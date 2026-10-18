"""Technology alignment and Gap decision over an orchestrated AnalysisState.

RFP 요구기술을 기술요소 축으로 삼아 기업 보유기술, 기술나눔 외부기술, NTIS 선행과제를
비교하고 PROJECT_PLAN의 판정 우선순위로 GapLabel을 결정한다.

- LLM은 RFP 요구기술 추출과 후보별 충족도(full/partial/none) 판단에만 사용한다.
  라벨은 `decide_label`의 결정론적 규칙으로 정한다.
- LLM이 제시한 quote는 원문과 대조해 검증된 경우에만 판정에 사용한다.
- 요구기술과 분야 고유 표현이 하나도 겹치지 않는 매칭(진단·감시 같은 일반 용어만 비슷한 경우)은
  LLM이 full/partial을 줘도 verified로 보지 않는다. 추가 LLM 호출 없이 코드로 검사한다.
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
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from app.common.paths import PROJECT_ROOT
from app.common.schemas import (
    BBox, Evidence, ExternalTechCandidate, GapLabel, ModuleResult, SourceType, TechElement,
)

if TYPE_CHECKING:
    from app.orchestrator import AnalysisState

COMPANY_DOC_ID = "company-input"
TECHNOLOGY_SOURCES = {SourceType.PUBLIC_TECH, SourceType.POSCO_TECH}
Coverage = Literal["full", "partial", "none"]
# llm(messages, response_model) -> response_model 인스턴스. 테스트에서는 가짜 함수를 주입한다.
StructuredLLM = Callable[[list[dict[str, str]], type[BaseModel]], BaseModel]
# embed(texts) -> 텍스트별 벡터. 예: lambda texts: embedder.encode(texts)[0]
EmbedFn = Callable[[Sequence[str]], Sequence[Sequence[float]]]

#: 분석할 RFP 수. RFP 검색 순위 상위만 분석해 질의와 무관한 공고의 요구가 추가R&D로 쌓이는 것을 막는다.
DEFAULT_MAX_RFPS = 2
#: 기술나눔 후보 1건당 비교에 쓰는 근거 조각 수(섹션 단위)와 조각 길이 (LLM 입력 토큰 상한)
HITS_PER_CANDIDATE = 2
HIT_QUOTE_CHARS = 300
#: 충족도 판단 LLM 1회에 묶어 보내는 요구기술 수
DEFAULT_ALIGN_BATCH = 10
#: 요구기술 1건에 참고로 붙이는 NTIS 과제 수 (LLM 없이 코드로 선별, 판정에는 쓰지 않는다)
NTIS_REFERENCES = 3
#: 기술 능력을 판단하는 근거로 쓰지 않는 섹션 제목의 일부 (적용 산업, 시장 전망은 기술 충족 근거가 아님)
SKIP_SECTION_WORDS = ("적용 산업", "시장성")

#: 기술 요구가 아닌 항목(합의·인증·상용화·산출물 제출·계획서 작성 지침). 해당 단어가 있으면 제외한다.
NON_TECHNOLOGY = re.compile(
    "합의|협의|협약|계약|인허가|인증|상용화|사업화|수용성|보험|주관사|확약서|제출|계획서|"
    "인력양성|사업비|예산|가점|특허|논문"
)
#: LLM이 뽑은 요구기술 '이름'에 적용하는 규칙. 이름은 짧아서 '시제품'도 비기술로 본다.
NON_TECHNOLOGY_NAME = re.compile(NON_TECHNOLOGY.pattern + "|시제품")


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


class BatchJudgement(BaseModel):
    # 필드 순서가 생성 순서다: 어떤 요구기술·후보인지 먼저 정하고, 이유를 쓴 뒤 coverage를 정한다.
    requirement_index: int
    candidate_index: int
    reason: str
    coverage: Coverage
    quote: str


class BatchJudgements(BaseModel):
    judgements: list[BatchJudgement]


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
- 관련 없는 후보(none)는 judgements에 넣지 마세요. 둘 다 AI·센서·설비 진단처럼 분야나 주제만 비슷한 것은 partial이 아니라 관련 없음입니다.
- reason을 '직접적인 관련성이 부족하다', '명시되어 있지 않다'처럼 쓰게 된다면 그 후보는 judgements에서 빼야 합니다.
- 판단 근거는 각 후보의 evidence 문장만 사용하세요. 후보 이름이나 추측으로 판단하지 마세요.
- quote에는 판단의 근거가 된 후보 evidence 문장을 그대로 복사하세요.
- full 또는 partial인 후보만 candidate_index와 함께 반환하세요. 해당하는 후보가 없으면 빈 목록을 반환하세요."""

ALIGNMENT_BATCH_PROMPT = """당신은 RFP 요구기술 여러 개를 비교 후보 기술들이 각각 얼마나 충족하는지 판정합니다.
requirements의 각 항목은 서로 독립입니다. 한 요구기술을 판단할 때 다른 요구기술의 내용이나 판단을 근거로 쓰지 마세요.
- 명칭이 달라도 기능·적용대상·상하위 관계를 함께 고려해 같은 기술인지 판단하세요.
- 먼저 reason에 '요구기술이 구체적으로 요구하는 기능'과 '후보 evidence가 명시적으로 서술한 기능'을 비교해 쓰고, 그 결론에 맞게 coverage를 정하세요.
- full: 후보 evidence가 요구기술의 핵심 기능을 직접 서술함.
- partial: 후보 evidence가 요구기술의 구체적인 기능·구성요소 일부를 명시적으로 서술하지만 성능·적용대상·범위가 부족함.
- 관련 없는 후보(none)는 judgements에 넣지 마세요. 둘 다 AI·센서·설비 진단처럼 분야나 주제만 비슷한 것은 partial이 아니라 관련 없음입니다.
- reason을 '직접적인 관련성이 부족하다', '명시되어 있지 않다'처럼 쓰게 된다면 그 후보는 judgements에서 빼야 합니다.
- 판단 근거는 각 후보의 evidence 문장만 사용하세요. 후보 이름이나 추측으로 판단하지 마세요.
- quote에는 판단의 근거가 된 후보 evidence 문장을 그대로 복사하세요.
- full 또는 partial인 (요구기술, 후보) 쌍만 requirement_index와 candidate_index를 함께 반환하세요. 해당하는 쌍이 없으면 빈 목록을 반환하세요."""


class OpenAIStructuredLLM:
    """OpenAI Structured Outputs 호출. 클라이언트는 첫 호출 시 생성한다.

    `cache_dir`를 주면 같은 모델·설정·메시지·응답 형식의 결과를 파일로 재사용한다.
    프롬프트나 입력이 바뀌면 키가 달라져 다시 호출한다. 여러 스레드에서 동시에 호출할 수 있다.
    """

    def __init__(self, model: str = "gpt-4o-mini", *, temperature: float = 0.0,
                 seed: int | None = 0, client: Any = None, cache_dir: str | Path | None = None):
        self.model = model
        self.temperature = temperature
        self.seed = seed
        self._client = client
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cache_hits": 0}
        self._lock = threading.Lock()

    def _cache_path(self, messages, response_model) -> Path | None:
        if self.cache_dir is None:
            return None
        payload = json.dumps({
            "model": self.model, "temperature": self.temperature, "seed": self.seed,
            "messages": messages, "schema": response_model.model_json_schema(),
        }, ensure_ascii=False, sort_keys=True)
        return self.cache_dir / f"{hashlib.sha256(payload.encode('utf-8')).hexdigest()}.json"

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
        cache = self._cache_path(messages, response_model)
        if cache is not None and cache.exists():
            with self._lock:
                self.usage["cache_hits"] += 1
            return response_model.model_validate_json(cache.read_text(encoding="utf-8"))

        kwargs: dict[str, Any] = dict(
            model=self.model, messages=messages, response_format=response_model,
            temperature=self.temperature,
        )
        if self.seed is not None:
            kwargs["seed"] = self.seed
        with self._lock:  # 클라이언트 생성은 한 번만
            client = self._get_client()
        completion = client.chat.completions.parse(**kwargs)
        usage = getattr(completion, "usage", None)
        with self._lock:
            self.usage["calls"] += 1
            self.usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            self.usage["completion_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise RuntimeError(f"모델이 응답을 거부했습니다: {message.refusal}")
        if message.parsed is None:
            raise RuntimeError(f"응답을 {response_model.__name__}로 해석하지 못했습니다.")
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(message.parsed.model_dump_json(), encoding="utf-8")
        return message.parsed


def _parallel_map(function: Callable, items: Sequence, workers: int) -> list:
    """순서를 유지하며 병렬 실행한다. workers가 1이면 순차 실행한다."""
    if workers <= 1 or len(items) <= 1:
        return [function(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(function, items))


# =============================================================================
# 공통 유틸
# =============================================================================

def _key(text: str) -> str:
    return "".join(text.split()).casefold()


def _element_id(name: str) -> str:
    return "te-" + hashlib.sha1(_key(name).encode("utf-8")).hexdigest()[:10]


_LEADING_MARKS = re.compile(r"^[\s□■ㅇ◦○▪●•∙·ㆍ\-\*※]+")
_TRAILING_MARKS = re.compile(r"[\s.,;:·ㆍ…。]+$")


def _trim_quote(quote: str) -> str:
    """LLM이 인용문 앞뒤에 붙이는 글머리 기호·마침표 같은 서식만 걷어낸다 (본문 글자는 건드리지 않는다)."""
    return _TRAILING_MARKS.sub("", _LEADING_MARKS.sub("", quote))


def _quote_in(quote: str, text: str) -> bool:
    """줄바꿈·공백·앞뒤 서식 기호 차이만 허용하고 원문에 연속으로 존재하는지 확인한다."""
    quote = _key(_trim_quote(quote))
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


def _hit_bodies(text: str) -> list[str]:
    """검색 청크를 섹션별 본문으로 나눈다.

    첫 줄(기술명)과 '[기술 개요]' 같은 섹션 제목 줄은 버리고, 한 섹션 안의 줄만 이어 붙인다.
    섹션 제목을 건너뛰어 앞뒤 섹션을 한 문장으로 잇지 않으므로, 각 본문은 원문 청크의
    연속된 부분이다(공백 차이만 있음). 적용 산업·시장성 섹션은 제외한다.
    """
    bodies: list[str] = []
    title, lines = "", []

    def flush():
        body = " ".join(lines).strip()
        if body and not any(word in title for word in SKIP_SECTION_WORDS):
            bodies.append(body[:HIT_QUOTE_CHARS].strip())
        lines.clear()

    for raw in text.splitlines()[1:]:
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            flush()
            title = line
        elif line:
            lines.append(line)
    flush()
    return bodies


def _candidate_pool(module: ModuleResult, covered: set[str]) -> list[_PoolItem]:
    """기술요소로 추출되지 않은 기술나눔 후보도 검색 본문으로 비교 대상에 넣는다.

    Technology RAG는 상위 일부 문서에서만 기술요소를 뽑으므로, 나머지 후보는 검색 청크 본문
    (원문 텍스트)을 근거로 쓴다. 이미 기술요소로 들어간 문서(`covered`)는 중복하지 않는다.
    """
    hits_by_doc: dict[str, list] = {}
    for hit in sorted(module.hits, key=lambda h: h.final_rank if h.final_rank is not None else 10**6):
        hits_by_doc.setdefault(hit.doc_id, []).append(hit)
    items = []
    for candidate in module.candidates:
        if candidate.doc_id in covered:
            continue
        hits = hits_by_doc.get(candidate.doc_id, [])
        if not hits:
            continue
        evidences = []
        for hit in hits:
            for body in _hit_bodies(hit.text):
                if len(evidences) < HITS_PER_CANDIDATE:
                    evidences.append(Evidence(
                        doc_id=candidate.doc_id, source=hit.source, section=hit.section_key, quote=body,
                        verified=True, extra={"from": "retrieval_hit", "chunk_id": hit.chunk_id},
                    ))
        if not evidences:
            continue
        name = hits[0].text.splitlines()[0].strip() or candidate.title  # '기술명 (부제)'
        items.append(_PoolItem(
            source=hits[0].source,
            element=TechElement(element_id=_element_id(name), name=name, surface_forms=[candidate.title],
                                origin=hits[0].source, evidences=evidences),
            doc_id=candidate.doc_id, title=candidate.title, provider=candidate.provider,
            transfer_condition=candidate.transfer_condition,
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


def _spans_of(quote: str, sections: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """quote를 담고 있는 동일 RFP 단위의 연속 원문 조각들.

    PDF 줄바꿈으로 갈라진 문장은 같은 항목·페이지 안에서만 이어 붙인다.
    서로 다른 항목이나 페이지의 텍스트를 합쳐 원문 인용을 만들지 않는다.
    """
    target = _key(quote)
    if not target:
        return []
    for section in sections:  # 한 줄 안에 있으면 그 줄의 위치를 그대로 쓴다
        if target in _key(section["text"]):
            return [section]
    for start, first in enumerate(sections):
        first_key = _key(first["text"])
        combined, spans = "", []
        for section in sections[start:]:
            if any(section.get(field) != first.get(field) for field in ("item", "page")):
                break
            spans.append(section)
            combined += _key(section["text"])
            position = combined.find(target)
            if 0 <= position < len(first_key):
                return spans
            if len(combined) >= len(first_key) + len(target):
                break
    return []


def _locate(quote: str, sections: Sequence[dict[str, Any]], doc_id: str) -> Evidence:
    """quote가 있는 RFP 원문 위치를 찾는다. RFP 페이지는 1-based, Evidence.page는 0-based.

    여러 줄에 걸친 quote는 모든 조각의 위치를 `extra["locations"]`에 남기고,
    단일 page/bbox는 한 줄일 때만(page는 같은 페이지일 때도) 채워 첫 조각으로 오인되지 않게 한다.
    """
    trimmed = _trim_quote(quote)
    spans = _spans_of(trimmed, sections)
    if not spans:
        return Evidence(doc_id=doc_id, source=SourceType.RFP, quote=quote, verified=False)
    quote = trimmed

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
                         excluded: list[dict[str, str]] | None = None,
                         workers: int = 1) -> list[_Requirement]:
    """RFP 후보별 요구항목 원문에서 기술요소를 추출하고 같은 기술은 하나로 병합한다.

    기술이 아니라고 표시됐거나 이름에 비기술 단어(합의·인증·상용화·시제품 등)가 있는 항목은
    제외하고 `excluded`에 남긴다. LLM 호출은 RFP별로 병렬 실행하고 결과는 RFP 순서대로 병합한다.
    """
    jobs = []
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
        jobs.append((candidate, sections, _messages(EXTRACTION_PROMPT, {
            "rfp_title": candidate.title, "sections": payload_sections,
        })))
    answers = _parallel_map(lambda job: llm(job[2], RequirementExtraction), jobs, workers)

    def exclude(candidate, name, reason):
        if excluded is not None:
            excluded.append({"rfp": candidate.doc_id, "text": name, "reason": reason})

    merged: dict[str, _Requirement] = {}
    alias: dict[str, str] = {}
    for (candidate, sections, _), answer in zip(jobs, answers):
        for found in answer.requirements:
            name = found.name.strip()
            if not name:
                continue
            if not found.is_technology:
                exclude(candidate, name, "LLM이 기술 요구가 아니라고 판단")
                continue
            word = NON_TECHNOLOGY_NAME.search(name)
            if word:  # LLM이 지시를 따르지 않는 경우를 규칙으로 보완한다
                exclude(candidate, name, f"비기술 항목 단어: {word.group()}")
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


#: 매칭의 근거가 이 일반 공정 용어뿐이고 분야 고유 표현이 겹치지 않으면, LLM이 full/partial을
#: 줘도 verified로 보지 않는다. "진단·감시" 같은 말은 거의 모든 설비 기술 설명에 등장해서,
#: 이 단어만으로 "실시간 진단을 한다"는 요구기술과 전혀 다른 분야의 후보(예: 케이블 요구에
#: 철도 전기설비 기술)가 매칭되는 문제를 코드로 걸러낸다. 추가 LLM 호출 없이 기존 응답만 검사한다.
GENERIC_MATCH_WORDS = (
    "기술", "시스템", "장치", "설비", "플랫폼", "솔루션", "체계", "구조",
    "진단", "감시", "모니터링", "관리", "평가", "측정", "시험", "검사", "분석",
    "제어", "운영", "자동", "실시간", "최적화", "통합", "구축", "개발", "확보",
    "적용", "활용", "구현", "제공", "지원", "성능", "데이터", "설계", "제작",
)
_GENERIC_STRIP = re.compile("|".join(re.escape(word) for word in GENERIC_MATCH_WORDS))


def _domain_bigrams(texts: Sequence[str | None]) -> set[str]:
    """일반 공정 용어를 지우고 남는 분야 고유 표현만으로 글자 쌍을 만든다."""
    return _bigrams([_GENERIC_STRIP.sub("", text) for text in texts if text])


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
    def group(item: _PoolItem) -> str:  # 공공·포스코 기술나눔은 한 묶음으로 센다
        return "technology" if item.source in TECHNOLOGY_SOURCES else item.source.value

    selected = []
    for key in dict.fromkeys(group(item) for item in pool):
        ranked = sorted(
            (i for i, item in enumerate(pool) if group(item) == key), key=lambda i: -scores[i],
        )
        selected.extend(pool[i] for i in ranked[:max_candidates])
    return selected


def _domain_terms(element: TechElement) -> set[str]:
    """요구기술 자신의 분야 용어. 일반 공정 용어뿐이면 비어 있어서 겹침 검사를 건너뛴다."""
    return _domain_bigrams([element.name, element.function, element.target, *element.synonyms,
                            *(ev.quote for ev in element.evidences if ev.verified)])


def _external_domain_match(requirement: TechElement, candidate: TechElement,
                           evidences: Sequence[Evidence]) -> bool:
    """Reject external matches supported only by a generic or incidental phrase."""
    required = _domain_bigrams([requirement.name, requirement.function, requirement.target,
                                *requirement.synonyms])
    offered = _domain_bigrams([candidate.name, candidate.function, candidate.target,
                               *candidate.synonyms, *(ev.quote for ev in evidences)])
    overlap = required & offered
    # shortcut: character overlap is a conservative free guard, upgrade when semantic fixtures justify a richer matcher.
    return bool(required) and len(overlap) >= 2 and len(overlap) / len(required) >= 0.25


def _to_matches(requirement: _Requirement, candidates: Sequence[_PoolItem],
                judgements: Sequence[Any]) -> list[SourceMatch]:
    """LLM 판단(candidate_index, coverage, quote, reason)을 원문 대조로 검증해 SourceMatch로 만든다."""
    domain_terms = _domain_terms(requirement.element)
    matches, seen = [], set()
    for judgement in judgements:
        index = judgement.candidate_index
        if judgement.coverage == "none" or not 0 <= index < len(candidates) or index in seen:
            continue
        seen.add(index)
        item = candidates[index]
        evidences = [ev for ev in item.element.evidences if _quote_in(judgement.quote, ev.quote)]
        verified = bool(evidences)
        if verified and item.source in TECHNOLOGY_SOURCES:
            verified = _external_domain_match(requirement.element, item.element, evidences)
        elif verified and domain_terms:
            # 분야 고유 표현이 하나도 겹치지 않으면 "진단·감시" 같은 말만 비슷한 것으로 보고 판정에서 뺀다.
            verified = bool(domain_terms & _domain_bigrams(
                [item.element.name, item.element.function, item.element.target, *(ev.quote for ev in evidences)]))
        matches.append(SourceMatch(
            source=item.source, element_name=item.element.name, coverage=judgement.coverage,
            reason=judgement.reason, verified=verified, doc_id=item.doc_id, title=item.title,
            provider=item.provider, transfer_condition=item.transfer_condition, evidences=evidences,
        ))
    return sorted(matches, key=lambda m: (m.coverage != "full", not m.verified))


def _align_chunk(requirements: Sequence[_Requirement], shortlists: Sequence[Sequence[_PoolItem]],
                 llm: StructuredLLM) -> list[list[SourceMatch]]:
    """요구기술 여러 개를 LLM 1회로 판단한다. 후보는 묶음 안 요구기술들의 후보 합집합이다."""
    union: list[_PoolItem] = []
    position: dict[int, int] = {}
    for shortlist in shortlists:
        for item in shortlist:
            if id(item) not in position:
                position[id(item)] = len(union)
                union.append(item)
    if not union:
        return [[] for _ in requirements]
    try:
        answer = llm(_messages(ALIGNMENT_BATCH_PROMPT, {
            "requirements": [
                {"index": i, "name": r.element.name, "synonyms": r.element.synonyms,
                 "function": r.element.function, "target": r.element.target,
                 "rfp_quotes": [ev.quote for ev in r.element.evidences if ev.verified]}
                for i, r in enumerate(requirements)
            ],
            "candidates": [
                {"index": i, "source": item.source.value, "name": item.element.name,
                 "function": item.element.function, "target": item.element.target,
                 "evidence": [ev.quote for ev in item.element.evidences]}
                for i, item in enumerate(union)
            ],
        }), BatchJudgements)
    except (ValueError, RuntimeError):
        if len(requirements) == 1:
            raise
        # 응답 형식 오류 등은 묶음을 반으로 나눠 다시 시도한다 (한 건씩 남으면 그대로 실패시킨다).
        mid = len(requirements) // 2
        return (_align_chunk(requirements[:mid], shortlists[:mid], llm)
                + _align_chunk(requirements[mid:], shortlists[mid:], llm))
    by_requirement: list[list[BatchJudgement]] = [[] for _ in requirements]
    for judgement in answer.judgements:
        if 0 <= judgement.requirement_index < len(requirements):
            by_requirement[judgement.requirement_index].append(judgement)
    return [_to_matches(requirement, union, judgements)
            for requirement, judgements in zip(requirements, by_requirement)]


def _align_many(requirements: Sequence[_Requirement], pool: Sequence[_PoolItem], llm: StructuredLLM,
                embed: EmbedFn | None, max_candidates: int, batch_size: int,
                workers: int) -> list[list[SourceMatch]]:
    """요구기술을 batch_size개씩 묶어 판단한다. 결과 순서는 입력 순서를 유지한다."""
    shortlists = [_shortlist(r.element, pool, embed, max_candidates) for r in requirements]
    chunks = [(requirements[i:i + batch_size], shortlists[i:i + batch_size])
              for i in range(0, len(requirements), batch_size)]
    results = _parallel_map(lambda chunk: _align_chunk(chunk[0], chunk[1], llm), chunks, workers)
    return [matches for chunk_result in results for matches in chunk_result]


def _ntis_references(requirement: _Requirement, ntis_pool: Sequence[_PoolItem],
                     embed: EmbedFn | None, limit: int) -> list[SourceMatch]:
    """NTIS 과제를 LLM 없이 참고 근거로 붙인다. 충족도는 판단하지 않으며(coverage=none) 판정에도 쓰지 않는다."""
    domain_terms = _domain_terms(requirement.element)
    if not domain_terms:
        return []
    references = []
    for item in _shortlist(requirement.element, ntis_pool, embed, limit):
        evidences = [ev for ev in item.element.evidences if ev.verified and ev.quote.strip()]
        if not evidences or not (domain_terms & _domain_bigrams(
                [item.element.name, item.element.function, item.element.target, *(ev.quote for ev in evidences)])):
            continue
        references.append(SourceMatch(
            source=item.source, element_name=item.element.name, coverage="none",
            reason="유사·선행 과제 참고 (충족도 미판단)", verified=True, doc_id=item.doc_id,
            title=item.title, evidences=evidences,
        ))
    return references


# =============================================================================
# ④ 판정 (PROJECT_PLAN 판정 우선순위)
# =============================================================================

def decide_label(*, requirement_verified: bool, requirement_clear: bool,
                 company: Sequence[SourceMatch], external: Sequence[SourceMatch],
                 external_available: bool = True) -> tuple[GapLabel, str]:
    """검증된 매칭만 사용해 라벨을 결정한다. NTIS 매칭은 입력으로 받지 않는다.

    external_available: 비교할 기술나눔 후보가 있었는지. 후보가 아예 없으면 검색이 비었다는 사실만으로
    추가 R&D를 권하지 않고 근거부족으로 둔다.
    """
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
    if not external_available:
        return GapLabel.INSUFFICIENT, "기술나눔 후보가 없고 보유기술 근거도 없어 충족 여부 판단 불가"
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
                     max_section_chars: int = 6000, max_rfps: int | None = DEFAULT_MAX_RFPS,
                     workers: int = 4, batch_size: int = DEFAULT_ALIGN_BATCH) -> GapReport:
    """AnalysisState를 RFP 요구기술 축으로 정렬해 Gap 판정 결과를 반환한다.

    max_rfps: RFP 검색 순위 상위 몇 개만 분석할지 (None이면 전부)
    workers: LLM 동시 호출 수 (1이면 순차)
    batch_size: 충족도 판단 LLM 1회에 묶는 요구기술 수. NTIS는 판단에 쓰지 않고 참고 근거로만 붙인다.
    """
    if max_candidates < 1:
        raise ValueError("max_candidates는 1 이상이어야 합니다.")
    if batch_size < 1:
        raise ValueError("batch_size는 1 이상이어야 합니다.")
    if not state.rfp.candidates:
        return empty_report(state, method="llm")
    llm = llm or OpenAIStructuredLLM()
    warnings: list[str] = []
    excluded: list[dict[str, str]] = []
    started = time.perf_counter()
    rfps, skipped = select_rfps(state, max_rfps)
    requirements = extract_requirements(
        rfps, llm, warnings, max_section_chars=max_section_chars, excluded=excluded, workers=workers,
    )
    ntis_pool = _document_pool(state.ntis_elements, state.ntis.candidates)
    report = build_report(
        state, requirements, None, warnings, method="llm", workers=workers,
        align_many=lambda reqs, pool: _align_many(reqs, pool, llm, embed, max_candidates, batch_size, workers),
        ntis_reference=lambda req: _ntis_references(req, ntis_pool, embed, NTIS_REFERENCES),
    )
    report.stats = {"seconds": round(time.perf_counter() - started, 2), "model": getattr(llm, "model", None),
                    **(getattr(llm, "usage", None) or {}), "excluded_requirements": excluded,
                    "rfps_analyzed": [c.doc_id for c in rfps], "rfps_skipped": skipped,
                    "pool_size": {**report.stats["pool_size"], "ntis": len(ntis_pool)}, "batch_size": batch_size}
    return report


def select_rfps(state: AnalysisState, max_rfps: int | None) -> tuple[list[ExternalTechCandidate], list[str]]:
    """RFP 검색 순위 상위 max_rfps개만 분석한다. 나머지는 ID만 남긴다 (최종 답변에서 후보로는 보여줄 수 있다)."""
    if max_rfps is not None and max_rfps < 1:
        raise ValueError("max_rfps는 1 이상이거나 None이어야 합니다.")
    candidates = list(state.rfp.candidates)
    if max_rfps is None:
        return candidates, []
    return candidates[:max_rfps], [c.doc_id for c in candidates[max_rfps:]]


def empty_report(state: AnalysisState, *, method: str) -> GapReport:
    """RFP 후보가 없으면 판정하지 않는다. 검색 실패는 기술 미보유·추가 R&D 필요를 뜻하지 않는다."""
    return GapReport(
        problem=state.request.problem, method=method,
        summary={label.value: 0 for label in GapLabel},
        owned_not_required=list(state.request.owned_technologies),
        warnings=["rfp: 후보가 없어 Gap 판정을 수행하지 않았습니다. 기술 미보유나 추가 R&D 필요를 의미하지 않습니다."],
    )


def build_pool(state: AnalysisState, *, include_ntis: bool = True) -> list[_PoolItem]:
    """비교 대상: 보유기술 + 기술나눔(기술요소 + 기술요소가 없는 후보의 검색 본문) + NTIS 기술요소(선택)."""
    elements = _document_pool(state.external_elements, state.technology.candidates)
    covered = {item.doc_id for item in elements}
    return (
        _company_pool(state.request.owned_technologies)
        + elements
        + _candidate_pool(state.technology, covered)
        + (_document_pool(state.ntis_elements, state.ntis.candidates) if include_ntis else [])
    )


def build_report(state: AnalysisState, requirements: Sequence[_Requirement],
                 align: Callable[[_Requirement, Sequence[_PoolItem]], list[SourceMatch]] | None,
                 warnings: list[str], *, method: str, workers: int = 1,
                 align_many: Callable[[list[_Requirement], Sequence[_PoolItem]], list[list[SourceMatch]]] | None = None,
                 ntis_reference: Callable[[_Requirement], list[SourceMatch]] | None = None) -> GapReport:
    """요구기술별 매칭 → 라벨 결정 → 리포트 조립. llm·local 모드가 공유해 판정 규칙을 동일하게 유지한다.

    `align`은 요구기술 1개씩, `align_many`는 원문 근거가 검증된 요구기술 전체를 한 번에 받아 같은 순서로
    매칭 목록을 돌려준다. `ntis_reference`를 주면 NTIS는 비교 풀에서 빼고 참고 근거로만 붙인다.
    `align`은 요구기술별로 병렬 실행할 수 있다(workers). 결과 순서는 요구기술 순서를 유지한다.
    """
    owned = list(state.request.owned_technologies)
    report = GapReport(problem=state.request.problem, method=method,
                       summary={label.value: 0 for label in GapLabel})
    pool = build_pool(state, include_ntis=ntis_reference is None)
    external_count = sum(item.source in TECHNOLOGY_SOURCES for item in pool)
    if not external_count:
        warnings.append("technology: 비교할 기술나눔 후보가 없어 외부기술보완 판정이 나올 수 없습니다.")

    verified_flags = [any(ev.verified for ev in r.element.evidences) for r in requirements]
    if align_many is not None:
        aligned = iter(align_many([r for r, ok in zip(requirements, verified_flags) if ok], pool))
        all_matches = [next(aligned) if ok else [] for ok in verified_flags]
    else:
        all_matches = _parallel_map(
            lambda pair: align(pair[0], pool) if pair[1] else [], list(zip(requirements, verified_flags)), workers,
        )
    for requirement, verified, matches in zip(requirements, verified_flags, all_matches):
        company = [m for m in matches if m.source == SourceType.COMPANY]
        external = [m for m in matches if m.source in TECHNOLOGY_SOURCES]
        if ntis_reference is None:
            ntis = [m for m in matches if m.source == SourceType.NTIS]
        else:
            ntis = ntis_reference(requirement) if verified else []
        label, path = decide_label(
            requirement_verified=verified, requirement_clear=requirement.clear,
            company=company, external=external, external_available=external_count > 0,
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
    report.stats = {"pool_size": {
        "company": sum(item.source == SourceType.COMPANY for item in pool),
        "technology": external_count,
        "ntis": sum(item.source == SourceType.NTIS for item in pool),
    }}
    return report
