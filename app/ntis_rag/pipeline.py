from typing import Any, Dict, Optional, Sequence

from .config import ANALYSIS_TOP_N, RERANK_CANDIDATES


def run_ntis_module(problem: str, **options):
    """팀 통합 진입점. 분석 결과를 공통 ModuleResult로 반환합니다."""
    from .adapter import to_module_result

    return to_module_result(run_ntis_pipeline(problem, **options))


def run_ntis_pipeline(
    problem: str,
    owned_technologies: Optional[Sequence[str]] = None,
    external_technologies: Optional[Sequence[str]] = None,
    analysis_top_n: int = ANALYSIS_TOP_N,
    requested_technologies: Optional[Sequence[str]] = None,
    relevance_llm=None,
    *,
    _retriever=None,
) -> Dict[str, Any]:
    from .generation.analysis import (
        aggregate_prior_rd_axes,
        canonicalize_technologies,
        extract_all_project_tech,
        structure_query,
    )
    from .retrieval.eligibility import TechnologyRelevanceGate

    if analysis_top_n < 1:
        raise ValueError("analysis_top_n은 1 이상이어야 합니다.")
    if _retriever is None:
        from .retrieval.pipeline import retrieve_ntis

        _retriever = retrieve_ntis

    structured_query = structure_query(
        problem=problem,
        owned_technologies=owned_technologies,
        external_technologies=external_technologies,
    )
    # Explicit B terms improve retrieval but do not replace the original problem.
    requested = [name.strip() for name in (requested_technologies or []) if name.strip()]
    structured_query = dict(structured_query)
    structured_query['search_query'] = '\n'.join(dict.fromkeys([
        problem.strip(), structured_query['search_query'], *requested,
    ]))
    gate = TechnologyRelevanceGate(problem, owned_technologies, requested, relevance_llm)
    projects = _retriever(structured_query, max(RERANK_CANDIDATES, analysis_top_n))
    related_projects, checks, seen = [], [], set()
    for project in projects:
        pid = str(project['project_id'])
        if pid in seen:
            continue
        seen.add(pid)
        check = gate.check(project)
        checks.append({'project_id': pid, **check})
        if check['accepted']:
            related_projects.append({**project, 'technology_relevance': check})
        if len(related_projects) >= analysis_top_n:
            break
    # Rejected projects must never enter extraction, query expansion or Gap analysis.
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
        "diagnostics": {"technology_relevance": {
            "owned_technologies": gate.owned, "requested_technologies": gate.requested,
            "checks": checks,
        }},
        "status": "ok" if related_projects else "no_matches",
        "message": "관련 과제를 찾았습니다." if related_projects else "관련 NTIS 과제가 없습니다.",
    }
