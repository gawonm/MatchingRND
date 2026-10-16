"""Technology -> NTIS -> RFP cascade, followed by optional policy retrieval.

This module coordinates the existing RAG implementations. It returns evidence
and query provenance for subsequent alignment, Gap analysis and answer generation;
it does not infer technical coverage or legal eligibility from retrieval scores.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.common.schemas import ModuleResult, SourceType, TechElement
from app.common.paths import PROJECT_ROOT, RFP_PDF_DIR, RFP_NOTICE_PATH, POLICY_RAW_DIR
from app.rfp_rag.retrieval.query import build_query



class AnalysisRequest(BaseModel):
    """User input; unmet elements are user-supplied review items, not Gap verdicts."""

    problem: str = Field(min_length=1)
    owned_technologies: list[str] = Field(default_factory=list)
    unmet_elements: list[str] = Field(default_factory=list)
    policy_question: str | None = None

    @field_validator("problem", "policy_question")
    @classmethod
    def clean_text(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("질문은 비어 있지 않은 문자열이어야 합니다.")
        return value

    @field_validator("owned_technologies", "unmet_elements")
    @classmethod
    def clean_names(cls, values):
        names, seen = [], set()
        for value in values:
            name = value.strip()
            if not name:
                raise ValueError("기술요소 이름은 비어 있을 수 없습니다.")
            key = "".join(name.split()).casefold()
            if key not in seen:
                seen.add(key)
                names.append(name)
        return names


class AnalysisState(BaseModel):
    """Cascade outputs retaining original input and all module-specific evidence."""

    request: AnalysisRequest
    technology: ModuleResult
    ntis: ModuleResult
    rfp: ModuleResult
    policy: ModuleResult | None = None
    external_elements: list[TechElement] = Field(default_factory=list)
    ntis_elements: list[TechElement] = Field(default_factory=list)
    queries: dict[str, str] = Field(default_factory=dict)
    rfp_query_details: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class OrchestrationError(RuntimeError):
    """Stage failure; preserve the original exception via exception chaining."""

    def __init__(self, stage: str, cause: Exception):
        self.stage = stage
        super().__init__(f"{stage} 단계 실행 실패: {cause}")


def _as_module_result(value: Any, module: str) -> ModuleResult:
    # Technology.answer returns GenerationResult; integrations may serialize it.
    if isinstance(value, Mapping) and "result" in value:
        value = value["result"]
    elif not isinstance(value, (ModuleResult, Mapping)) and hasattr(value, "result"):
        value = value.result
    result = ModuleResult.model_validate(value)
    if result.module != module:
        raise ValueError(f"{module} 결과를 기대했지만 {result.module} 결과를 받았습니다.")
    return result


def _cascade_elements(result: ModuleResult) -> list[TechElement]:
    """Keep verified, correctly attributed evidence without dropping provenance."""
    allowed = {SourceType.PUBLIC_TECH, SourceType.POSCO_TECH} if result.module == "technology" else {SourceType.NTIS}
    elements = list(result.tech_elements)
    elements.extend(element for candidate in result.candidates for element in candidate.tech_elements)
    selected, seen = [], set()
    for element in elements:
        if element.origin not in allowed or not element.name.strip():
            continue
        evidences = [ev for ev in element.evidences if ev.verified and ev.quote.strip() and ev.source in allowed]
        unique = []
        for evidence in evidences:
            key = ("".join(element.name.split()).casefold(), evidence.source, evidence.doc_id, evidence.quote)
            if key not in seen:
                seen.add(key)
                unique.append(evidence)
        if unique:
            selected.append(element.model_copy(update={"evidences": unique}))
    return selected


def _expansion_rows(elements: list[TechElement]) -> list[dict[str, str]]:
    return [
        {"technology": element.name.strip(), "quote": evidence.quote, "source_id": evidence.doc_id}
        for element in elements for evidence in element.evidences
    ]


POLICY_DEFAULT_TERMS = "기술이전 사업화 국가연구개발사업 참여 요건 협약 지식재산 귀속"
POLICY_QUERY_MAX_CHARS = 300  # 임베딩 토큰 한도(질문 길이 검사) 초과 방지


def build_policy_query(request: AnalysisRequest) -> str:
    """법령 검색어: 사용자의 제도 질문 + 확보하려는 기술 + 고정 제도 키워드.

    제도 질문이 없어도 기술 맥락과 R&D·기술이전 키워드로 관련 조문을 찾도록 한다.
    """
    targets = request.unmet_elements[:3] or [request.problem]
    parts = [request.policy_question or "", *targets, POLICY_DEFAULT_TERMS]
    # 고정 키워드는 항상 남기고 앞쪽(사용자 입력)을 잘라 한도에 맞춘다.
    query = " ".join(part.strip() for part in parts if part and part.strip())
    if len(query) > POLICY_QUERY_MAX_CHARS:
        head = " ".join(part.strip() for part in parts[:-1] if part and part.strip())
        head = head[:max(0, POLICY_QUERY_MAX_CHARS - len(POLICY_DEFAULT_TERMS) - 1)]
        query = f"{head} {POLICY_DEFAULT_TERMS}".strip()
    return query


class RagOrchestrator:
    """Reusable coordinator; injected runners make integration independently testable.

    technology_runner(query, owned_technologies=..., targets=...) returns ModuleResult or GenerationResult.
    ntis_runner(problem, owned_technologies=..., external_technologies=...) returns ModuleResult.
    rfp_runner(query_details) and policy_runner(question) return ModuleResult.
    Default implementations load pipelines/indexes on first use and reuse them.
    """

    def __init__(
        self,
        *,
        technology_runner: Callable[..., Any] | None = None,
        ntis_runner: Callable[..., Any] | None = None,
        rfp_runner: Callable[..., Any] | None = None,
        policy_runner: Callable[..., Any] | None = None,
        technology_config: Any = None,
        rfp_data_dir: str | Path = RFP_PDF_DIR,
        policy_data_dir: str | Path = POLICY_RAW_DIR,
        rfp_notice_path: str | Path = RFP_NOTICE_PATH,
        index_dir: str | Path = PROJECT_ROOT / "db",
        backend: str | None = None,
    ):
        import os
        self.backend = backend or os.getenv('RAG_BACKEND', 'local')
        if self.backend not in {'local', 'supabase'}:
            raise ValueError('backend는 local 또는 supabase여야 합니다.')
        self.technology_runner = technology_runner or self._technology_answer
        self.ntis_runner = ntis_runner or self._ntis_analysis
        self.rfp_runner = rfp_runner or self._rfp_search
        self.policy_runner = policy_runner or self._policy_search
        self.technology_config = technology_config
        self.rfp_data_dir = rfp_data_dir
        self.policy_data_dir = policy_data_dir
        self.rfp_notice_path = rfp_notice_path
        index_dir = Path(index_dir)
        self.index_dir = index_dir if index_dir.is_absolute() else PROJECT_ROOT / index_dir
        self._technology_pipeline = None
        self._rfp_index = None
        self._policy_index = None

    def _technology_answer(self, query, owned_technologies=None, targets=None):
        from app.technology_rag.pipeline import TechnologyRagPipeline

        if self._technology_pipeline is None:
            config = self.technology_config
            if self.backend == 'supabase':
                from app.technology_rag.config import load_config, TechnologyRagConfig
                config = config.model_copy(deep=True) if isinstance(config, TechnologyRagConfig) else load_config(config)
                config.index.backend = 'supabase'
            self._technology_pipeline = TechnologyRagPipeline.from_config(config)
        # Technology RAG 는 문장을 분해하지 않는다: 보유기술(A)과 확보하려는 기술(B)을 받아 B 로 검색·판정한다.
        return self._technology_pipeline.answer(owned_technologies or [], targets or query)

    def _ntis_analysis(self, problem, **options):
        if self.backend == 'supabase':
            from app.common.supabase_retrieval import run_ntis_module
            return run_ntis_module(problem, **options)
        from app.ntis_rag.pipeline import run_ntis_module

        return run_ntis_module(problem, **options)

    def _rfp_search(self, details):
        from app.rfp_rag.pipeline import build_index, search_module_result

        if self._rfp_index is None:
            if self.backend == 'supabase':
                from app.common.supabase_retrieval import load_pdf_index
                self._rfp_index = load_pdf_index('rfp')
            else:
                self._rfp_index = build_index(
                    data_dir=self.rfp_data_dir, output_dir=self.index_dir / "rfp",
                    notice_path=self.rfp_notice_path,
                )
        return search_module_result(self._rfp_index, details)

    def _policy_search(self, question):
        from app.policy_rag.pipeline import build_index, search_module_result

        if self._policy_index is None:
            if self.backend == 'supabase':
                from app.common.supabase_retrieval import load_pdf_index
                self._policy_index = load_pdf_index('policy')
            else:
                self._policy_index = build_index(
                    data_dir=self.policy_data_dir, output_dir=self.index_dir / "law",
                )
        return search_module_result(self._policy_index, question)

    @staticmethod
    def _execute(module, runner, *args, **kwargs):
        try:
            return _as_module_result(runner(*args, **kwargs), module)
        except Exception as error:
            raise OrchestrationError(module, error) from error

    def run(self, request: AnalysisRequest | dict[str, Any]) -> AnalysisState:
        """Run the cascade; preserve empty results and surface stage errors.

        Only verified elements expand later queries. The original problem remains
        explicit in NTIS input and at the beginning of the RFP baseline query.
        No uncovered requirement is inferred merely from a failed/empty search.
        """
        request = AnalysisRequest.model_validate(request).model_copy(deep=True)
        baseline = build_query(request.owned_technologies, request.problem)
        # B = 사용자가 확보하려는 기술(unmet_elements). 없으면 기술문제 전체를 B 로 쓴다.
        technology = self._execute(
            "technology", self.technology_runner, baseline,
            owned_technologies=list(request.owned_technologies),
            targets=list(request.unmet_elements) or [request.problem],
        )
        external = _cascade_elements(technology)
        external_names = list(dict.fromkeys(element.name.strip() for element in external))
        ntis_options = {}
        if request.unmet_elements:
            ntis_options['requested_technologies'] = list(request.unmet_elements)
        ntis = self._execute(
            "ntis", self.ntis_runner, request.problem,
            owned_technologies=list(request.owned_technologies), external_technologies=external_names,
            **ntis_options,
        )
        ntis_elements = _cascade_elements(ntis)
        details = build_query(
            request.owned_technologies, request.problem,
            external_elements=_expansion_rows(external), ntis_elements=_expansion_rows(ntis_elements),
            unmet_elements=request.unmet_elements, return_details=True,
        )
        # Pass a copy so a runner cannot overwrite the recorded query provenance.
        import copy
        rfp = self._execute("rfp", self.rfp_runner, copy.deepcopy(details))
        warnings = []
        # 모든 질문에 제도 참고용 법령을 검색한다. 실패해도 기술 분석 결과는 보존한다.
        policy_query = build_policy_query(request)
        try:
            policy = self._execute("policy", self.policy_runner, policy_query)
        except OrchestrationError as error:
            policy = None
            warnings.append(f"policy: 법령 검색에 실패해 제외했습니다 ({error.__cause__}).")
        for module in (technology, ntis, rfp, policy):
            if module is not None and not module.candidates:
                warnings.append(f"{module.module}: 검색 후보가 없습니다. 기술 미보유나 추가 R&D 필요를 의미하지 않습니다.")
        for name, elements in (("technology", external), ("ntis", ntis_elements)):
            if not elements:
                warnings.append(f"{name}: 검증된 기술요소가 없어 해당 단계의 Query 확장을 생략했습니다.")
        queries = {"technology": baseline, "ntis": ntis.query, "rfp": details["query"], "policy": policy_query}
        return AnalysisState(
            request=request, technology=technology, ntis=ntis, rfp=rfp, policy=policy,
            external_elements=external, ntis_elements=ntis_elements, queries=queries,
            rfp_query_details=details, warnings=warnings,
        )
