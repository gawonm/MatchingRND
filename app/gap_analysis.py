"""Technology alignment and Gap decision over an orchestrated AnalysisState.

RFP 요구기술을 기술요소 축으로 삼아 기업 보유기술, 기술나눔 외부기술, NTIS 선행과제를
비교하고 PROJECT_PLAN의 판정 우선순위로 GapLabel을 결정한다.

- LLM은 RFP 요구기술 추출과 후보별 충족도(full/partial/none) 판단에만 사용한다.
  라벨은 `decide_label`의 결정론적 규칙으로 정한다.
- LLM이 제시한 quote는 원문과 대조해 검증된 경우에만 판정에 사용한다.
- NTIS 과제는 참고 근거로만 첨부하고 Gap 판정의 단독 근거로 사용하지 않는다.
- 검색 결과가 비어 있다는 사실만으로 추가 R&D 필요를 추정하지 않는다.

    from app.orchestrator import AnalysisRequest, RagOrchestrator
    from app.gap_analysis import run_gap_analysis

    state = RagOrchestrator().run(AnalysisRequest(problem=..., owned_technologies=[...]))
    report = run_gap_analysis(state)
    report.model_dump(mode="json")  # 최종 답변 생성 단계의 근거
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.common.paths import PROJECT_ROOT
from app.common.schemas import BBox, Evidence, ExternalTechCandidate, GapLabel, SourceType, TechElement

if TYPE_CHECKING:
    from app.orchestrator import AnalysisState

COMPANY_DOC_ID = "company-input"
TECHNOLOGY_SOURCES = {SourceType.PUBLIC_TECH, SourceType.POSCO_TECH}
Coverage = Literal["full", "partial", "none"]
# llm(messages, response_model) -> response_model 인스턴스. 테스트에서는 가짜 함수를 주입한다.
StructuredLLM = Callable[[list[dict[str, str]], type[BaseModel]], BaseModel]
# embed(texts) -> 텍스트별 벡터. 예: lambda texts: embedder.encode(texts)[0]
EmbedFn = Callable[[Sequence[str]], Sequence[Sequence[float]]]


# =============================================================================
# 출력 스키마 (최종 답변 생성 단계로 넘기는 계약)
# =============================================================================

class SourceMatch(BaseModel):
    """요구기술 1개와 특정 출처 기술 1개의 매칭."""

    source: SourceType
    element_name: str
    coverage: Coverage
    reason: str
    verified: bool = Field(description="LLM이 제시한 근거 문장이 출처 원문에서 확인되었는지")
    doc_id: str | None = None
    title: str | None = None
    provider: str | None = Field(default=None, description="기술 제공기관 (어디서 보완하는가)")
    transfer_condition: str | None = Field(default=None, description="기술나눔 이전조건")
    evidences: list[Evidence] = Field(default_factory=list)


class GapItem(BaseModel):
    """기술요소 축 1행: RFP 요구기술 하나에 대한 판정."""

    requirement: TechElement
    rfp_doc_ids: list[str]
    requirement_clear: bool = Field(description="RFP가 해당 기술을 명시적으로 요구하는지")
    label: GapLabel
    decision_path: str = Field(description="라벨을 결정한 규칙")
    company: list[SourceMatch] = Field(default_factory=list)
    external: list[SourceMatch] = Field(default_factory=list)
    ntis_references: list[SourceMatch] = Field(
        default_factory=list, description="유사·선행 과제 참고 근거 (판정에 직접 사용하지 않음)"
    )
    policy_check: list[str] = Field(default_factory=list, description="제도·법령 확인이 필요한 사항")


class GapReport(BaseModel):
    problem: str
    method: str = Field(default="llm", description="요구기술 추출·충족도 판단 방식: llm | local")
    items: list[GapItem] = Field(default_factory=list)
    owned_not_required: list[str] = Field(
        default_factory=list, description="보유기술 중 RFP 요구기술과 매칭되지 않은 항목"
    )
    summary: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict, description="호출 수·토큰·소요 시간 등 실행 정보")


# =============================================================================
# LLM 응답 스키마 (Structured Outputs는 모든 필드를 필수로 요구하므로 기본값을 두지 않는다)
# =============================================================================

class ExtractedRequirement(BaseModel):
    name: str
    is_technology: bool
    synonyms: list[str]
    broader: list[str]
    narrower: list[str]
    function: str | None
    target: str | None
    quote: str
    clear: bool


class RequirementExtraction(BaseModel):
    requirements: list[ExtractedRequirement]


class CoverageJudgement(BaseModel):
    # 필드 순서가 생성 순서다. 이유를 먼저 쓰게 해서 이유와 모순되는 coverage를 줄인다.
    candidate_index: int
    reason: str
    coverage: Coverage
    quote: str


class AlignmentJudgements(BaseModel):
    judgements: list[CoverageJudgement]


EXTRACTION_PROMPT = """당신은 국가 R&D RFP에서 요구기술을 기술요소 단위로 추출합니다.
- sections에 있는 원문만 사용하고 원문에 없는 기술을 만들지 마세요.
- 각 기술요소는 하나의 기술(예: 'LiDAR 객체 인지', 'Edge AI 실시간 추론')로 작성하고 지원조건·사업 일반 설명은 제외합니다.
- is_technology: 연구개발로 개발·확보·입증해야 하는 기술, 시스템, 성능 요구이면 true입니다. 다음은 기술이 아니므로 false로 표시하세요:
  사업관리·일정·예산, 주관기관·실증기관과의 합의·협약·계약, 인허가·인증 취득 절차, 상용화·사업화·시장 확산 계획,
  인력양성, 산출물 제출(특허·논문·보고서·시제품 개수), 연구개발계획서 작성 지침.
  시제품 제작 자체를 기술요소로 만들지 말고, 시제품으로 구현할 핵심 기술을 기술요소로 삼으세요.
  성능 검증·실증은 기술의 성능을 입증하는 요구일 때만 true입니다.
- quote에는 근거가 된 문장을 sections의 text에서 그대로 복사하세요. 줄이 바뀌어도 이어지는 문장이면 함께 복사해도 되지만, 요약하거나 단어를 바꾸지 말고 '-', '□' 같은 글머리 기호는 빼세요.
- clear는 RFP가 해당 기술의 개발·확보를 명시적으로 요구하면 true, 배경 언급이나 모호한 표현이면 false입니다.
- synonyms·broader·narrower에는 일반적으로 통용되는 표현만 적고, function·target은 원문에서 알 수 없으면 null로 둡니다."""

ALIGNMENT_PROMPT = """당신은 RFP 요구기술 하나를 비교 후보 기술들이 얼마나 충족하는지 판정합니다.
- 명칭이 달라도 기능·적용대상·상하위 관계를 함께 고려해 같은 기술인지 판단하세요.
- 먼저 reason에 '요구기술이 구체적으로 요구하는 기능'과 '후보 evidence가 명시적으로 서술한 기능'을 비교해 쓰고, 그 결론에 맞게 coverage를 정하세요.
- full: 후보 evidence가 요구기술의 핵심 기능을 직접 서술함.
- partial: 후보 evidence가 요구기술의 구체적인 기능·구성요소 일부를 명시적으로 서술하지만 성능·적용대상·범위가 부족함.
- none: 그 외 모두. 둘 다 AI·센서·설비 진단처럼 분야나 주제만 비슷한 것은 partial이 아니라 none입니다.
- reason을 '직접적인 관련성이 부족하다', '명시되어 있지 않다'처럼 쓰게 된다면 coverage는 반드시 none이어야 합니다.
- 판단 근거는 각 후보의 evidence 문장만 사용하세요. 후보 이름이나 추측으로 판단하지 마세요.
- quote에는 판단의 근거가 된 후보 evidence 문장을 그대로 복사하세요. none이면 빈 문자열로 둡니다.
- 모든 후보에 대해 candidate_index별로 judgement를 하나씩 반환하세요."""


class OpenAIStructuredLLM:
    """OpenAI Structured Outputs 호출. 클라이언트는 첫 호출 시 생성한다."""

    def __init__(self, model: str = "gpt-4o-mini", *, temperature: float = 0.0,
                 seed: int | None = 0, client: Any = None):
        self.model = model
        self.temperature = temperature
        self.seed = seed
        self._client = client
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    def _get_client(self):
        if self._client is None:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env")
            if not os.environ.get("OPENAI_API_KEY"):
                raise RuntimeError("OPENAI_API_KEY가 없습니다. 프로젝트 루트의 .env에 설정하세요.")
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def __call__(self, messages, response_model):
        kwargs: dict[str, Any] = dict(
            model=self.model, messages=messages, response_format=response_model,
            temperature=self.temperature,
        )
        if self.seed is not None:
            kwargs["seed"] = self.seed
        completion = self._get_client().chat.completions.parse(**kwargs)
        usage = getattr(completion, "usage", None)
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
        self.usage["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise RuntimeError(f"모델이 응답을 거부했습니다: {message.refusal}")
        if message.parsed is None:
            raise RuntimeError(f"응답을 {response_model.__name__}로 해석하지 못했습니다.")
        return message.parsed


# =============================================================================
# 공통 유틸
# =============================================================================

def _key(text: str) -> str:
    return "".join(text.split()).casefold()


def _element_id(name: str) -> str:
    return "te-" + hashlib.sha1(_key(name).encode("utf-8")).hexdigest()[:10]


def _quote_in(quote: str, text: str) -> bool:
    """줄바꿈·공백 차이만 허용하고 원문에 연속으로 존재하는지 확인한다."""
    quote = _key(quote)
    return bool(quote) and quote in _key(text)


def _messages(system: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


@dataclass
class _PoolItem:
    """비교 대상 기술 1건 (출처 문서 단위)."""

    source: SourceType
    element: TechElement
    doc_id: str | None = None
    title: str | None = None
    provider: str | None = None
    transfer_condition: str | None = None


@dataclass
class _Requirement:
    element: TechElement
    rfp_doc_ids: list[str]
    clear: bool


# =============================================================================
# ① 비교 풀 구성
# =============================================================================

def _company_pool(owned: Sequence[str]) -> list[_PoolItem]:
    """사용자 입력 자체가 근거이므로 입력 문자열을 검증된 근거로 감싼다."""
    return [
        _PoolItem(
            source=SourceType.COMPANY,
            element=TechElement(
                element_id=_element_id(name), name=name, surface_forms=[name],
                origin=SourceType.COMPANY, confidence=1.0,
                evidences=[Evidence(doc_id=COMPANY_DOC_ID, source=SourceType.COMPANY, quote=name, verified=True)],
            ),
            doc_id=COMPANY_DOC_ID, title="사용자 입력 보유기술",
        )
        for name in owned
    ]


def _document_pool(elements: Sequence[TechElement],
                   candidates: Sequence[ExternalTechCandidate]) -> list[_PoolItem]:
    """검증된 근거만 남기고 출처 문서별로 나눠 제공기관·이전조건을 연결한다."""
    by_doc = {candidate.doc_id: candidate for candidate in candidates}
    items = []
    for element in elements:
        groups: dict[str, list[Evidence]] = {}
        for evidence in element.evidences:
            if evidence.verified and evidence.quote.strip():
                groups.setdefault(evidence.doc_id, []).append(evidence)
        for doc_id, evidences in groups.items():
            candidate = by_doc.get(doc_id)
            items.append(_PoolItem(
                source=element.origin,
                element=element.model_copy(update={"evidences": evidences}),
                doc_id=doc_id,
                title=candidate.title if candidate else None,
                provider=candidate.provider if candidate else None,
                transfer_condition=(
                    candidate.transfer_condition
                    if candidate and element.origin in TECHNOLOGY_SOURCES else None
                ),
            ))
    return items


# =============================================================================
# ② RFP 요구기술 추출
# =============================================================================

def _rfp_sections(candidate: ExternalTechCandidate) -> list[dict[str, Any]]:
    rows = []
    for item, fragments in (candidate.extra.get("requirements") or {}).items():
        for fragment in fragments:
            text = str(fragment.get("text") or "").strip()
            if text:
                rows.append({"item": item, "text": text, "kind": fragment.get("source_kind"),
                             "page": fragment.get("page"), "bbox": fragment.get("bbox")})
    return rows


_LEADING_MARKS = re.compile(r"^[\s□■ㅇ◦○▪●•·ㆍ\-\*※]+")


def _spans_of(quote: str, sections: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """quote를 담고 있는 RFP 원문 조각들. PDF 줄바꿈으로 문장이 여러 줄에 갈라져 있어도 찾는다."""
    target = _key(quote)
    if not target:
        return []
    for section in sections:  # 한 줄 안에 있으면 그 줄의 위치를 그대로 쓴다
        if target in _key(section["text"]):
            return [section]
    keys = [_key(section["text"]) for section in sections]
    start = "".join(keys).find(target)
    if start < 0:
        return []
    end, offset, spans = start + len(target), 0, []
    for section, key in zip(sections, keys):
        if key and offset < end and offset + len(key) > start:
            spans.append(section)
        offset += len(key)
    return spans


def _locate(quote: str, sections: Sequence[dict[str, Any]], doc_id: str) -> Evidence:
    """quote가 있는 RFP 원문 위치를 찾는다. RFP 페이지는 1-based, Evidence.page는 0-based.

    여러 줄에 걸친 quote는 모든 조각의 위치를 `extra["locations"]`에 남기고,
    단일 page/bbox는 한 줄일 때만(page는 같은 페이지일 때도) 채워 첫 조각으로 오인되지 않게 한다.
    """
    spans = _spans_of(quote, sections)
    if not spans:  # 불릿 기호만 다른 경우를 허용한다
        stripped = _LEADING_MARKS.sub("", quote)
        if stripped and stripped != quote:
            spans, quote = _spans_of(stripped, sections), stripped
    if not spans:
        return Evidence(doc_id=doc_id, source=SourceType.RFP, quote=quote, verified=False)

    pages = [span.get("page") for span in spans]
    single = len(spans) == 1
    bbox = spans[0].get("bbox") if single else None
    return Evidence(
        doc_id=doc_id, source=SourceType.RFP, section=spans[0]["item"],
        page=pages[0] - 1 if len(set(pages)) == 1 and isinstance(pages[0], int) else None,
        bbox=BBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]) if bbox and len(bbox) == 4 else None,
        quote=quote, verified=True,
        extra={"page": pages[0] if single else None, "source_page_base": 1,
               "locations": [{"page": span.get("page"), "bbox": span.get("bbox"), "item": span["item"]}
                             for span in spans]},
    )


def extract_requirements(candidates: Sequence[ExternalTechCandidate], llm: StructuredLLM,
                         warnings: list[str], *, max_section_chars: int = 6000,
                         excluded: list[dict[str, str]] | None = None) -> list[_Requirement]:
    """RFP 후보별 요구항목 원문에서 기술요소를 추출하고 같은 기술은 하나로 병합한다.

    기술이 아니라고 표시된 항목(합의·인증·상용화 등)은 제외하고 `excluded`에 남긴다.
    """
    merged: dict[str, _Requirement] = {}
    alias: dict[str, str] = {}
    for candidate in candidates:
        sections = _rfp_sections(candidate)
        if not sections:
            warnings.append(f"rfp {candidate.doc_id}: 요구항목 원문이 없어 요구기술을 추출하지 않았습니다.")
            continue
        payload_sections, used = [], 0
        for section in sections:
            if used + len(section["text"]) > max_section_chars:
                warnings.append(f"rfp {candidate.doc_id}: 요구항목 원문이 길어 일부만 추출에 사용했습니다.")
                break
            used += len(section["text"])
            payload_sections.append({"item": section["item"], "text": section["text"]})
        answer = llm(_messages(EXTRACTION_PROMPT, {
            "rfp_title": candidate.title, "sections": payload_sections,
        }), RequirementExtraction)

        for found in answer.requirements:
            name = found.name.strip()
            if not name:
                continue
            if not found.is_technology:
                if excluded is not None:
                    excluded.append({"rfp": candidate.doc_id, "text": name, "reason": "LLM이 기술 요구가 아니라고 판단"})
                continue
            evidence = _locate(found.quote, sections, candidate.doc_id)
            if not evidence.verified:
                warnings.append(f"rfp {candidate.doc_id}: '{name}'의 근거 문장을 원문에서 확인하지 못했습니다.")
            synonyms = [s.strip() for s in found.synonyms if s.strip()]
            keys = [_key(name)] + [_key(s) for s in synonyms]
            target = next((alias[k] for k in keys if k in alias), None)
            if target is None:
                target = keys[0]
                merged[target] = _Requirement(
                    element=TechElement(
                        element_id=_element_id(name), name=name, surface_forms=[name],
                        synonyms=synonyms, broader=list(found.broader), narrower=list(found.narrower),
                        function=found.function, target=found.target,
                        origin=SourceType.RFP, evidences=[evidence],
                    ),
                    rfp_doc_ids=[candidate.doc_id], clear=found.clear and evidence.verified,
                )
            else:
                requirement = merged[target]
                element = requirement.element
                if name not in element.surface_forms:
                    element.surface_forms.append(name)
                element.synonyms.extend(s for s in synonyms if s not in element.synonyms)
                if all((ev.doc_id, ev.quote) != (evidence.doc_id, evidence.quote) for ev in element.evidences):
                    element.evidences.append(evidence)
                if candidate.doc_id not in requirement.rfp_doc_ids:
                    requirement.rfp_doc_ids.append(candidate.doc_id)
                requirement.clear = requirement.clear or (found.clear and evidence.verified)
            for k in keys:
                alias.setdefault(k, target)
    return list(merged.values())


# =============================================================================
# ③ 정렬: 후보 좁히기 + LLM 충족도 판단
# =============================================================================

def _terms(element: TechElement) -> list[str]:
    return list(dict.fromkeys([element.name, *element.synonyms, *element.surface_forms]))


def _bigrams(texts: Sequence[str]) -> set[str]:
    grams = set()
    for text in texts:
        text = _key(text)
        if len(text) > 1:
            grams.update(text[i:i + 2] for i in range(len(text) - 1))
        elif text:
            grams.add(text)
    return grams


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def _shortlist(requirement: TechElement, pool: Sequence[_PoolItem],
               embed: EmbedFn | None, max_candidates: int) -> list[_PoolItem]:
    """출처별 상위 후보만 LLM에 전달한다. 유사도는 후보 선별에만 쓰고 판정에는 쓰지 않는다."""
    if not pool:
        return []
    if embed is not None:
        texts = [" / ".join(_terms(requirement))] + [" / ".join(_terms(item.element)) for item in pool]
        vectors = list(embed(texts))
        scores = [_cosine(vectors[0], vector) for vector in vectors[1:]]
    else:
        query = _bigrams(_terms(requirement))
        scores = []
        for item in pool:
            grams = _bigrams(_terms(item.element))
            scores.append(len(query & grams) / len(query | grams) if query | grams else 0.0)
    selected = []
    for source in dict.fromkeys(item.source for item in pool):
        ranked = sorted(
            (i for i, item in enumerate(pool) if item.source == source), key=lambda i: -scores[i],
        )
        selected.extend(pool[i] for i in ranked[:max_candidates])
    return selected


def _align(requirement: _Requirement, pool: Sequence[_PoolItem], llm: StructuredLLM,
           embed: EmbedFn | None, max_candidates: int) -> list[SourceMatch]:
    shortlisted = _shortlist(requirement.element, pool, embed, max_candidates)
    if not shortlisted:
        return []
    element = requirement.element
    answer = llm(_messages(ALIGNMENT_PROMPT, {
        "requirement": {
            "name": element.name, "synonyms": element.synonyms, "function": element.function,
            "target": element.target, "rfp_quotes": [ev.quote for ev in element.evidences if ev.verified],
        },
        "candidates": [
            {"index": i, "source": item.source.value, "name": item.element.name,
             "function": item.element.function, "target": item.element.target,
             "evidence": [ev.quote for ev in item.element.evidences]}
            for i, item in enumerate(shortlisted)
        ],
    }), AlignmentJudgements)

    matches, seen = [], set()
    for judgement in answer.judgements:
        index = judgement.candidate_index
        if judgement.coverage == "none" or not 0 <= index < len(shortlisted) or index in seen:
            continue
        seen.add(index)
        item = shortlisted[index]
        evidences = [ev for ev in item.element.evidences if _quote_in(judgement.quote, ev.quote)]
        matches.append(SourceMatch(
            source=item.source, element_name=item.element.name, coverage=judgement.coverage,
            reason=judgement.reason, verified=bool(evidences), doc_id=item.doc_id, title=item.title,
            provider=item.provider, transfer_condition=item.transfer_condition, evidences=evidences,
        ))
    return sorted(matches, key=lambda m: (m.coverage != "full", not m.verified))


# =============================================================================
# ④ 판정 (PROJECT_PLAN 판정 우선순위)
# =============================================================================

def decide_label(*, requirement_verified: bool, requirement_clear: bool,
                 company: Sequence[SourceMatch], external: Sequence[SourceMatch]) -> tuple[GapLabel, str]:
    """검증된 매칭만 사용해 라벨을 결정한다. NTIS 매칭은 입력으로 받지 않는다."""
    if not requirement_verified:
        return GapLabel.INSUFFICIENT, "RFP 요구기술의 원문 근거를 검증하지 못함"

    def has(matches, coverage):
        return any(m.verified and m.coverage == coverage for m in matches)

    if has(company, "full"):
        return GapLabel.OWNED, "기업 보유기술이 요구기술을 충족"
    if has(company, "partial"):
        return GapLabel.PARTIAL, "기업 보유기술이 요구기술을 일부 충족"
    if has(external, "full"):
        return GapLabel.EXTERNAL, "기업 근거 없음, 기술나눔 기술이 요구기술을 보완"
    if has(external, "partial"):
        return GapLabel.PARTIAL, "기업 근거 없음, 기술나눔 기술이 요구기술을 일부 보완"
    if requirement_clear:
        return GapLabel.RND_NEEDED, "RFP가 명확히 요구하나 기업·외부기술 충족 근거 없음"
    return GapLabel.INSUFFICIENT, "RFP 요구가 명확하지 않아 충족 여부 판단 불가"


def _policy_checks(label: GapLabel, external: Sequence[SourceMatch]) -> list[str]:
    checks = []
    if label in {GapLabel.EXTERNAL, GapLabel.PARTIAL}:
        for match in external:
            if match.verified:
                checks.append(
                    f"기술나눔 기술 이전·사용 조건 확인: {match.title or match.doc_id} "
                    f"(이전조건: {match.transfer_condition or '미상'})"
                )
    if label == GapLabel.RND_NEEDED:
        checks.append("국가 R&D 과제 참여·수행 조건 확인")
    return list(dict.fromkeys(checks))


# =============================================================================
# 진입점
# =============================================================================

def run_gap_analysis(state: AnalysisState, *, llm: StructuredLLM | None = None,
                     embed: EmbedFn | None = None, max_candidates: int = 8,
                     max_section_chars: int = 6000) -> GapReport:
    """AnalysisState를 RFP 요구기술 축으로 정렬해 Gap 판정 결과를 반환한다."""
    if max_candidates < 1:
        raise ValueError("max_candidates는 1 이상이어야 합니다.")
    if not state.rfp.candidates:
        return empty_report(state, method="llm")
    llm = llm or OpenAIStructuredLLM()
    warnings: list[str] = []
    excluded: list[dict[str, str]] = []
    started = time.perf_counter()
    requirements = extract_requirements(
        state.rfp.candidates, llm, warnings, max_section_chars=max_section_chars, excluded=excluded,
    )
    report = build_report(
        state, requirements, lambda req, pool: _align(req, pool, llm, embed, max_candidates),
        warnings, method="llm",
    )
    report.stats = {"seconds": round(time.perf_counter() - started, 2), "model": getattr(llm, "model", None),
                    **(getattr(llm, "usage", None) or {}), "excluded_requirements": excluded}
    return report


def empty_report(state: AnalysisState, *, method: str) -> GapReport:
    """RFP 후보가 없으면 판정하지 않는다. 검색 실패는 기술 미보유·추가 R&D 필요를 뜻하지 않는다."""
    return GapReport(
        problem=state.request.problem, method=method,
        summary={label.value: 0 for label in GapLabel},
        owned_not_required=list(state.request.owned_technologies),
        warnings=["rfp: 후보가 없어 Gap 판정을 수행하지 않았습니다. 기술 미보유나 추가 R&D 필요를 의미하지 않습니다."],
    )


def build_pool(state: AnalysisState) -> list[_PoolItem]:
    return (
        _company_pool(state.request.owned_technologies)
        + _document_pool(state.external_elements, state.technology.candidates)
        + _document_pool(state.ntis_elements, state.ntis.candidates)
    )


def build_report(state: AnalysisState, requirements: Sequence[_Requirement],
                 align: Callable[[_Requirement, Sequence[_PoolItem]], list[SourceMatch]],
                 warnings: list[str], *, method: str) -> GapReport:
    """요구기술별 매칭 → 라벨 결정 → 리포트 조립. llm·local 모드가 공유해 판정 규칙을 동일하게 유지한다."""
    owned = list(state.request.owned_technologies)
    report = GapReport(problem=state.request.problem, method=method,
                       summary={label.value: 0 for label in GapLabel})
    pool = build_pool(state)
    if not state.external_elements:
        warnings.append("technology: 검증된 외부기술 요소가 없어 외부기술보완 판정 후보가 없습니다.")

    for requirement in requirements:
        verified = any(ev.verified for ev in requirement.element.evidences)
        matches = align(requirement, pool) if verified else []
        company = [m for m in matches if m.source == SourceType.COMPANY]
        external = [m for m in matches if m.source in TECHNOLOGY_SOURCES]
        ntis = [m for m in matches if m.source == SourceType.NTIS]
        label, path = decide_label(
            requirement_verified=verified, requirement_clear=requirement.clear,
            company=company, external=external,
        )
        report.items.append(GapItem(
            requirement=requirement.element, rfp_doc_ids=requirement.rfp_doc_ids,
            requirement_clear=requirement.clear, label=label, decision_path=path,
            company=company, external=external, ntis_references=ntis,
            policy_check=_policy_checks(label, external),
        ))
        report.summary[label.value] += 1

    matched = {m.element_name for item in report.items for m in item.company if m.verified}
    report.owned_not_required = [name for name in owned if name not in matched]
    report.warnings = warnings
    return report
