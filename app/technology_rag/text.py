"""
텍스트 정제 / 정규화 유틸.

PDF 파서(technology_rag/parsing/pdf_parser.py)와 이후 단계(청킹, 인용 검증)가
공통으로 쓰는 순수 함수 모음. 외부 의존성 없음.
"""

from __future__ import annotations

import re
from datetime import date

# --- 상수 ---------------------------------------------------------------------

#: Wingdings 글머리표가 PDF에서 이 문자로 추출된다 (단독 라인으로 나온다)
BULLET_CHARS = frozenset({"Ÿ", "", "", "•"})

#: 포스코 PDF는 어절 구분 공백이 U+0001 로 추출된다. 공백으로 치환한다.
_SOFT_SEP = "\x01"

#: 개행/탭을 제외한 제어문자 (U+0000~U+001F 중)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"[ \t  -​　]+")

#: 이미지 출처/도면 캡션. 본문 검색 노이즈가 되므로 본문에서 제외한다.
#:   '*출처: 철도경제'   '<철도 인프라>'
_CAPTION_RES = (
    re.compile(r"^\*\s*출처\s*[:：]?.*$"),
    re.compile(r"^<[^<>]{1,40}>$"),
)

_DATE_RE = re.compile(r"(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})")


# --- 라인 정제 ----------------------------------------------------------------

def clean_line(raw: str) -> str:
    """PDF 한 줄을 정제한다.

    - U+0001(포스코 어절 구분자) → 공백
    - 기타 제어문자 제거, 연속 공백 1개로, 양끝 공백 제거
    NFKC 정규화는 하지 않는다 (원문과의 문자열 일치가 Evidence 검증의 전제).
    """
    s = raw.replace(_SOFT_SEP, " ")
    s = _CTRL_RE.sub("", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def is_bullet(text: str) -> bool:
    """정제된 라인이 글머리표 단독인가."""
    return text.strip() in BULLET_CHARS


def is_caption(text: str) -> bool:
    """정제된 라인이 이미지 출처/캡션 표기인가."""
    t = text.strip()
    return any(p.match(t) for p in _CAPTION_RES)


# --- 인용 검증용 ---------------------------------------------------------------

def compact(text: str) -> str:
    """모든 공백을 제거한 비교용 문자열.

    LLM이 낸 quote가 원문 chunk에 실제로 있는지 확인할 때
    `compact(quote) in compact(chunk_text)` 로 비교한다.
    """
    return re.sub(r"\s+", "", text)


# --- 서지정보 -----------------------------------------------------------------

def normalize_application_number(value: object) -> str | None:
    """출원번호/등록번호에서 숫자만 남긴다. PDF↔엑셀 조인 키.

    '10-2008-0054298' -> '1020080054298'
    1020070046575 (int) -> '1020070046575'
    1.020070046575e12 (float) 은 정수 변환 후 처리한다.
    """
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        value = int(value)
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def parse_date(value: object) -> date | None:
    """'2028-06-10' / '2028.06.10' / date / Timestamp -> date. 실패 시 None."""
    if value is None:
        return None
    if isinstance(value, date):
        # pandas NaT 는 date 의 인스턴스로 판정되지만 year 가 NaN(float)이다
        try:
            return date(value.year, value.month, value.day)
        except (TypeError, ValueError):
            return None
    m = _DATE_RE.search(str(value))
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def make_doc_id(source: str, year: int, seq_no: str | int) -> str:
    """'pub', 2026, '001' -> 'pub-2026-001'"""
    return f"{source}-{year}-{int(seq_no):03d}"
