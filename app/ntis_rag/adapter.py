"""NTIS 결과를 검증된 공통 ModuleResult 또는 JSON 호환 dict로 변환합니다."""
import hashlib
import re
from collections import defaultdict

from app.common.schemas import Evidence, ExternalTechCandidate, ModuleResult, RetrievalHit, TechElement


def to_module_result(result) -> ModuleResult:
    query = result["query"]
    structured = {}
    if isinstance(query, dict):
        structured = query.get("structured_query") or {}
        query = query.get("problem") or query.get("original_query") or query.get("query")
    if not isinstance(query, str):
        raise ValueError("원본 자연어 query 필드를 확인해야 합니다.")
    projects = {str(p["project_id"]): p for p in result["related_projects"]}
    tech_by_project = defaultdict(list)
    all_elements = []
    for row in result["canonical_technologies"]:
        pid = str(row["project_id"])
        if pid not in projects:
            continue
        quote = row.get("evidence") or ""
        evidence = Evidence(
            doc_id=f"ntis-{pid}", source="ntis", quote=quote,
            verified=bool(quote and quote in (projects[pid].get("text") or "")),
        )
        name = row["canonical_name"]
        normalized = re.sub(r"\s+", "", name).lower()
        element = TechElement(
            element_id="te-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10],
            name=name, surface_forms=[row["original_element"]], origin="ntis",
            evidences=[evidence],
        )
        tech_by_project[pid].append(element)
        all_elements.append(element)

    candidates, hits = [], []
    for pid, project in projects.items():
        doc_id = f"ntis-{pid}"
        ranks = project.get("source_ranks") or {}
        hit = RetrievalHit(
            chunk_id=f"{doc_id}#project", doc_id=doc_id, source="ntis",
            text=project.get("text") or "", dense_rank=ranks.get("dense"),
            bm25_rank=ranks.get("bm25"), rrf_score=project.get("rrf_score"),
            rerank_score=project.get("rerank_score"), final_rank=project.get("rank"),
            retriever="hybrid_rerank" if project.get("rerank_score") is not None else "hybrid",
            extra={"project_id": pid, "metadata": project.get("metadata", {})},
        )
        hits.append(hit)
        score = project.get("rerank_score")
        if score is None:
            score = project.get("rrf_score")
        candidates.append(ExternalTechCandidate(
            doc_id=doc_id, title=project.get("project_title") or pid,
            provider=project.get("organization"), relevance_score=score if score is not None else 0.0,
            relation_summary="", tech_elements=tech_by_project[pid],
            evidences=[ev for tech in tech_by_project[pid] for ev in tech.evidences],
            hits=[hit], extra={"project_id": pid, "metadata": project.get("metadata", {})},
        ))
    return ModuleResult(
        module="ntis", query=structured.get("search_query") or query,
        candidates=candidates, tech_elements=all_elements, hits=hits,
        stats={
            "candidate_count": len(candidates), "technology_element_count": len(all_elements),
            "verified_evidence_count": sum(ev.verified for c in candidates for ev in c.evidences),
            "generation_implemented": True, "prior_rd_axes": result.get("prior_rd_axes", []),
        },
        extra=dict(result),
    )


def adapt_ntis_to_module_result(result):
    """기존 dict 호출부를 유지하되 실제 공통 스키마 검증을 적용합니다."""
    return to_module_result(result).model_dump(mode="json")


def align_ntis_to_a_schema(ntis_result, raw_result):
    """기존 2단계 변환 호출과 호환되는 진입점. 원본에서 직접 변환합니다."""
    return adapt_ntis_to_module_result(raw_result)
