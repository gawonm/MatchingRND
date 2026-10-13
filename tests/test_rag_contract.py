"""Contract checks use in-memory search results, with no model/API downloads."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.common.adapters import adapt_pdf_result
from app.common.schemas import ModuleResult
from app.ntis_rag.adapter import adapt_ntis_to_module_result, align_ntis_to_a_schema, to_module_result
from app.policy_rag import law_rag
from app.rfp_rag import rfp_rag


def pdf_fixture(module):
    group = "task_id" if module == "rfp" else "article_id"
    metadata = {group: "unit-1", "document_id": "doc-1", "original_text": "원문 근거",
                "item": "개발목표"} if module == "rfp" else {
        group: "unit-1", "document_id": "doc-1", "original_text": "원문 근거", "article_number": "제1조"}
    index = {"chunks_by_id": {"chunk-1": SimpleNamespace(metadata=metadata, page_content="제목\n원문 근거")}}
    row = {group: "unit-1", "chunk_id": "chunk-1", "document_id": "doc-1", "rank": 1,
           "keyword_rank": 2, "vector_rank": 1, "rrf_score": 0.03, "reranker_score": 0.0}
    candidate = {**row, "title": "과제명", "law_name": "법령명", "article_number": "제1조", "article_title": "목적"}
    source = {**row, "text": "원문 근거", "source": "원본.pdf", "pages": [1],
              "source_locations": [{"page": 1, "bbox": [1, 2, 3, 4]}]}
    result = {"question": "질문", "ranking": [row], "hits": [candidate], "sources": [source],
              "context": "원문 근거", "status": "ok", "context_truncated": False,
              "diagnostics": {"failed_files": []}, "result_type": "institutional_reference" if module == "policy" else "technical_candidate"}
    return result, index


def ntis_fixture():
    return {
        "query": {"original_query": "질문", "structured_query": {"search_query": "확장 질문"}},
        "related_projects": [{"project_id": 7, "project_title": "과제", "text": "원문 근거",
                              "rank": 1, "rerank_score": 0.0, "rrf_score": 0.03,
                              "source_ranks": {"dense": 1, "bm25": 2}, "metadata": {"year": 2026}}],
        "canonical_technologies": [{"project_id": 7, "canonical_name": "센서 융합",
                                    "original_element": "다중센서 융합", "evidence": "원문 근거"}],
        "prior_rd_axes": [{"axis": "센서"}],
    }


class RagContractTests(unittest.TestCase):
    def test_pdf_mapping_and_roundtrip(self):
        for module in ("rfp", "policy"):
            with self.subTest(module=module):
                raw, index = pdf_fixture(module)
                result = adapt_pdf_result(raw, index, module)
                restored = ModuleResult.model_validate_json(result.model_dump_json())
                self.assertEqual(restored.module, module)
                self.assertEqual(restored.extra, raw)
                candidate = restored.candidates[0]
                self.assertEqual(candidate.doc_id, "doc-1")
                self.assertEqual(candidate.relevance_score, 0.0)
                evidence = candidate.evidences[0]
                self.assertEqual(evidence.source.value, module)
                self.assertEqual(evidence.page, 0)
                self.assertEqual(evidence.bbox.as_tuple(), (1, 2, 3, 4))
                self.assertTrue(evidence.verified)
                self.assertEqual(candidate.hits[0].bm25_rank, 2)
                self.assertEqual(candidate.hits[0].dense_rank, 1)

    def test_pdf_multi_location_quote(self):
        raw, index = pdf_fixture("policy")
        raw["sources"][0]["source_locations"].append({"page": 2, "bbox": [5, 6, 7, 8]})
        evidence = adapt_pdf_result(raw, index, "policy").candidates[0].evidences[0]
        self.assertIsNone(evidence.page)
        self.assertIsNone(evidence.bbox)
        self.assertEqual(len(evidence.extra["source_locations"]), 2)

    def test_unverified_quote(self):
        raw, index = pdf_fixture("rfp")
        raw["sources"][0]["text"] = "원문에 없는 인용"
        self.assertFalse(adapt_pdf_result(raw, index, "rfp").candidates[0].evidences[0].verified)

    def test_empty_pdf_results(self):
        for module in ("rfp", "policy"):
            raw, index = pdf_fixture(module)
            raw.update(ranking=[], hits=[], sources=[], status="no_matches")
            result = adapt_pdf_result(raw, index, module)
            self.assertEqual(result.candidates, [])
            self.assertEqual(result.hits, [])
            self.assertEqual(result.stats["status"], "no_matches")

    def test_context_limit_preserves_candidates(self):
        raw, index = pdf_fixture("rfp")
        raw.update(sources=[], status="context_limit", context_truncated=True)
        result = adapt_pdf_result(raw, index, "rfp")
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].evidences, [])

    def test_rfp_query_expansion(self):
        raw, index = pdf_fixture("rfp")
        raw["query_details"] = {"expansion_sources": [{"technology": "센서"}, {"technology": "센서"}],
                                "unmet_elements": ["통신"]}
        self.assertEqual(adapt_pdf_result(raw, index, "rfp").query_expansion, ["센서", "통신"])

    def test_pdf_entrypoints(self):
        for module, implementation in (("rfp", rfp_rag), ("policy", law_rag)):
            raw, index = pdf_fixture(module)
            with patch.object(implementation, "search", return_value=raw) as search:
                result = implementation.search_module_result(index, "질문", top_k=2)
                self.assertIsInstance(result, ModuleResult)
                search.assert_called_once_with(index, "질문", top_k=2)

    def test_ntis_required_fields_and_compatibility(self):
        raw = ntis_fixture()
        result = to_module_result(raw)
        self.assertEqual(result.query, "확장 질문")
        self.assertEqual(result.tech_elements[0].origin.value, "ntis")
        self.assertTrue(result.tech_elements[0].element_id.startswith("te-"))
        self.assertEqual(result.tech_elements[0].surface_forms, ["다중센서 융합"])
        self.assertEqual(result.candidates[0].relevance_score, 0.0)
        self.assertEqual(result.hits[0].doc_id, "ntis-7")
        self.assertEqual(result.hits[0].bm25_rank, 2)
        self.assertTrue(result.candidates[0].evidences[0].verified)
        adapted = adapt_ntis_to_module_result(raw)
        self.assertEqual(ModuleResult.model_validate(adapted), result)
        self.assertEqual(align_ntis_to_a_schema(adapted, raw), adapted)
        self.assertEqual(ModuleResult.model_validate_json(result.model_dump_json()), result)

    def test_ntis_element_id_normalization(self):
        raw = ntis_fixture()
        first = to_module_result(raw).tech_elements[0].element_id
        raw["canonical_technologies"][0]["canonical_name"] = "센서융합"
        self.assertEqual(to_module_result(raw).tech_elements[0].element_id, first)

    def test_empty_ntis_results(self):
        raw = ntis_fixture()
        raw.update(related_projects=[], canonical_technologies=[])
        self.assertEqual(to_module_result(raw).candidates, [])


if __name__ == "__main__":
    unittest.main()
