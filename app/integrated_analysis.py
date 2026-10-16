"""Run the LLM Gap analysis over one retrieval snapshot and generate an answer."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from app.final_answer import FinalAnswer, generate_final_answer
from app.gap_analysis import GapReport, OpenAIStructuredLLM, run_gap_analysis
from app.orchestrator import AnalysisRequest, AnalysisState, RagOrchestrator


class AnalysisRun(BaseModel):
    primary_method: str = "llm"
    reports: dict[str, GapReport] = Field(default_factory=dict)
    answers: dict[str, FinalAnswer] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    comparison: dict = Field(default_factory=dict)


def save_model(path: Path, model: BaseModel):
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def run_integrated_analysis(
    *,
    request: AnalysisRequest | None = None,
    state: AnalysisState | None = None,
    orchestrator: RagOrchestrator | None = None,
    modes=("llm",),
    output_dir: str | Path | None = None,
    model: str = "gpt-4o-mini",
    template_only: bool = False,
    embed=None,
    llm_factory: Callable | None = None,
    gap_runner: Callable = run_gap_analysis,
    answer_generator: Callable = generate_final_answer,
) -> AnalysisRun:
    """Execute the production LLM path from one immutable retrieval snapshot."""
    if (request is None) == (state is None):
        raise ValueError("request 또는 state 중 하나만 제공하세요.")
    if tuple(modes) != ("llm",):
        raise ValueError("Gap 분석 방식은 llm만 지원합니다.")

    target = Path(output_dir) if output_dir is not None else None
    if target:
        target.mkdir(parents=True, exist_ok=True)
        if any(target.glob("*.json")) or any(target.glob("*.md")):
            raise FileExistsError("결과 파일이 있는 폴더입니다. 새 output-dir을 지정하세요.")

    if state is None:
        state = (orchestrator or RagOrchestrator()).run(request)
    state = AnalysisState.model_validate(state).model_copy(deep=True)
    if target:
        save_model(target / "state.json", state)

    factory = llm_factory or (lambda: OpenAIStructuredLLM(model=model))
    result = AnalysisRun()
    try:
        report = GapReport.model_validate(
            gap_runner(state.model_copy(deep=True), embed=embed, llm=factory())
        )
        if report.method != "llm":
            raise ValueError("Gap 결과의 분석 방식이 llm이 아닙니다.")
        result.reports["llm"] = report
        if target:
            save_model(target / "gap_llm.json", report)
    except Exception as error:
        result.errors["gap_llm"] = str(error)
    else:
        try:
            answer = answer_generator(
                state,
                report,
                template_only=template_only,
                llm=None if template_only else factory(),
            )
            result.answers["llm"] = answer
            if target:
                save_model(target / "answer_llm.json", answer)
                (target / "answer_llm.md").write_text(answer.markdown, encoding="utf-8")
                (target / "answer.md").write_text(answer.markdown, encoding="utf-8")
        except Exception as error:
            result.errors["answer_llm"] = str(error)

    if target:
        save_model(target / "comparison.json", result)
    return result
