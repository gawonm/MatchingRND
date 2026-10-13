from typing import Any, Dict, Optional, Sequence

from .analysis import (
    aggregate_prior_rd_axes,
    canonicalize_technologies,
    extract_all_project_tech,
    structure_query,
)
from .config import ANALYSIS_TOP_N
from .retrieval import retrieve_ntis


def run_ntis_pipeline(
    problem: str,
    owned_technologies: Optional[Sequence[str]] = None,
    external_technologies: Optional[Sequence[str]] = None,
    analysis_top_n: int = ANALYSIS_TOP_N,
) -> Dict[str, Any]:
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
