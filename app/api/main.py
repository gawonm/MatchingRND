from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="R&D Match API",
    version="0.1.0"
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


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "message": "R&D Match API is running"
    }

from functools import lru_cache

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


class ExtractionRequest(BaseModel):
    """Wizard Step 1 input: A (required), B (optional), problem (required)."""

    owned_description: str = Field(min_length=1)
    required_description: str | None = None
    problem: str = Field(min_length=1)


class ExtractionResponse(BaseModel):
    """Extraction candidates only; nothing is approved or stored server-side."""

    owned: list[InputTechnology]
    requested: list[InputTechnology]
    warnings: list[str]


def extraction_query(request: ExtractionRequest) -> str:
    lines = [f"현재 보유한 기술: {request.owned_description.strip()}"]
    if request.required_description and request.required_description.strip():
        lines.append(f"보완·확보하고 싶은 기술: {request.required_description.strip()}")
    lines.append(f"해결하려는 문제: {request.problem.strip()}")
    return "\n".join(lines)


@app.post("/api/analysis/extract", response_model=ExtractionResponse)
async def extract_elements(request: ExtractionRequest):
    if not request.owned_description.strip() or not request.problem.strip():
        raise HTTPException(status_code=422, detail={
            "error": "invalid_input",
            "message": "보유 기술과 해결 문제를 입력해 주세요.",
        })
    try:
        result = await run_in_threadpool(parse_query, extraction_query(request))
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
        raise RuntimeError(next(iter(result.errors), "report"))
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
        raise RuntimeError(next(iter(result.errors), "report"))
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
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "report_failed",
                "message": "분석 보고서 생성에 실패했습니다.",
            },
        ) from exc
