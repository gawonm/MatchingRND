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

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from app.orchestrator import (
    AnalysisRequest,
    AnalysisState,
    OrchestrationError,
    RagOrchestrator,
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