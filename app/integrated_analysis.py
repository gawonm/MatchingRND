"""Compare Gap methods over one immutable retrieval snapshot and generate answers."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from app.final_answer import FinalAnswer, generate_final_answer
from app.gap_analysis import GapReport, OpenAIStructuredLLM, run_gap_analysis
from app.gap_analysis_local import run_gap_analysis_local
from app.orchestrator import AnalysisRequest, AnalysisState, RagOrchestrator


class AnalysisRun(BaseModel):
    primary_method: str = "llm"
    reports: dict[str, GapReport] = Field(default_factory=dict)
    answers: dict[str, FinalAnswer] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    comparison: dict = Field(default_factory=dict)


def compare_reports(llm: GapReport, local: GapReport) -> dict:
    def rows(report):
        grouped = {}
        for item in report.items:
            key = "".join(item.requirement.name.split()).casefold()
            grouped.setdefault(key, []).append(item)
        return grouped
    a, b = rows(llm), rows(local)
    shared = []
    for key in sorted(a.keys() & b.keys()):
        if len(a[key]) == len(b[key]) == 1:
            left, right = a[key][0], b[key][0]
            shared.append({"requirement": left.requirement.name, "llm": left.label.value,
                           "local": right.label.value, "same_label": left.label == right.label})
    return {
        "note": "명칭이 동일하고 유일한 요구기술만 직접 비교합니다. 추출 단위가 달라 불일치율은 정확도 지표가 아닙니다.",
        "shared_exact_requirements": shared,
        "llm_only": [row.requirement.name for key in sorted(a.keys() - b.keys()) for row in a[key]],
        "local_only": [row.requirement.name for key in sorted(b.keys() - a.keys()) for row in b[key]],
        "llm_summary": llm.summary, "local_summary": local.summary,
        "llm_stats": llm.stats, "local_stats": local.stats,
    }


def save_model(path: Path, model: BaseModel):
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def run_integrated_analysis(
    *, request: AnalysisRequest | None = None, state: AnalysisState | None = None,
    orchestrator: RagOrchestrator | None = None, modes=("llm", "local"),
    output_dir: str | Path | None = None, model: str = "gpt-4o-mini",
    template_only: bool = False, embed=None,
    llm_factory: Callable | None = None, gap_runners: dict | None = None,
    answer_generator: Callable = generate_final_answer,
) -> AnalysisRun:
    if (request is None) == (state is None):
        raise ValueError("request 또는 state 중 하나만 제공하세요.")
    if not modes or len(set(modes)) != len(modes) or set(modes) - {"llm", "local"}:
        raise ValueError("분석 방식은 llm, local 또는 두 방식이어야 합니다.")
    target = Path(output_dir) if output_dir is not None else None
    if target:
        target.mkdir(parents=True, exist_ok=True)
        if any(target.glob('*.json')) or any(target.glob('*.md')):
            raise FileExistsError("결과 파일이 있는 폴더입니다. 새로운 output-dir를 지정하세요.")
    if state is None:
        state = (orchestrator or RagOrchestrator()).run(request)
    state = AnalysisState.model_validate(state).model_copy(deep=True)
    if target:
        save_model(target / "state.json", state)
    factory = llm_factory or (lambda: OpenAIStructuredLLM(model=model))
    runners = gap_runners or {"llm": run_gap_analysis, "local": run_gap_analysis_local}
    result = AnalysisRun()
    for method in modes:
        # Both methods receive the same snapshot; one cannot mutate the other's input.
        try:
            options = {"embed": embed}
            if method == "llm":
                options["llm"] = factory()
            report = GapReport.model_validate(runners[method](state.model_copy(deep=True), **options))
            if report.method != method:
                raise ValueError("Gap 결과의 분석 방식이 요청 방식과 다릅니다.")
            result.reports[method] = report
            if target:
                save_model(target / f"gap_{method}.json", report)
        except Exception as error:
            result.errors[f"gap_{method}"] = str(error)
            continue
        try:
            answer = answer_generator(
                state, report, template_only=template_only,
                llm=None if template_only else factory(),
            )
            result.answers[method] = answer
            if target:
                save_model(target / f"answer_{method}.json", answer)
                (target / f"answer_{method}.md").write_text(answer.markdown, encoding="utf-8")
                if method == "llm":
                    (target / "answer.md").write_text(answer.markdown, encoding="utf-8")
        except Exception as error:
            result.errors[f"answer_{method}"] = str(error)
    if "llm" in result.reports and "local" in result.reports:
        result.comparison = compare_reports(result.reports["llm"], result.reports["local"])
    if target:
        save_model(target / "comparison.json", result)
    return result
