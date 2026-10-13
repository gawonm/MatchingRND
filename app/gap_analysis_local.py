"""LLM 없이 키워드·임베딩 점수로 Gap을 분석하는 로컬 모드.

`app.gap_analysis`(LLM 모드)와 같은 `AnalysisState` 입력, 같은 `GapReport` 출력,
같은 `decide_label` 판정 규칙을 쓴다. 다른 점은 두 단계뿐이다.

- 요구기술 추출: RFP 요구항목의 줄을 그대로 요구기술로 사용한다 (기술요소 구조화 없음).
- 충족도 판단: 임베딩 유사도와 키워드 겹침을 합친 점수를 기준값으로 full/partial/none으로 나눈다.

점수는 "주제가 비슷한가"만 알려 주므로 의미상 충족 여부(예: LiDAR vs 카메라)와
부분충족의 의미(성능·범위 부족)는 판단하지 못한다. 기준값은 근거 없는 초기값이며
LLM 모드 결과와 비교하면서 조정해야 한다. 결과는 `GapReport.method == "local"`로 표시한다.

    report = run_gap_analysis_local(state, embed=embed)   # embed는 선택
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.common.schemas import BBox, Evidence, ExternalTechCandidate, SourceType, TechElement
from app.gap_analysis import (
    EmbedFn, SourceMatch, _PoolItem, _Requirement, _cosine, _element_id, _key, _rfp_sections,
    build_report, empty_report,
)

#: 요구기술로 보는 RFP 항목. 성능지표·평가방법·지원조건은 기술이 아니므로 제외한다.
REQUIREMENT_ITEMS = ("요구기술", "개발목표", "개발내용", "연구개발범위", "실증조건")
MIN_LINE_CHARS = 8
NAME_MAX_CHARS = 60

#: RFP·기술소개 어디에나 나오는 단어. 이것만 겹쳐서 비슷한 기술로 잡히는 일을 막는다.
STOPWORDS = frozenset({
    "기반", "기술", "개발", "확보", "구현", "적용", "활용", "이용", "관련", "대한", "위한", "통한",
    "방법", "기능", "수행", "제공", "구축", "고도화", "향상", "개선", "연구", "시스템", "개념", "내용",
})

#: 기술 요구가 아닌 항목(합의·인증·상용화·산출물 제출·계획서 작성 지침). 해당 단어가 있으면 제외한다.
#: 단어 단위 규칙이라 기술과 섞인 문장도 제외될 수 있다. 제외된 항목은 report.stats에 남는다.
NON_TECHNOLOGY = re.compile(
    "합의|협의|협약|계약|인허가|인증|상용화|사업화|수용성|보험|주관사|확약서|제출|계획서|"
    "인력양성|사업비|예산|가점|특허|논문"
)
#: 줄 첫머리의 글머리·번호. 이 표시가 있는 줄이 새 항목이고, 없는 줄은 앞 항목에 이어지는 줄이다.
_BULLET_START = re.compile(r"^\s*(?:[□■ㅇ◦○▪●•∙·ㆍ\-\*※]|\d+[.)]\s|[가-하][.)]\s|\([^)]{1,12}\)\s*)")
#: PDF는 줄 폭 한도 근처에서 줄이 바뀐다. 앞 줄이 이 길이 이상일 때만 다음 줄을 이어 붙인다.
WRAP_MIN_CHARS = 30
_TITLE = (r"(?:개념|개발\s*내용|개발\s*목표|연구개발\s*(?:내용|목표|범위)|요구\s*기술|"
          r"개발\s*위험\s*극복\s*방안|추진\s*방안|기대\s*효과|활용\s*방안)")
#: '□ 개념', '1. 개념 및 개발내용', '□ 개발위험 극복방안' 같은 소제목
HEADER_TITLE = re.compile(rf"^{_TITLE}(?:\s*(?:및|,|·)\s*{_TITLE})*$")

_BULLET = re.compile(r"^[\s□■ㅇ◦○▪●•∙·ㆍ\-\*※]+")
_ENUM = re.compile(r"^(?:\d+|[가-하])[.)]\s*")
_WORD = re.compile(r"[가-힣A-Za-z]{2,}|\d{2,}")


@dataclass(frozen=True)
class LocalThresholds:
    """충족도 기준값. 근거 있는 값이 아니라 초기값이다."""

    full: float = 0.70          # 종합 점수 ≥ full 이고 keyword ≥ full_keyword 이면 full
    full_keyword: float = 0.50
    partial: float = 0.50       # 종합 점수 ≥ partial 이고 공통 키워드가 있으면 partial
    embed_weight: float = 0.60  # 종합 = embed_weight × 임베딩 + (1 - embed_weight) × 키워드 (임베딩 없으면 키워드만)
    max_matches_per_source: int = 3


def default_tokenizer() -> Callable[[str], list[str]]:
    """Kiwi 명사·영문 토큰. 불러오지 못하면 정규식 토큰으로 대체한다."""
    try:
        from app.technology_rag.indexing.tokenizer import default_tokenizer as kiwi

        tokenizer = kiwi()
        tokenizer("테스트")
        return tokenizer
    except Exception:  # noqa: BLE001 - kiwipiepy 미설치·초기화 실패 시 대체
        return lambda text: [w.lower() for w in _WORD.findall(text)]


def _clean(text: str) -> str:
    return _ENUM.sub("", _BULLET.sub("", text.strip())).strip()


# =============================================================================
# ① 요구기술: RFP 요구항목 줄을 그대로 사용
# =============================================================================

@dataclass
class _Unit:
    """줄바꿈으로 갈라진 줄을 합친 요구 문장 하나."""

    item: str
    text: str
    sections: list
    last_len: int = 0   # 마지막 물리 줄의 길이. 짧으면 문장이 거기서 끝난 것으로 본다


def split_units(sections: Sequence[dict]) -> list[_Unit]:
    """RFP 줄을 글머리 기준으로 문장 단위로 합친다.

    - 글머리·번호로 시작하는 줄은 새 문장, 아니면 같은 항목의 앞 문장에 이어 붙인다.
    - 표 행은 ' | ' 셀로 나누고, 셀 라벨('연차별', '1차 년도' 같은 짧은 줄)은 버린다.
    - 성능지표 표(metric_table)는 요구 문장이 아니므로 건너뛴다.
    """
    units: list[_Unit] = []
    for section in sections:
        if section.get("kind") == "metric_table":
            continue
        table = section.get("kind") == "table_row"
        cells = re.split(r"\s\|\s", section["text"]) if table else [section["text"]]
        for cell in cells:
            for raw in cell.splitlines():
                line = raw.strip()
                if not line:
                    continue
                previous = units[-1] if units else None
                wrapped = (previous is not None and previous.item == section["item"]
                           and previous.last_len >= WRAP_MIN_CHARS
                           and not previous.text.rstrip().endswith("."))
                if _BULLET_START.match(line):
                    units.append(_Unit(section["item"], line, [section], len(line)))
                elif table and len(line) < MIN_LINE_CHARS:
                    continue  # 표의 셀 라벨
                elif wrapped:
                    previous.text += " " + line
                    previous.last_len = len(line)
                    if previous.sections[-1] is not section:
                        previous.sections.append(section)
                else:
                    units.append(_Unit(section["item"], line, [section], len(line)))
    return units


def _evidence_of(unit: _Unit, text: str, doc_id: str) -> Evidence:
    """여러 조각에 걸친 문장은 단일 좌표를 만들지 않는다 (LLM 모드의 _locate와 같은 규칙)."""
    spans = unit.sections
    pages = [span.get("page") for span in spans]
    single = len(spans) == 1
    bbox = spans[0].get("bbox") if single else None
    return Evidence(
        doc_id=doc_id, source=SourceType.RFP, section=unit.item,
        page=pages[0] - 1 if len(set(pages)) == 1 and isinstance(pages[0], int) else None,
        bbox=BBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]) if bbox and len(bbox) == 4 else None,
        quote=text, verified=True,
        extra={"page": pages[0] if single else None, "source_page_base": 1,
               "locations": [{"page": span.get("page"), "bbox": span.get("bbox"), "item": span["item"]}
                             for span in spans]},
    )


def extract_requirements_local(candidates: Sequence[ExternalTechCandidate],
                               tokenizer: Callable[[str], list[str]],
                               warnings: list[str],
                               excluded: list[dict[str, str]] | None = None) -> list[_Requirement]:
    """RFP 요구항목을 문장 단위로 합친 뒤 소제목·비기술 항목을 제외하고 요구기술로 사용한다."""
    merged: dict[str, _Requirement] = {}
    for candidate in candidates:
        sections = _rfp_sections(candidate)
        chosen = [s for s in sections if s["item"] in REQUIREMENT_ITEMS]
        if not chosen:
            # 파서가 요구 문장을 다른 항목(예: 성능지표)에 담은 RFP는 있는 원문으로 대체한다.
            chosen = [s for s in sections if s.get("kind") != "metric_table"]
            if chosen:
                items = ", ".join(dict.fromkeys(s["item"] for s in chosen))
                warnings.append(f"rfp {candidate.doc_id}: 요구기술 항목이 없어 '{items}' 항목 원문으로 대체했습니다.")
        if not chosen:
            warnings.append(f"rfp {candidate.doc_id}: 요구항목 원문이 없어 요구기술을 추출하지 않았습니다.")
            continue

        for unit in split_units(chosen):
            line = _clean(unit.text)
            if HEADER_TITLE.match(line):
                continue  # 소제목
            if len(line) < MIN_LINE_CHARS or line == unit.item or len(tokenizer(line)) < 2:
                continue
            found = NON_TECHNOLOGY.search(line)
            if found:
                if excluded is not None:
                    excluded.append({"rfp": candidate.doc_id, "text": line[:NAME_MAX_CHARS],
                                     "reason": f"비기술 항목 단어: {found.group()}"})
                continue
            evidence = _evidence_of(unit, line, candidate.doc_id)
            key = _key(line)
            if key not in merged:
                name = line if len(line) <= NAME_MAX_CHARS else line[:NAME_MAX_CHARS] + "…"
                merged[key] = _Requirement(
                    element=TechElement(
                        element_id=_element_id(line), name=name, surface_forms=[line],
                        origin=SourceType.RFP, evidences=[evidence],
                    ),
                    rfp_doc_ids=[candidate.doc_id], clear=True,
                )
            else:
                requirement = merged[key]
                requirement.element.evidences.append(evidence)
                if candidate.doc_id not in requirement.rfp_doc_ids:
                    requirement.rfp_doc_ids.append(candidate.doc_id)
    return list(merged.values())


# =============================================================================
# ② 충족도: 키워드 + 임베딩 점수
# =============================================================================

def _candidate_text(item: _PoolItem) -> str:
    element = item.element
    return " / ".join([element.name, *[ev.quote for ev in element.evidences[:3]]])


def _keyword_score(req_tokens: set[str], name_tokens: set[str], evidence_tokens: set[str]) -> tuple[float, list[str]]:
    """기술명 토큰이 요구 줄에 얼마나 포함되는지, 요구 줄 토큰이 기술명·근거에 얼마나 덮이는지의 큰 값."""
    shared = sorted(req_tokens & (name_tokens | evidence_tokens))
    if not shared:
        return 0.0, []
    name_in_req = len(name_tokens & req_tokens) / len(name_tokens) if name_tokens else 0.0
    req_covered = len(req_tokens & (name_tokens | evidence_tokens)) / len(req_tokens)
    return max(name_in_req, req_covered), shared


def make_local_aligner(requirements: Sequence[_Requirement], embed: EmbedFn | None,
                       tokenizer: Callable[[str], list[str]], thresholds: LocalThresholds):
    req_text = {r.element.element_id: r.element.surface_forms[0] for r in requirements}
    req_tokens = {rid: set(tokenizer(text)) for rid, text in req_text.items()}
    req_vectors: dict[str, Sequence[float]] = {}
    if embed is not None and req_text:
        vectors = list(embed(list(req_text.values())))
        req_vectors = dict(zip(req_text, vectors))
    pool_cache: dict[str, object] = {}

    def prepare(pool: Sequence[_PoolItem]):
        texts = [_candidate_text(item) for item in pool]
        pool_cache["vectors"] = list(embed(texts)) if embed is not None and texts else []
        pool_cache["name_tokens"] = [set(tokenizer(" ".join([i.element.name, *i.element.synonyms]))) for i in pool]
        pool_cache["evidence_tokens"] = [
            set(tokenizer(" ".join(ev.quote for ev in i.element.evidences))) for i in pool
        ]
        pool_cache["size"] = len(pool)

    def align(requirement: _Requirement, pool: Sequence[_PoolItem]) -> list[SourceMatch]:
        if pool_cache.get("size") != len(pool):
            prepare(pool)
        rid = requirement.element.element_id
        tokens = req_tokens[rid]
        scored = []
        for index, item in enumerate(pool):
            keyword, shared = _keyword_score(tokens, pool_cache["name_tokens"][index],
                                             pool_cache["evidence_tokens"][index])
            if not shared:
                continue  # 공통 키워드가 없으면 임베딩이 높아도 후보로 보지 않는다
            if embed is not None:
                cosine = _cosine(req_vectors[rid], pool_cache["vectors"][index])
                score = thresholds.embed_weight * cosine + (1 - thresholds.embed_weight) * keyword
            else:
                cosine, score = None, keyword
            if score >= thresholds.full and keyword >= thresholds.full_keyword:
                coverage = "full"
            elif score >= thresholds.partial:
                coverage = "partial"
            else:
                continue
            scored.append((score, keyword, cosine, shared, coverage, item))

        matches, per_source = [], {}
        for score, keyword, cosine, shared, coverage, item in sorted(scored, key=lambda row: -row[0]):
            if per_source.get(item.source, 0) >= thresholds.max_matches_per_source:
                continue
            per_source[item.source] = per_source.get(item.source, 0) + 1
            best = max(item.element.evidences, key=lambda ev: len(set(tokenizer(ev.quote)) & tokens))
            embed_text = f"임베딩 {cosine:.2f} · " if cosine is not None else "임베딩 미사용 · "
            matches.append(SourceMatch(
                source=item.source, element_name=item.element.name, coverage=coverage,
                reason=f"[로컬 점수 판정] {embed_text}키워드 {keyword:.2f} → 종합 {score:.2f}"
                       f" / 공통 키워드: {', '.join(shared)}",
                verified=True, doc_id=item.doc_id, title=item.title, provider=item.provider,
                transfer_condition=item.transfer_condition, evidences=[best],
            ))
        return sorted(matches, key=lambda m: m.coverage != "full")

    return align


# =============================================================================
# 진입점
# =============================================================================

def run_gap_analysis_local(state, *, embed: EmbedFn | None = None,
                           tokenizer: Callable[[str], list[str]] | None = None,
                           thresholds: LocalThresholds | None = None):
    """LLM 없이 점수 기반으로 GapReport를 만든다. 입력·출력·판정 규칙은 LLM 모드와 같다."""
    if not state.rfp.candidates:
        return empty_report(state, method="local")
    thresholds = thresholds or LocalThresholds()
    base_tokenizer = tokenizer or default_tokenizer()

    def tokenizer(text: str) -> list[str]:
        return [token for token in base_tokenizer(text) if token not in STOPWORDS]

    warnings: list[str] = []
    started = time.perf_counter()
    excluded: list[dict[str, str]] = []
    requirements = extract_requirements_local(state.rfp.candidates, tokenizer, warnings, excluded)
    report = build_report(
        state, requirements, make_local_aligner(requirements, embed, tokenizer, thresholds),
        warnings, method="local",
    )
    report.stats = {
        "seconds": round(time.perf_counter() - started, 2), "calls": 0, "prompt_tokens": 0,
        "completion_tokens": 0, "embedding": embed is not None,
        "thresholds": thresholds.__dict__, "excluded_requirements": excluded,
    }
    return report
