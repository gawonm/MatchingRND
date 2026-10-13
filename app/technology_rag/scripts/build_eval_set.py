r"""
평가셋 조립/검증:  queries_source.jsonl + judgments.jsonl (+ pool_candidates.jsonl)  →  tech_queries.jsonl

실행:
    .venv\Scripts\python.exe -X utf8 -m app.technology_rag.scripts.build_eval_set

하는 일
-------
1. 정답 문서가 실제 존재하는지, 근거 문장(contains)이 문서의 해당 섹션에서 정확히 한 블록으로 해석되는지 확인하고
   근거 블록의 (섹션, 블록 인덱스, 페이지, bbox, quote)를 문서에서 직접 복사한다 (손으로 옮겨 적은 오타 방지).
2. 쿼리와 정답 문서의 어휘 겹침(lexical overlap)을 측정한다. 겹침이 크면 BM25 에 유리한 쿼리다.
3. 쿼리별 expected_verdict 를 판정에서 도출한다.
       grade 2 문서가 있으면 "answerable", 없고 grade 1 만 있으면 "partial", 둘 다 없으면 "no_answer"
4. dev / test 를 층화 분할한다 (튜닝은 dev 에서만, 보고는 test 에서만).
5. 스키마·일관성 검증. 위반이 있으면 종료코드 1.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

from app.technology_rag.paths import PROJECT_ROOT
from app.technology_rag.schemas import SectionCode, TechDocument
from app.technology_rag.text import compact
from app.technology_rag.indexing.tokenizer import default_tokenizer

ROOT = PROJECT_ROOT   # app.technology_rag.paths — TECHRAG_ROOT 로 바꿀 수 있다
EVAL = ROOT / "data" / "evaluation"
DOCS = ROOT / "data" / "processed" / "tech_documents.jsonl"


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def resolve_evidence(doc: TechDocument, section: str, contains: str) -> dict:
    """문서의 section 에서 contains 를 포함하는 블록을 정확히 하나 찾아 근거 레코드를 만든다."""
    sec = doc.section(SectionCode(section))
    hits = [(i, b) for i, b in enumerate(sec.blocks) if contains in b.text]
    if len(hits) != 1:
        raise ValueError(f"{doc.doc_id}/{section}: {contains!r} 가 {len(hits)}개 블록에서 발견됨 (정확히 1개여야 함)")
    i, b = hits[0]
    return {
        "doc_id": doc.doc_id, "section": section, "block_index": i, "page": b.page,
        "bbox": [round(v, 1) for v in b.bbox.as_tuple()], "quote": b.text,
    }


def overlap_stats(tok, query: str, doc: TechDocument) -> dict:
    """쿼리 토큰 중 정답 문서 본문에 그대로 나오는 비율, 그리고 쿼리 문장 조각이 문서에 그대로 있는 정도."""
    q = set(tok(query))
    d = set(tok(doc.full_text))
    token_overlap = len(q & d) / len(q) if q else 0.0
    # 쿼리를 6글자 조각으로 잘랐을 때 문서에 (공백 제거 후) 그대로 존재하는 비율 → 문장 베끼기 탐지
    qc, dc = compact(query), compact(doc.full_text)
    grams = {qc[i:i + 6] for i in range(max(0, len(qc) - 5))}
    verbatim = sum(1 for g in grams if g in dc) / len(grams) if grams else 0.0
    return {"token_overlap": round(token_overlap, 3), "verbatim_6gram": round(verbatim, 3)}


def assign_split(rows: list[dict], dev_ratio: float = 1 / 3) -> None:
    """유형별로 정렬 후 해시 순서로 dev 비율만큼 뽑는다 (재현 가능, 유형 분포 유지)."""
    by_type = collections.defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
    for t, rs in by_type.items():
        rs.sort(key=lambda r: hashlib.sha1(("split|" + r["query_id"]).encode()).hexdigest())
        n_dev = max(1, round(len(rs) * dev_ratio)) if len(rs) >= 3 else 0
        for i, r in enumerate(rs):
            r["split"] = "dev" if i < n_dev else "test"


def main() -> int:
    docs = {d.doc_id: d for d in (TechDocument.model_validate_json(l) for l in DOCS.open(encoding="utf-8") if l.strip())}
    queries = read_jsonl(EVAL / "queries_source.jsonl")
    judg = {j["query_id"]: j for j in read_jsonl(EVAL / "judgments.jsonl")}
    pool = {p["query_id"]: p for p in read_jsonl(EVAL / "pool_candidates.jsonl")}
    # 사람 검수 기록(03 노트북이 추가). 쿼리별 마지막 기록만 유효하다. 없으면 모두 draft.
    review_path = EVAL / "review_log.jsonl"
    review = {r["query_id"]: r for r in read_jsonl(review_path)} if review_path.exists() else {}
    tok = default_tokenizer()

    problems: list[str] = []
    rows: list[dict] = []
    for q in queries:
        qid = q["query_id"]
        j = judg.get(qid)
        if j is None:
            problems.append(f"{qid}: 판정 없음")
            continue
        grades = j["grades"]
        pooled = {c["doc_id"] for c in pool[qid]["candidates"]}

        for d in grades:
            if d not in docs:
                problems.append(f"{qid}: 존재하지 않는 doc_id {d}")
            if d not in pooled:
                problems.append(f"{qid}: {d} 는 pooling 후보가 아니었다(판정 근거 없음)")
        if q["source_doc_id"] and grades.get(q["source_doc_id"]) != 2:
            problems.append(f"{qid}: 출처 문서 {q['source_doc_id']} 가 2점이 아니다")

        specs = list(q["evidence"]) + [e for e in j.get("extra_evidence", [])]
        evidence = []
        for e in specs:
            doc_id = e.get("doc_id", q["source_doc_id"])
            try:
                evidence.append(resolve_evidence(docs[doc_id], e["section"], e["contains"]))
            except Exception as ex:  # noqa: BLE001
                problems.append(f"{qid}: 근거 해석 실패 - {ex}")
        covered = {e["doc_id"] for e in evidence}
        for d, g in grades.items():
            if g == 2 and d not in covered:
                problems.append(f"{qid}: 2점 문서 {d} 에 근거(evidence)가 없다")

        relevant = [{"doc_id": d, "grade": g} for d, g in sorted(grades.items(), key=lambda kv: (-kv[1], kv[0]))]
        verdict = "answerable" if 2 in grades.values() else ("partial" if 1 in grades.values() else "no_answer")
        expect_by_type = {"problem": "answerable", "keyword": "answerable", "no_answer": "no_answer"}
        if q["type"] in expect_by_type and verdict != expect_by_type[q["type"]]:
            problems.append(f"{qid}: type={q['type']} 인데 판정 결과는 {verdict}")

        ov = overlap_stats(tok, q["query"], docs[q["source_doc_id"]]) if q["source_doc_id"] else None
        rows.append({
            "query_id": qid, "query": q["query"], "type": q["type"], "expected_verdict": verdict,
            "source_doc_id": q["source_doc_id"], "relevant": relevant, "gold_evidence": evidence,
            "overlap": ov, "judged_pool_size": len(pooled), "note": j.get("note", ""),
            "status": ("reviewed" if review[qid]["ok"] else "needs_fix") if qid in review else "draft",
            "review_comment": review[qid].get("comment", "") if qid in review else "",
            "label_source": "LLM(Claude) 작성·판정" + (", 사람 검수 완료" if qid in review and review[qid]["ok"] else ", 사람 검수 전"),
        })

    assign_split(rows)
    rows.sort(key=lambda r: r["query_id"])

    ids = [r["query_id"] for r in rows]
    if len(ids) != len(set(ids)):
        problems.append("query_id 중복")
    if len({r["query"] for r in rows}) != len(rows):
        problems.append("쿼리 문장 중복")

    out = EVAL / "tech_queries.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---------------- 요약 ----------------
    print(f"저장: {out.relative_to(ROOT)}  ({len(rows)}개 쿼리)")
    print("\n[유형 × 분할]")
    tab = collections.Counter((r["type"], r["split"]) for r in rows)
    for t in ("problem", "keyword", "no_answer", "scenario"):
        print(f"  {t:<10} dev={tab[(t, 'dev')]:>2}  test={tab[(t, 'test')]:>2}")
    print("[검수 상태]", dict(collections.Counter(r["status"] for r in rows)))
    print("\n[기대 판정]", dict(collections.Counter(r["expected_verdict"] for r in rows)))
    g = collections.Counter(x["grade"] for r in rows for x in r["relevant"])
    print("[관련 문서 수] 2점:", g[2], " 1점:", g[1], f" (쿼리당 평균 2점 {g[2] / len(rows):.2f})")
    multi = [r["query_id"] for r in rows if sum(1 for x in r["relevant"] if x["grade"] == 2) > 1]
    print("[2점 문서가 여럿인 쿼리]", multi)
    print("\n[어휘 겹침] (출처 문서 기준) 유형별 평균")
    for t in ("problem", "keyword"):
        ov = [r["overlap"] for r in rows if r["type"] == t and r["overlap"]]
        if ov:
            print(f"  {t:<8} 토큰 겹침 {sum(o['token_overlap'] for o in ov) / len(ov):.2f}   "
                  f"6글자 조각 일치 {sum(o['verbatim_6gram'] for o in ov) / len(ov):.2f}   "
                  f"(최대 {max(o['verbatim_6gram'] for o in ov):.2f})")
    hi = [(r["query_id"], r["overlap"]["verbatim_6gram"]) for r in rows if r["type"] == "problem" and r["overlap"]["verbatim_6gram"] > 0.25]
    print("  문서 문장 베낌 의심(problem, 6글자 일치>0.25):", hi or "없음")

    print("\n" + "=" * 70)
    if problems:
        print(f"❌ 검증 위반 {len(problems)}건")
        for p in problems:
            print("  -", p)
        return 1
    print("✅ 검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
