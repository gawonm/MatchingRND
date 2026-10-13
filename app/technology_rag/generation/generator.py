"""
생성기: 검색 결과 → (문서 전체를 LLM 에) → 답변 → 인용 검증 → `ModuleResult` 의 빈 필드 채우기.

흐름
----
    search(ModuleResult)                                    ← 검색이 만든 후보 (생성 필드는 비어 있음)
        │  상위 n_docs 기술의 **문서 전체**를 프롬프트에
        ▼
    LLM → LLMAnswer(verdict, answer, tech_elements, references, gaps)
        │  코드가 모든 인용을 원문과 대조 (validation.py)
        ▼
    검증 통과분만 ──▶ candidates[].evidences / tech_elements / relation_summary
    검증 실패분은 ──▶ GenerationResult.references 에 ok=False 로 남겨 투명하게 보여준다

판정 강등
---------
LLM 이 "답이 있다(answerable/partial)"고 했는데 **검증된 참고문헌이 하나도 없으면** 최종 판정을
`no_answer`(근거부족)로 내린다. 근거 없는 답을 사용자에게 확정적으로 보여주지 않기 위해서다.

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
from app.technology_rag.generation.schemas import (
    AnswerQuote,
    GenerationResult,
    LLMAnswer,
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
        query: str,
        search: ModuleResult,
        documents: Mapping[str, TechDocument],
        *,
        dry_run: bool = False,
        n_docs: int | None = None,
    ) -> GenerationResult:
        """`n_docs` 를 주면 설정값(`llm.n_docs`) 대신 이번 호출에만 그 수를 쓴다 (설정 객체는 바뀌지 않는다)."""
        if not documents:
            raise RuntimeError("문서(TechDocument)가 로드되지 않았습니다. from_config(load_documents=True) 로 만드세요.")

        top = search.candidates[: (n_docs or self.config.n_docs)]
        provided = {c.doc_id: documents[c.doc_id] for c in top}
        rank = {c.doc_id: i for i, c in enumerate(top, 1)}
        messages = build_messages(query, list(provided.values()))

        if dry_run:
            return GenerationResult(
                result=search, answer="", llm_verdict="no_answer", verdict="no_answer",
                provided_doc_ids=list(provided), dry_run=True, messages=messages,
            )

        ans, usage = self.llm.ask(messages)
        return self._assemble(search, ans, usage, provided, rank)

    # ------------------------------------------------------------------
    def _assemble(
        self,
        search: ModuleResult,
        ans: LLMAnswer,
        usage: Usage,
        provided: dict[str, TechDocument],
        rank: dict[str, int],
    ) -> GenerationResult:
        # ---- 1) 검증 ----
        refs: list[VerifiedReference] = []
        ref_checks: list[QuoteCheck] = []
        for r in ans.references:
            c = check_quote(provided, r.doc_id, r.quote)
            ref_checks.append(c)
            refs.append(VerifiedReference(
                doc_id=r.doc_id, role=r.role, why=r.why, quote=r.quote, ok=c.ok, reason=c.reason,
                section=c.section, page=c.page, bbox=c.bbox, search_rank=rank.get(r.doc_id)))

        elems: list[VerifiedElement] = []
        elem_checks: list[QuoteCheck] = []
        for e in ans.tech_elements:
            c = check_quote(provided, e.source_doc_id, e.quote)
            elem_checks.append(c)
            elems.append(VerifiedElement(
                name=e.name, function=e.function, source_doc_id=e.source_doc_id, quote=e.quote,
                ok=c.ok, reason=c.reason, section=c.section, page=c.page, bbox=c.bbox))

        prose: list[AnswerQuote] = []
        for q in find_prose_quotes(ans.answer):
            c, found_in = check_anywhere(provided, q)
            prose.append(AnswerQuote(text=q, ok=c.ok, doc_id=found_in))

        n_ok = sum(r.ok for r in refs)
        verdict, note = ans.verdict, ""
        if ans.verdict != "no_answer" and n_ok == 0:
            verdict, note = "no_answer", "검증된 근거가 없어 '근거부족'으로 강등"

        # ---- 2) 검증 통과분만 ModuleResult 의 빈 필드에 채운다 ----
        result = search.model_copy(deep=True)
        all_elements: list[TechElement] = []
        for cand in result.candidates:
            doc = provided.get(cand.doc_id)
            if doc is None:
                continue                                   # n_docs 밖의 후보는 생성하지 않았다
            whys: list[str] = []
            for r, c in zip(ans.references, ref_checks):
                if c.ok and r.doc_id == cand.doc_id:
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
            cand.relation_summary = " / ".join(whys)       # 검증된 인용이 없는 문서는 비워 둔다

        result.tech_elements = all_elements
        result.stats["generation_implemented"] = True
        result.stats["generation"] = {
            "model": usage.model, "verdict": verdict, "llm_verdict": ans.verdict,
            "n_provided": len(provided), "n_refs": len(refs), "n_verified": n_ok,
            "cost_usd": usage.cost_usd,
        }

        return GenerationResult(
            result=result, answer=ans.answer, llm_verdict=ans.verdict, verdict=verdict, downgrade_note=note,
            gaps=list(ans.gaps), references=refs, tech_elements=elems, answer_quotes=prose,
            provided_doc_ids=list(provided), n_verified=n_ok,
            unsupported_rate=(1 - n_ok / len(refs)) if refs else 0.0, usage=usage,
        )
