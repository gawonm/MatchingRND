"""run_ntis_pipeline 결과 → 공용(A 스키마) ModuleResult 변환 (2단계).

노트북 f71b1843, dd5e305b 셀의 함수를 그대로 옮긴 것이다.
"""
from collections import defaultdict


def adapt_ntis_to_module_result(result):
    projects = result["related_projects"]
    canonical_rows = result["canonical_technologies"]

    project_map = {
        str(p["project_id"]): p
        for p in projects
    }

    # 과제별 기술요소 및 Evidence 구성
    tech_by_project = defaultdict(list)
    all_elements = []

    for row in canonical_rows:
        pid = str(row["project_id"])
        project = project_map.get(pid)
        if project is None:
            continue

        quote = row.get("evidence") or ""
        source_text = project.get("text") or ""

        evidence = {
            "doc_id": f"ntis-{pid}",
            "source": "ntis",
            "quote": quote,
            "verified": bool(quote and quote in source_text),
        }

        element = {
            "name": row["canonical_name"],
            "original_name": row["original_element"],
            "function": None,  # 기존 결과에 별도 기능 설명 없음
            "doc_id": f"ntis-{pid}",
            "evidences": [evidence],
        }

        tech_by_project[pid].append(element)
        all_elements.append(element)

    # 과제별 Candidate
    candidates = []

    for p in projects:
        pid = str(p["project_id"])

        candidate = {
            "doc_id": f"ntis-{pid}",
            "title": p["project_title"],
            "provider": p.get("organization"),
            "relevance_score": p.get("rerank_score"),
            "tech_elements": tech_by_project[pid],
            "evidences": [
                ev
                for tech in tech_by_project[pid]
                for ev in tech["evidences"]
            ],
            "metadata": {
                "project_id": pid,
                "rank": p.get("rank"),
                "rrf_score": p.get("rrf_score"),
                "source_ranks": p.get("source_ranks"),
            },
        }

        candidates.append(candidate)

    # 공용 출력 초안
    return {
        "module": "ntis",
        "query": result["query"],
        "query_expansion": [],
        "candidates": candidates,
        "tech_elements": all_elements,
        "hits": [],
        "stats": {
            "candidate_count": len(candidates),
            "technology_element_count": len(all_elements),
            "verified_evidence_count": sum(
                ev["verified"]
                for c in candidates
                for ev in c["evidences"]
            ),
        },
        # NTIS 전용 확장 필드
        "extensions": {
            "prior_rd_axes": result["prior_rd_axes"],
        },
    }


def align_ntis_to_a_schema(ntis_result, raw_result):
    # A의 query는 자연어 문자열
    query = raw_result["query"]
    if isinstance(query, dict):
        query = (
            query.get("problem")
            or query.get("original_query")
            or query.get("query")
        )
    if not isinstance(query, str):
        raise ValueError("원본 자연어 query 필드를 확인해야 합니다.")

    def convert_evidence(ev):
        return {
            "doc_id": ev["doc_id"],
            "source": ev["source"],
            "section": None,
            "page": None,
            "bbox": None,
            "quote": ev["quote"],
            "verified": ev["verified"],
        }

    def convert_element(tech):
        return {
            "name": tech["name"],
            "function": tech.get("function"),
            "origin": "ntis",
            "evidences": [
                convert_evidence(ev)
                for ev in tech["evidences"]
            ],
        }

    candidates = []

    for c in ntis_result["candidates"]:
        candidates.append({
            "doc_id": c["doc_id"],
            "title": c["title"],
            "provider": c["provider"],
            "relevance_score": c["relevance_score"],
            "relation_summary": "",
            "tech_elements": [
                convert_element(t)
                for t in c["tech_elements"]
            ],
            "evidences": [
                convert_evidence(ev)
                for ev in c["evidences"]
            ],
            "hits": [],
        })

    return {
        "module": "ntis",
        "query": query,
        "query_expansion": [],
        "candidates": candidates,
        "tech_elements": [
            convert_element(t)
            for t in ntis_result["tech_elements"]
        ],
        "hits": [],
        "stats": {
            **ntis_result["stats"],
            "generation_implemented": True,
            "prior_rd_axes": raw_result["prior_rd_axes"],
        },
    }
