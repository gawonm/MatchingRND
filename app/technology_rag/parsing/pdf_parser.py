"""
기술나눔 기술소개자료 PDF → TechDocument 파서.

대상: 공공기관 PDF(298건), 포스코 PDF(293건). 두 PDF의 레이아웃은 동일하다.
엑셀 조인/메타 보강은 이 파일의 책임이 아니다 (parsing/merger.py).

처리 흐름
---------
1. 본문 페이지(CONTENT_START_PAGE~)에서 라인 단위로 텍스트+좌표를 추출한다.
2. 표지 일련번호(001~)가 같은 연속 페이지를 한 레코드로 묶는다.
3. 섹션 제목 배너 이미지의 md5로 섹션 경계(y좌표)를 얻는다. (제목이 이미지라 OCR 불필요)
4. 배너 아래 라인을 섹션에 귀속시키고, 섹션별로 항목(불릿/표 행)을 재구성한다.
5. 배너 위 표지 영역에서 기술명·분류·발명자·출원/등록 정보를 뽑는다.

모든 항목은 TextBlock(page, bbox)로 보존한다 → Evidence 원문 하이라이트의 근거.
"""

from __future__ import annotations

import hashlib
import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pymupdf

from app.common.schemas import BBox, SourceType, TechTaxonomy
from app.technology_rag.schemas import PatentInfo, Section, SectionCode, TechDocument, TextBlock
from app.technology_rag.text import clean_line, is_bullet, is_caption, make_doc_id, parse_date
from app.technology_rag import constants as C

log = logging.getLogger(__name__)

_SEQ_RE = re.compile(r"^\d{3}$")
_DATE_FULL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_APP_RE = re.compile(C.APPLICATION_NO_PATTERN)
_REG_RE = re.compile(C.REGISTRATION_NO_PATTERN)
_PAREN_DATE_RE = re.compile(C.PAREN_DATE_PATTERN)


# =============================================================================
# 내부 자료구조
# =============================================================================

@dataclass(slots=True)
class Line:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str  # clean_line 적용 후
    soft_end: bool = False  # 원문 줄 끝에 공백(또는 U+0001)이 있었는가 = 단어 경계에서 끊긴 줄


@dataclass(slots=True)
class Banner:
    y0: float
    code: SectionCode


@dataclass(slots=True)
class PageData:
    pno: int
    lines: list[Line]
    banners: list[Banner]


def _starts_hangul(text: str) -> bool:
    return bool(text) and "가" <= text[0] <= "힣"


def _join(lines: list[Line]) -> str:
    """줄바꿈으로 끊긴 줄들을 문장으로 잇는다.

    - 앞줄 끝에 공백이 있었으면 단어 경계 → 공백 1개
    - 공백이 없으면 단어 중간에서 끊긴 것('상태에' / '서') → 공백 없이 붙인다
    - 단, 다음 줄이 한글로 시작하지 않으면('연화점' / '(Softening') 단어 경계로 본다
    """
    out = ""
    for i, l in enumerate(lines):
        if i and (lines[i - 1].soft_end or not _starts_hangul(l.text)):
            out += " "
        out += l.text
    return out.strip()


@dataclass(slots=True)
class Item:
    """섹션 안의 의미 단위 1개 (불릿 1개 / 표 행 1개 / 단독 문장 1개)."""

    text: str
    page: int
    lines: list[Line] = field(default_factory=list)

    def bbox(self) -> BBox:
        return BBox(
            x0=min(l.x0 for l in self.lines),
            y0=min(l.y0 for l in self.lines),
            x1=max(l.x1 for l in self.lines),
            y1=max(l.y1 for l in self.lines),
        )


# =============================================================================
# 페이지 단위 추출
# =============================================================================

def _extract_lines(page: pymupdf.Page) -> list[Line]:
    out: list[Line] = []
    for blk in page.get_text("dict")["blocks"]:
        if blk["type"] != 0:
            continue
        for ln in blk["lines"]:
            raw = "".join(sp["text"] for sp in ln["spans"])
            text = clean_line(raw)
            if not text:
                continue
            x0, y0, x1, y1 = ln["bbox"]
            if y0 > C.FOOTER_Y_THRESHOLD:  # '- 1 -' 페이지 번호
                continue
            soft = raw.endswith((" ", "", " "))
            out.append(Line(page.number, x0, y0, x1, y1, text, soft))
    return out


class _BannerReader:
    """섹션 제목 배너 이미지 → SectionCode. xref별 digest를 캐시한다."""

    def __init__(self, doc: pymupdf.Document) -> None:
        self._doc = doc
        self._digest: dict[int, str | None] = {}
        self.unknown: dict[str, int] = {}

    def _digest_of(self, xref: int) -> str | None:
        if xref not in self._digest:
            try:
                img = self._doc.extract_image(xref)["image"]
                self._digest[xref] = hashlib.md5(img).hexdigest()[:10]
            except Exception:  # noqa: BLE001  손상 이미지는 무시
                self._digest[xref] = None
        return self._digest[xref]

    def read(self, page: pymupdf.Page) -> list[Banner]:
        banners: list[Banner] = []
        for im in page.get_image_info(xrefs=True):
            xref = im["xref"]
            x0, y0, x1, y1 = im["bbox"]
            # 배너는 폭이 넓고 높이가 얇다. 큰 사진은 digest 계산을 건너뛴다.
            if not xref or (x1 - x0) <= C.BANNER_MIN_WIDTH or (y1 - y0) >= C.BANNER_MAX_HEIGHT:
                continue
            d = self._digest_of(xref)
            code = C.SECTION_BANNERS.get(d or "")
            if code is None:
                self.unknown[d or "?"] = self.unknown.get(d or "?", 0) + 1
                continue
            banners.append(Banner(y0=y0, code=code))
        return sorted(banners, key=lambda b: b.y0)


def _record_seq(lines: list[Line]) -> str | None:
    """페이지의 일련번호(001~). 표지는 제목 옆, 이어지는 페이지는 러닝헤더 옆에 있다."""
    for l in lines:
        if l.y0 < C.TITLE_Y_THRESHOLD and _SEQ_RE.match(l.text):
            return l.text
    return None


# =============================================================================
# 섹션 본문 재구성
# =============================================================================

def _col(l: Line) -> int:
    return 1 if l.x0 >= C.COLUMN_SPLIT_X else 0


def _find_table_header(lines: list[Line]) -> tuple[Line, Line] | None:
    """'구분|내용' / '구성|내용' 헤더 쌍을 찾는다."""
    lefts = [l for l in lines if l.text in C.TABLE_HEADER_LEFT]
    rights = [l for l in lines if l.text == C.TABLE_HEADER_RIGHT]
    for a in lefts:
        for b in rights:
            if abs(a.y0 - b.y0) <= C.TABLE_HEADER_DY_TOL:
                return a, b
    return None


def _table_items(rest: list[Line], bullets: list[Line]) -> list[Item]:
    """표 섹션: 행 = 라벨 + 불릿 + 내용. 라벨/내용은 불릿 x 기준으로 가른다."""
    bullets = sorted(bullets, key=lambda b: b.y0)
    bx0 = statistics.median(b.x0 for b in bullets)
    bx1 = statistics.median(b.x1 for b in bullets)

    rows: list[dict] = [{"bullet": b, "label": [], "content": []} for b in bullets]

    def row_of(y: float) -> dict | None:
        cand = None
        for r in rows:
            if r["bullet"].y0 <= y + C.TABLE_LABEL_Y_TOL:
                cand = r
        return cand

    extras: list[Line] = []
    ordered = sorted(rest, key=lambda l: (l.y0, l.x0))

    # 1차: 내용 줄 (불릿 오른쪽)
    leftover: list[Line] = []
    for l in ordered:
        r = row_of(l.y0)
        if r is not None and l.x0 >= bx1 - 1:
            prev = r["content"][-1] if r["content"] else r["bullet"]
            first_x = r["content"][0].x0 if r["content"] else l.x0
            if l.y0 - prev.y0 <= C.CONT_MAX_DY and abs(l.x0 - first_x) <= C.CONT_X_TOL:
                r["content"].append(l)
                continue
        leftover.append(l)

    # 2차: 라벨 줄 (불릿 왼쪽, 행 범위 안)
    for l in leftover:
        r = row_of(l.y0)
        if r is not None and l.x1 <= bx0 + 1:
            row_end = max([r["bullet"].y0] + [c.y0 for c in r["content"]])
            if l.y0 <= row_end + C.TABLE_ROW_END_TOL:
                r["label"].append(l)
                continue
        extras.append(l)

    items: list[Item] = []
    for r in rows:
        label = _join(sorted(r["label"], key=lambda l: (l.y0, l.x0)))
        body = _join(r["content"])
        text = f"{label}: {body}" if label and body else (label or body)
        if not text:
            continue
        lines = [r["bullet"], *r["label"], *r["content"]]
        items.append(Item(text=text, page=lines[0].page, lines=lines))
    for l in extras:  # 표 아래 도면 캡션/차트 제목 등
        items.append(Item(text=l.text, page=l.page, lines=[l]))
    return items


def _list_items(rest: list[Line], bullets: list[Line]) -> list[Item]:
    """일반 섹션: 불릿 라인이 항목 시작. 같은 들여쓰기의 다음 줄은 이어진 줄."""

    def has_bullet(l: Line) -> bool:
        return any(
            _col(b) == _col(l) and abs(b.y0 - l.y0) <= C.BULLET_Y_TOL and b.x1 <= l.x0 + 1
            for b in bullets
        )

    items: list[Item] = []
    cur: Item | None = None
    cur_x0 = 0.0
    for l in sorted(rest, key=lambda l: (_col(l), l.y0, l.x0)):
        if has_bullet(l):
            cur = Item(text="", page=l.page, lines=[l])
            cur_x0 = l.x0
            items.append(cur)
        elif (
            cur is not None
            and _col(l) == _col(cur.lines[-1])
            and abs(l.x0 - cur_x0) <= C.CONT_X_TOL
            and l.y0 - cur.lines[-1].y0 <= C.CONT_MAX_DY
        ):
            cur.lines.append(l)
        else:  # 불릿 없는 단독 문장
            cur = Item(text="", page=l.page, lines=[l])
            cur_x0 = l.x0
            items.append(cur)
    for it in items:
        it.text = _join(it.lines)
    return items


def _section_items(lines: list[Line]) -> list[Item]:
    """한 페이지 안의 한 섹션 라인들 → 항목 목록."""
    bullets = [l for l in lines if is_bullet(l.text)]
    rest = [l for l in lines if not is_bullet(l.text) and not is_caption(l.text)]

    hdr = _find_table_header(rest)
    if hdr is not None:
        rest = [l for l in rest if l is not hdr[0] and l is not hdr[1]]
        if bullets:
            return _table_items(rest, bullets)
    return _list_items(rest, bullets)


# =============================================================================
# 표지 파싱
# =============================================================================

def _parse_cover(lines: list[Line], warns: list[str]) -> dict:
    provider = None
    for l in lines:
        if l.y0 < C.HEADER_Y_THRESHOLD:
            m = re.search(C.PROVIDER_PATTERN, l.text)
            if m:
                provider = m.group(1).strip()
    body = [l for l in lines if l.y0 >= C.HEADER_Y_THRESHOLD]

    # 분류: 우측 열(x>=470)에 대/중/소 순으로 세로 배치
    tax_lines = sorted(
        (l for l in body if l.x0 >= C.TAXONOMY_X_MIN and l.y0 < 162), key=lambda l: l.y0
    )
    # 항목 간격(~26pt)보다 좁은(~13pt) 줄은 앞 항목이 줄바꿈된 것이다.
    groups: list[list[Line]] = []
    for l in tax_lines:
        if groups and l.y0 - groups[-1][-1].y0 <= C.TAXONOMY_WRAP_DY:
            groups[-1].append(l)
        else:
            groups.append([l])
    tax = [_join(g) for g in groups]
    if len(tax) != 3:
        warns.append(f"분류 항목 수 {len(tax)} (기대 3): {tax}")
    taxonomy = TechTaxonomy(
        major=tax[0] if len(tax) > 0 else None,
        middle=tax[1] if len(tax) > 1 else None,
        minor=tax[2] if len(tax) > 2 else None,
    )

    # 기술명/부제: 일련번호 오른쪽, 분류 왼쪽 영역. '(' 로 시작하는 줄부터 부제.
    left = sorted(
        (
            l
            for l in body
            if l.x0 < C.TAXONOMY_X_MIN
            and l.y0 < 162
            and not (_SEQ_RE.match(l.text) and l.x0 < 90)
        ),
        key=lambda l: (l.y0, l.x0),
    )
    title_parts: list[Line] = []
    sub_parts: list[Line] = []
    for i, l in enumerate(left):
        if i > 0 and l.text.startswith("(") and not sub_parts:
            sub_parts.append(l)
        elif sub_parts:
            sub_parts.append(l)
        else:
            title_parts.append(l)
    title = _join(title_parts)
    subtitle = _join(sub_parts) or None
    if subtitle and subtitle.startswith("(") and subtitle.endswith(")"):
        subtitle = subtitle[1:-1].strip()
    if not title:
        warns.append("기술명 없음")

    # 발명자 / 만료일 / 출원·등록 정보 (y>=162)
    inventor_lines: list[Line] = []
    expiry = None
    app_raw = app_date = reg_raw = reg_date = None
    for l in sorted((l for l in body if l.y0 >= 162), key=lambda l: (l.y0, l.x0)):
        if _DATE_FULL_RE.match(l.text):
            expiry = parse_date(l.text)
            continue
        m_app = _APP_RE.search(l.text)
        if m_app:
            app_raw = m_app.group(1)
            d = _PAREN_DATE_RE.search(l.text)
            app_date = parse_date(d.group(1)) if d else None
            continue
        m_reg = _REG_RE.search(l.text)
        if m_reg and l.text.lstrip().startswith(m_reg.group(1)):
            reg_raw = m_reg.group(1)
            d = _PAREN_DATE_RE.search(l.text)
            reg_date = parse_date(d.group(1)) if d else None
            continue
        if l.y0 < 190:
            inventor_lines.append(l)
    inventors = [
        n.strip()
        for n in re.split(r"[,，、]", _join(inventor_lines))
        if n.strip()
    ]
    if app_raw is None:
        warns.append("출원번호 추출 실패")

    patent = PatentInfo(
        application_number=app_raw,
        application_number_raw=app_raw,
        application_date=app_date,
        registration_number=reg_raw,
        registration_number_raw=reg_raw,
        registration_date=reg_date,
        expiry_date=expiry,
    )
    return {
        "provider": provider,
        "taxonomy": taxonomy,
        "title": title,
        "subtitle": subtitle,
        "inventors": inventors,
        "patent": patent,
    }


# =============================================================================
# 레코드 → TechDocument
# =============================================================================

def _build_document(
    *,
    source: SourceType,
    year: int,
    seq: str,
    pages: list[PageData],
    pdf_path: str,
) -> TechDocument:
    warns: list[str] = []
    if len(pages) != 2:
        warns.append(f"레코드 페이지 수 {len(pages)} (기대 2)")

    first = pages[0]
    if not first.banners:
        warns.append("첫 페이지에 섹션 배너 없음")
    first_banner_y = first.banners[0].y0 if first.banners else float("inf")
    cover = [l for l in first.lines if l.y0 < first_banner_y - 2]
    meta = _parse_cover(cover, warns)

    # 섹션별 라인 수집
    by_section: dict[SectionCode, list[Line]] = {c: [] for c in C.SECTION_ORDER}
    current: SectionCode | None = None
    for pi, pd in enumerate(pages):
        for l in pd.lines:
            sec = None
            for b in pd.banners:
                if l.y0 >= b.y0 - 2:
                    sec = b.code
            if sec is None:
                if pi == 0:
                    continue  # 표지 영역
                if l.y0 < 120 or current is None:
                    continue  # 이어지는 페이지의 러닝헤더/제목
                sec = current  # 배너 위인데 헤더가 아니면 직전 섹션이 이어지는 것
            current = sec
            by_section[sec].append(l)

    sections: list[Section] = []
    for code in C.SECTION_ORDER:
        sec_lines = by_section[code]
        items: list[Item] = []
        for pno in sorted({l.page for l in sec_lines}):
            items.extend(_section_items([l for l in sec_lines if l.page == pno]))
        blocks = [
            TextBlock(page=it.page, bbox=it.bbox(), text=it.text, order=i)
            for i, it in enumerate(items)
        ]
        text = "\n".join(it.text for it in items)
        if not text:
            warns.append(f"섹션 비어 있음: {code.value}")
        sections.append(
            Section(code=code, title=C.SECTION_TITLES[code], text=text, blocks=blocks)
        )

    return TechDocument(
        doc_id=make_doc_id(source.value, year, seq),
        source=source,
        seq_no=seq,
        title=meta["title"],
        subtitle=meta["subtitle"],
        provider=meta["provider"],
        taxonomy=meta["taxonomy"],
        inventors=meta["inventors"],
        patent=meta["patent"],
        pdf_path=pdf_path,
        page_start=pages[0].pno,
        page_end=pages[-1].pno,
        sections=sections,
        extra={"parse_warnings": warns},
    )


# =============================================================================
# 공개 API
# =============================================================================

def iter_documents(
    source: SourceType,
    raw_dir: Path,
    *,
    limit: int | None = None,
    root: Path | None = None,
) -> Iterator[TechDocument]:
    """PDF를 읽어 TechDocument를 하나씩 생성한다.

    Args:
        source: PUBLIC_TECH | POSCO_TECH
        raw_dir: data/raw 디렉터리
        limit: 앞에서부터 N건만 (테스트/디버깅용)
        root: pdf_path 의 기준 디렉터리. 기본은 raw_dir 의 두 단계 위(프로젝트 루트).
              산출물에 절대경로가 들어가면 다른 PC(팀원)에서 원문을 열 수 없으므로
              항상 루트 기준 상대경로('data/raw/xxx.pdf')로 저장한다.
    """
    spec = C.SOURCE_SPECS[source]
    path = Path(raw_dir) / spec["pdf"]
    year = spec["year"]
    base = Path(root) if root is not None else Path(raw_dir).resolve().parent.parent
    rel = path.resolve().relative_to(base.resolve()).as_posix()

    doc = pymupdf.open(path)
    banner_reader = _BannerReader(doc)
    try:
        cur_seq: str | None = None
        cur_pages: list[PageData] = []
        emitted = 0

        def flush() -> TechDocument | None:
            if cur_seq is None or not cur_pages:
                return None
            return _build_document(
                source=source, year=year, seq=cur_seq, pages=cur_pages, pdf_path=rel
            )

        for pno in range(C.CONTENT_START_PAGE, doc.page_count):
            page = doc[pno]
            lines = _extract_lines(page)
            seq = _record_seq(lines)
            if seq is None:  # 대분류 간지 등
                continue
            if seq != cur_seq:
                d = flush()
                if d is not None:
                    yield d
                    emitted += 1
                    if limit is not None and emitted >= limit:
                        return
                cur_seq, cur_pages = seq, []
            cur_pages.append(PageData(pno, lines, banner_reader.read(page)))
        d = flush()
        if d is not None and (limit is None or emitted < limit):
            yield d
        if banner_reader.unknown:
            log.warning("미등록 배너 이미지 digest: %s", banner_reader.unknown)
    finally:
        doc.close()


def parse_pdf(
    source: SourceType, raw_dir: Path, *, limit: int | None = None, root: Path | None = None
) -> list[TechDocument]:
    return list(iter_documents(source, raw_dir, limit=limit, root=root))
