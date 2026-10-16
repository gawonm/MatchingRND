"""
생성기: 검색 결과 → (문서 전체를 LLM 에) → 문서별 매칭 판정 → 인용·관련성 검증 → `ModuleResult` 정리.

흐름
----
    search(ModuleResult)                                    ← B 로 검색한 후보 (생성 필드는 비어 있음)
        │  상위 judge_docs 기술의 **문서 전체**를 프롬프트에
        ▼
    LLM → LLMAnswer(verdict, answer, matches[doc_id, matched_target, level, reason, quote], tech_elements, gaps)
        │  코드가 모든 인용을 원문과 대조 (validation.py) + B 와의 분야 고유 표현 겹침 검사 (relevance.py)
        ▼
    통과한 매칭(same/similar)의 문서만 ──▶ result.candidates 에 남기고 evidences / tech_elements / relation_summary 를 채운다
    탈락한 문서(none)는 candidates 에서 빼고 GenerationResult.dropped_doc_ids 와 stats["match"]["none"] 에, 실패한 인용은 references 에 ok=False 로 남긴다

판정은 코드가 정한다
------------------
최종 verdict 는 LLM 의 말이 아니라 검증을 통과한 매칭으로 정한다:
same 이 있으면 same, similar 만 있으면 similar, 하나도 없으면 none(= has_match False).
`search.hits` 는 검색 결과의 기록이므로 걸러내지 않는다.

공용 계약(`ModuleResult`, `Evidence`, `TechElement`)은 바꾸지 않고 기존 필드를 채우기만 한다.
"""

from __future__ import annotations

import hashlib
from typing import Mapping

from app.common.schemas import BBox, Evidence, ModuleResult, TechElement
from app.technology_rag.schemas import TechDocument
from app.technology_rag.text import compact
from app.technology_rag.config import LLMConfig
from app.technology_rag.generation.llm import LLMClient
from app.technology_rag.generation.prompt import build_messages
from app.technology_rag.generation.relevance import term_overlap
from app.technology_rag.generation.schemas import (
    AnswerQuote,
    GenerationResult,
    LLMAnswer,
    TechInput,
    Usage,
    VerifiedElement,
    VerifiedReference,
)
from app.technology_rag.generation.validation import (
    QuoteCheck,
    check_anywhere,
    check_quote,
    find_prose_quotes,
)

REASON_OFF_TOPIC = "분야 고유 표현 불일치"
REASON_NOT_APPLICABLE = "B의 적용 대상에 적용 불가"
REASON_NOT_MATCHED = "매칭되지 않은 문서"
ROLE = {"same": "직접 해결", "similar": "부분 관련"}
LEVEL_TAG = {"same": "same", "similar": "similar"}
REASON_LLM_SKIPPED = "LLM 미선택(B와 관련 없음)"
REASON_VERIFY_FAILED = "검증 탈락"


def _evidence(doc: TechDocument, quote: str, check: QuoteCheck) -> Evidence:
    """검증을 통과한 인용 → 공용 `Evidence`. 검증을 통과한 것만 `verified=True` 로 만든다."""
    return Evidence(
        doc_id=doc.doc_id,
        source=doc.source,
        section=check.section or None,
        page=check.page,
        bbox=BBox(x0=check.bbox[0], y0=check.bbox[1], x1=check.bbox[2], y1=check.bbox[3]) if check.bbox else None,
        quote=quote,
        verified=True,
    )


def _element_id(name: str) -> str:
    return "te-" + hashlib.sha1(compact(name).lower().encode("utf-8")).hexdigest()[:10]


class Generator:
    def __init__(self, config: LLMConfig, llm: LLMClient | None = None) -> None:
        self.config = config
        self.llm = llm or LLMClient(config)

    # ------------------------------------------------------------------
    def run(
        self,
        inp: TechInput,
        search: ModuleResult,
        documents: Mapping[str, TechDocument],
        *,
        dry_run: bool = False,
        n_docs: int | None = None,
    ) -> GenerationResult:
        """`n_docs` 를 주면 설정값(`llm.judge_docs`) 대신 이번 호출에만 그 수를 판정한다 (설정 객체는 바뀌지 않는다).

        `inp` 는 상류에서 이미 나뉘어 온 보유기술(A)·원하는 기술(B)이다. 판정은 B 에 대해서만 한다.
        """
        if not documents:
            raise RuntimeError("문서(TechDocument)가 로드되지 않았습니다. from_config(load_documents=True) 로 만드세요.")

        top = search.candidates[: (n_docs or self.config.judge_docs)]
        provided = {c.doc_id: documents[c.doc_id] for c in top}
        rank = {c.doc_id: i for i, c in enumerate(top, 1)}
        messages = build_messages(inp, list(provided.values()))

        if dry_run:
            return GenerationResult(
                result=search, answer="", llm_verdict="none", verdict="none",
                provided_doc_ids=list(provided), dry_run=True, messages=messages,
                tech_input=inp, retrieval_query=str(search.stats.get("retrieval_query", "")),
            )

        ans, usage = self.llm.ask(messages)
        return self._assemble(search, ans, usage, provided, rank, inp)

    # ------------------------------------------------------------------
    def _assemble(
        self,
        search: ModuleResult,
        ans: LLMAnswer,
        usage: Usage,
        provided: dict[str, TechDocument],
        rank: dict[str, int],
        inp: TechInput,
    ) -> GenerationResult:
        retrieval_query = str(search.stats.get("retrieval_query", ""))

        # ---- 1) 검증: 인용이 원문에 있는가 + B 와 분야 고유 표현이 겹치는가 ----
        b_terms = [*inp.targets, *inp.search_terms]
        min_overlap = self.config.min_term_overlap
        refs: list[VerifiedReference] = []

        def resolve_target(value: str) -> str | None:
            if len(inp.targets) == 1:
                return inp.targets[0]
            return value if value in inp.targets else None

        ref_checks: list[QuoteCheck] = []
        for m in ans.matches:
            c = check_quote(provided, m.doc_id, m.quote)
            ref_checks.append(c)
            ok, reason = c.ok, c.reason
            doc = provided.get(m.doc_id)
            if ok and not m.applicable_to_target:
                ok, reason = False, REASON_NOT_APPLICABLE
            if ok and b_terms and min_overlap > 0 and doc is not None:
                if term_overlap(b_terms, [doc.title, m.quote]) < min_overlap:
                    ok, reason = False, REASON_OFF_TOPIC
            refs.append(VerifiedReference(
                doc_id=m.doc_id, role=ROLE[m.level], why=m.reason, difference=m.difference, quote=m.quote, ok=ok, reason=reason,
                level=m.level, matched_target=resolve_target(m.matched_target),
                section=c.section, page=c.page, bbox=c.bbox, search_rank=rank.get(m.doc_id)))

        # 문서별 최종 level: 검증을 통과한 매칭 중 가장 높은 것
        level_of: dict[str, str] = {}
        for r in refs:
            if r.ok and level_of.get(r.doc_id) != "same":
                level_of[r.doc_id] = r.level or "similar"
        matched = sorted(level_of, key=lambda d: (level_of[d] != "same", rank.get(d, 10**6)))

        elems: list[VerifiedElement] = []
        elem_checks: list[QuoteCheck] = []
        for e in ans.tech_elements:
            c = check_quote(provided, e.source_doc_id, e.quote)
            elem_checks.append(c)
            in_match = e.source_doc_id in level_of
            elems.append(VerifiedElement(
                name=e.name, function=e.function, source_doc_id=e.source_doc_id, quote=e.quote,
                ok=c.ok and in_match, reason=c.reason if in_match else REASON_NOT_MATCHED,
                section=c.section, page=c.page, bbox=c.bbox))

        prose: list[AnswerQuote] = []
        for q in find_prose_quotes(ans.answer):
            c, found_in = check_anywhere(provided, q)
            prose.append(AnswerQuote(text=q, ok=c.ok, doc_id=found_in))

        n_ok = sum(r.ok for r in refs)
        verdict = ("same" if "same" in level_of.values()
                   else "similar" if level_of else "none")
        note = f"LLM 판정 '{ans.verdict}' → 검증을 통과한 매칭 기준 '{verdict}'" if verdict != ans.verdict else ""

        # ---- 2) 매칭된 문서만 candidates 에 남기고 빈 필드를 채운다 (hits 는 검색 기록이므로 그대로 둔다) ----
        result = search.model_copy(deep=True)
        by_id = {c.doc_id: c for c in result.candidates}
        kept = [by_id[d] for d in matched if d in by_id]
        all_elements: list[TechElement] = []
        for cand in kept:
            doc = provided[cand.doc_id]
            whys: list[str] = []
            for r, c in zip(refs, ref_checks):
                if r.ok and r.doc_id == cand.doc_id:
                    cand.evidences.append(_evidence(doc, r.quote, c))
                    whys.append(r.why)
            for e, c in zip(ans.tech_elements, elem_checks):
                if c.ok and e.source_doc_id == cand.doc_id:
                    ev = _evidence(doc, e.quote, c)
                    te = TechElement(
                        element_id=_element_id(e.name), name=e.name, surface_forms=[e.name],
                        function=e.function, origin=doc.source, evidences=[ev],
                        # confidence: LLM 이 신뢰도를 주지 않으므로 채우지 않는다 (기본 0.0 = 미산정)
                    )
                    cand.tech_elements.append(te)
                    all_elements.append(te)
            cand.relation_summary = f"[{LEVEL_TAG[level_of[cand.doc_id]]}] " + " / ".join(whys)
            best = next((r for r in refs if r.ok and r.doc_id == cand.doc_id and r.level == level_of[cand.doc_id]), None)
            cand.extra["match_level"] = level_of[cand.doc_id]          # same | similar (none 은 candidates 에 남지 않는다)
            cand.extra["matched_target"] = best.matched_target if best else None
        result.candidates = kept
        dropped = [d for d in provided if d not in level_of]

        result.tech_elements = all_elements
        result.stats["generation_implemented"] = True
        # 하위 모듈(Gap 등)이 ModuleResult 만으로 B 매칭 결과를 구조적으로 읽을 수 있게 한다.
        judged = {j.doc_id: j for j in ans.judgments}
        none_items = []
        for d in dropped:
            failed = next((r for r in refs if r.doc_id == d and not r.ok), None)
            none_items.append({
                "doc_id": d, "title": by_id[d].title if d in by_id else None, "level": "none",
                "reason": f"{REASON_VERIFY_FAILED}: {failed.reason}" if failed
                          else f"{REASON_LLM_SKIPPED}: {judged[d].reason}" if d in judged else REASON_LLM_SKIPPED,
            })
        result.stats["match"] = {
            "has_match": bool(matched),
            "verdict": verdict,
            "targets": list(inp.targets),
            "items": [{"doc_id": d, "level": level_of[d], "title": by_id[d].title,
                       "matched_target": next((r.matched_target for r in refs
                                               if r.ok and r.doc_id == d and r.level == level_of[d]), None)}
                      for d in matched if d in by_id],
            # none: 판정했으나 매칭되지 않은 문서와 사유 (LLM 이 고르지 않음 / LLM 은 골랐으나 코드 검증에서 탈락)
            "none": none_items,
            "dropped": dropped,
            # 문서별 LLM 판정 기록. 판정은 same/similar 인데 matches 에 없어 버려진 문서는 unlisted 로 따로 남긴다.
            "judgments": [{"doc_id": j.doc_id, "level": j.level, "reason": j.reason} for j in ans.judgments],
            "unlisted": [j.doc_id for j in ans.judgments if j.level != "none" and j.doc_id not in {m.doc_id for m in ans.matches}],
            "dropped_titles": [{"doc_id": d, "title": by_id[d].title if d in by_id else None} for d in dropped],
            # LLM 은 매칭이라 했지만 코드 검증에서 탈락한 것과 그 이유 (LLM 이 아예 고르지 않은 문서는 이유가 없다)
            "rejected": [{"doc_id": r.doc_id, "level": r.level, "reason": r.reason}
                         for r in refs if not r.ok and r.doc_id not in level_of],
        }
        result.stats["generation"] = {
            "model": usage.model, "verdict": verdict, "llm_verdict": ans.verdict,
            "n_judged": len(provided), "n_matched": len(matched), "n_dropped": len(dropped),
            "n_refs": len(refs), "n_verified": n_ok, "cost_usd": usage.cost_usd,
        }

        return GenerationResult(
            result=result, answer=ans.answer, llm_verdict=ans.verdict, verdict=verdict, downgrade_note=note,
            gaps=list(ans.gaps), references=refs, tech_elements=elems, answer_quotes=prose,
            provided_doc_ids=list(provided), n_verified=n_ok,
            unsupported_rate=(1 - n_ok / len(refs)) if refs else 0.0, usage=usage,
            has_match=bool(matched), tech_input=inp, retrieval_query=retrieval_query,
            dropped_doc_ids=dropped,
        )
