from typing import Any, Dict, Optional, Sequence

from .config import ANALYSIS_TOP_N


def run_ntis_module(problem: str, **options):
    """팀 통합 진입점. 분석 결과를 공통 ModuleResult로 반환합니다."""
    from .adapter import to_module_result

    return to_module_result(run_ntis_pipeline(problem, **options))


def run_ntis_pipeline(
    problem: str,
    owned_technologies: Optional[Sequence[str]] = None,
    external_technologies: Optional[Sequence[str]] = None,
    analysis_top_n: int = ANALYSIS_TOP_N,
) -> Dict[str, Any]:
    from .generation.analysis import (
        aggregate_prior_rd_axes,
        canonicalize_technologies,
        extract_all_project_tech,
        structure_query,
    )
    from .retrieval.pipeline import retrieve_ntis

    if analysis_top_n < 1:
        raise ValueError("analysis_top_n은 1 이상이어야 합니다.")

    structured_query = structure_query(
        problem=problem,
        owned_technologies=owned_technologies,
        external_technologies=external_technologies,
    )
    related_projects = retrieve_ntis(structured_query, analysis_top_n)
    project_analyses = extract_all_project_tech(related_projects)
    canonical_technologies = canonicalize_technologies(project_analyses)
    prior_rd_axes = aggregate_prior_rd_axes(canonical_technologies)

    return {
        "query": {
            "original_query": problem,
            "structured_query": structured_query,
        },
        "related_projects": related_projects,
        "project_analyses": project_analyses,
        "canonical_technologies": canonical_technologies,
        "prior_rd_axes": prior_rd_axes,
    }
