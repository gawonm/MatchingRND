"""Convert PDF retriever results to the shared contract without rebuilding indexes."""
from __future__ import annotations

from collections import defaultdict
from typing import Literal

from app.common.schemas import BBox, Evidence, ExternalTechCandidate, ModuleResult, RetrievalHit


def adapt_pdf_result(result: dict, index: dict, module: Literal["rfp", "policy"]) -> ModuleResult:
    if module not in {"rfp", "policy"}:
        raise ValueError("PDF module must be rfp or policy")
    chunks = index["chunks_by_id"]
    group_key = "task_id" if module == "rfp" else "article_id"
    hits = []
    hits_by_group = defaultdict(list)
    for row in result["ranking"]:
        document = chunks[row["chunk_id"]]
        metadata = document.metadata
        hit = RetrievalHit(
            chunk_id=row["chunk_id"], doc_id=row["document_id"], source=module,
            section_key=metadata.get("item") or metadata.get("article_number"),
            text=document.page_content, bm25_rank=row.get("keyword_rank"),
            dense_rank=row.get("vector_rank"), rrf_score=row.get("rrf_score"),
            rerank_score=row.get("reranker_score"), final_rank=row["rank"],
            retriever="hybrid_rerank" if row.get("reranker_score") is not None else "hybrid",
            extra=dict(row),
        )
        hits.append(hit)
        hits_by_group[metadata[group_key]].append(hit)

    evidence_by_group = defaultdict(list)
    for source in result["sources"]:
        # PDF modules use 1-based physical pages; common Evidence uses 0-based.
        locations = source.get("source_locations", [])
        # Do not associate a multi-page quote with only its first block.
        location = locations[0] if len(locations) == 1 else {}
        quote = source["text"]
        original = chunks[source["chunk_id"]].metadata.get("original_text")
        if original is None:
            original = chunks[source["chunk_id"]].page_content
        bbox = location.get("bbox")
        evidence_by_group[source[group_key]].append(Evidence(
            doc_id=source["document_id"], source=module,
            section=source.get("item") or source.get("article_number"),
            page=location["page"] - 1 if location.get("page") is not None else None,
            bbox=BBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]) if bbox else None,
            quote=quote, verified=bool(quote and quote in original),
            extra={**source, "source_page_base": 1},
        ))

    candidates = []
    for row in result["hits"]:
        score = row.get("reranker_score")
        if score is None:
            score = row.get("rrf_score")
        title = row["title"] if module == "rfp" else " ".join(
            value for value in (row["law_name"], row["article_number"], row.get("article_title")) if value
        )
        candidates.append(ExternalTechCandidate(
            doc_id=row["document_id"], title=title,
            relevance_score=score if score is not None else 0.0, relation_summary="",
            evidences=evidence_by_group[row[group_key]], hits=hits_by_group[row[group_key]],
            extra=dict(row),
        ))
    details = result.get("query_details") or {}
    expansion = [row["technology"] for row in details.get("expansion_sources", [])]
    expansion.extend(details.get("unmet_elements", []))
    return ModuleResult(
        module=module, query=result["question"], query_expansion=list(dict.fromkeys(expansion)),
        candidates=candidates, hits=hits,
        stats={
            "candidate_count": len(candidates), "hit_count": len(hits),
            "status": result["status"], "context_truncated": result["context_truncated"],
            "generation_implemented": False,
            "verified_evidence_count": sum(ev.verified for c in candidates for ev in c.evidences),
        },
        extra=dict(result),
    )
