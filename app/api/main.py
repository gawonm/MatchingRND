from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.discovery import router as discovery_router


@asynccontextmanager
async def lifespan(_app):
    log_runtime_settings()
    yield


app = FastAPI(
    title="R&D Match API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(discovery_router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "message": "R&D Match API is running"
    }


@app.get("/api/capabilities")
def capabilities():
    """Public MVP scope; unsupported modules are explicit instead of implied."""
    return {
        "supported_analysis": ["technology", "ntis", "rfp", "gap_report"],
        "unsupported_analysis": ["policy_search", "legal_eligibility", "company_database_verification"],
        "company_input_provenance": "user_assertion_not_independently_verified",
        "paid_llm_calls": "only_on_explicit_analysis_requests",
    }

from functools import lru_cache
import os

from dotenv import load_dotenv
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from app.common.paths import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env", override=False)

from app.orchestrator import (
    AnalysisRequest,
    AnalysisState,
    OrchestrationError,
    RagOrchestrator,
)
from app.final_answer import FinalAnswer
from app.integrated_analysis import run_integrated_analysis
from app.query_parser import InputTechnology, parse_query
from app.analysis_view import AnalysisView, ProjectionError, project_analysis_view
import logging
from typing import Literal
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def runtime_settings() -> dict:
    """Effective backend/model settings for the startup log. Never includes credentials."""
    from app.common.llm_config import DEFAULT_LLM_MODEL
    from app.technology_rag.config import load_config

    overrides = ("NTIS_LLM_MODEL", "NTIS_RELEVANCE_MODEL", "RFP_RELEVANCE_MODEL",
                 "RFP_EMBEDDING_MODEL", "NTIS_EMBEDDING_MODEL")
    return {
        "rag_backend": os.getenv("RAG_BACKEND", "local"),  # RagOrchestrator()와 같은 규칙
        "rag_backend_from_env": "RAG_BACKEND" in os.environ,
        "default_llm_model": DEFAULT_LLM_MODEL,
        "technology_llm_model": load_config().llm.model,
        **{name.lower(): os.getenv(name) for name in overrides if os.getenv(name)},
    }


def log_runtime_settings():
    log = logging.getLogger("uvicorn.error")
    settings = runtime_settings()
    log.info("RAG runtime settings: %s", settings)
    if not settings["rag_backend_from_env"]:
        # 비UI CLI(tests/integration_e2e.py, app/scripts/run_analysis.py)는 --backend 기본값 supabase를 쓴다.
        log.warning("RAG_BACKEND 미설정: FastAPI는 local, 비UI CLI는 supabase를 사용합니다. RAG_BACKEND를 명시하세요.")


class ReportGenerationError(RuntimeError):
    """Safe stage marker for a failed report pipeline."""

    def __init__(self, stage: str):
        self.stage = stage
        super().__init__(f"report stage failed: {stage}")


class ExtractionRequest(BaseModel):
    """Original query, or A/problem fields with optional B."""

    owned_description: str = ""
    required_description: str | None = None
    problem: str = ""
    original_query: str | None = None


class ExtractionResponse(BaseModel):
    """Extraction candidates only; nothing is approved or stored server-side."""

    owned: list[InputTechnology]
    requested: list[InputTechnology]
    warnings: list[str]
    policy_question: str | None = None


def extraction_query(request: ExtractionRequest) -> str:
    if request.original_query and request.original_query.strip():
        return request.original_query.strip()
    lines = [f"현재 보유한 기술: {request.owned_description.strip()}"]
    if request.required_description and request.required_description.strip():
        lines.append(f"보완·확보하고 싶은 기술: {request.required_description.strip()}")
    lines.append(f"해결하려는 문제: {request.problem.strip()}")
    return "\n".join(lines)


@app.post("/api/analysis/extract", response_model=ExtractionResponse)
async def extract_elements(request: ExtractionRequest):
    if not (request.original_query and request.original_query.strip()) and (
        not request.owned_description.strip() or not request.problem.strip()
    ):
        raise HTTPException(status_code=422, detail={
            "error": "invalid_input",
            "message": "보유 기술과 해결 문제를 입력해 주세요.",
        })
    try:
        max_retries = int(os.getenv("QUERY_EXTRACTION_MAX_RETRIES", "2"))
        if max_retries < 0:
            raise ValueError("QUERY_EXTRACTION_MAX_RETRIES는 0 이상이어야 합니다.")
        result = await run_in_threadpool(
            parse_query, extraction_query(request), max_retries=max_retries,
        )
    except ValueError as exc:
        # parse_query could not ground the extracted names in the user's text.
        raise HTTPException(status_code=422, detail={
            "error": "extraction_unverified",
            "message": "원문에서 확인 가능한 기술요소를 추출하지 못했습니다. 입력을 보완하거나 직접 정리해 주세요.",
        }) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={
            "error": "extraction_failed",
            "message": "기술요소 추출에 실패했습니다.",
        }) from exc
    return ExtractionResponse(
        owned=result.parsed.owned, requested=result.parsed.requested, warnings=result.warnings,
        policy_question=result.request.policy_question,
    )


@lru_cache(maxsize=1)
def get_orchestrator() -> RagOrchestrator:
    """Reuse the orchestrator across requests."""
    return RagOrchestrator()


@app.post("/api/analysis", response_model=AnalysisState)
async def analyze(request: AnalysisRequest):
    try:
        result = await run_in_threadpool(
            get_orchestrator().run,
            request,
        )
        return result

    except OrchestrationError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "analysis_failed",
                "stage": exc.stage,
                "message": "RAG 분석 단계 실행에 실패했습니다.",
            },
        ) from exc


def generate_analysis_report(request: AnalysisRequest) -> FinalAnswer:
    result = run_integrated_analysis(
        request=request,
        orchestrator=get_orchestrator(),
        modes=("llm",),
    )
    if "llm" not in result.answers:
        raise ReportGenerationError(next(iter(result.errors), "report"))
    return result.answers["llm"]


class ReportViewResponse(BaseModel):
    """Versioned response: the unchanged FinalAnswer plus an optional UI read model."""

    report: FinalAnswer
    view: AnalysisView | None
    view_status: Literal["ok", "failed"] = Field(
        description="failed는 Projection 실패이며 분석 결과가 비었다는 뜻이 아니다")
    view_error: str | None = Field(default=None, description="실패 코드 (원인 상세는 서버 로그)")


def generate_report_with_view(request: AnalysisRequest) -> ReportViewResponse:
    # One retrieval, one Gap analysis and one answer; the view reuses that run's objects.
    state = get_orchestrator().run(request)
    result = run_integrated_analysis(state=state, modes=("llm",))
    if "llm" not in result.answers:
        raise ReportGenerationError(next(iter(result.errors), "report"))
    answer = result.answers["llm"]
    try:
        view = project_analysis_view(state, result.reports["llm"], answer)
    except Exception as exc:
        code = exc.code if isinstance(exc, ProjectionError) else "projection_error"
        logger.exception("analysis view projection failed: %s", code)
        return ReportViewResponse(report=answer, view=None, view_status="failed", view_error=code)
    return ReportViewResponse(report=answer, view=view, view_status="ok")


@app.post("/api/analysis/report-view", response_model=ReportViewResponse)
async def analyze_report_view(request: AnalysisRequest):
    try:
        return await run_in_threadpool(generate_report_with_view, request)
    except OrchestrationError as exc:
        raise HTTPException(status_code=500, detail={
            "error": "report_failed", "stage": exc.stage,
            "message": "보고서 검색 단계 실행에 실패했습니다.",
        }) from exc
    except ReportGenerationError as exc:
        raise HTTPException(status_code=500, detail={
            "error": "report_failed", "stage": exc.stage,
            "message": "보고서 생성 단계 실행에 실패했습니다.",
        }) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "report_failed",
                "message": "분석 보고서 생성에 실패했습니다.",
            },
        ) from exc


@app.post("/api/analysis/report", response_model=FinalAnswer)
async def analyze_report(request: AnalysisRequest):
    try:
        return await run_in_threadpool(generate_analysis_report, request)
    except OrchestrationError as exc:
        raise HTTPException(status_code=500, detail={
            "error": "report_failed", "stage": exc.stage,
            "message": "보고서 검색 단계 실행에 실패했습니다.",
        }) from exc
    except ReportGenerationError as exc:
        raise HTTPException(status_code=500, detail={
            "error": "report_failed", "stage": exc.stage,
            "message": "보고서 생성 단계 실행에 실패했습니다.",
        }) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "report_failed",
                "message": "분석 보고서 생성에 실패했습니다.",
            },
        ) from exc
