import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.common.schemas import Evidence, ExternalTechCandidate, ModuleResult, TechElement
from app.orchestrator import AnalysisState, OrchestrationError, RagOrchestrator


def element(name, source, *, verified=True, quote="원문 근거"):
    return TechElement(
        element_id=f"te-{name}", name=name, origin=source,
        evidences=[Evidence(doc_id=f"{source}-1", source=source, quote=quote, verified=verified)],
    )


def module_result(module, elements=()):
    candidate = ExternalTechCandidate(
        doc_id=f"{module}-1", title=f"{module} 후보", relevance_score=0.5,
        relation_summary="", tech_elements=list(elements),
    )
    return ModuleResult(module=module, query="실제 검색 Query", candidates=[candidate], tech_elements=list(elements))


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.request = {"problem": "작업자와 지게차의 충돌을 줄이고 싶다.",
                        "owned_technologies": ["SLAM", "영상 인식"]}
        self.external = element("센서 융합", "pub")
        self.ntis_element = element("동적 객체 추적", "ntis")
        self.technology = Mock(return_value=SimpleNamespace(result=module_result("technology", [self.external])))
        self.ntis = Mock(return_value=module_result("ntis", [self.ntis_element]))
        self.rfp = Mock(return_value=module_result("rfp"))
        self.policy = Mock(return_value=module_result("policy"))
        self.orchestrator = RagOrchestrator(
            technology_runner=self.technology, ntis_runner=self.ntis,
            rfp_runner=self.rfp, policy_runner=self.policy,
        )

    def test_cascade_retains_input_and_evidence_provenance(self):
        result = self.orchestrator.run(self.request)
        self.ntis.assert_called_once_with(
            self.request["problem"], owned_technologies=["SLAM", "영상 인식"],
            external_technologies=["센서 융합"],
        )
        details = self.rfp.call_args.args[0]
        self.assertTrue(details["query"].startswith(details["baseline_query"]))
        self.assertIn(self.request["problem"], details["query"])
        self.assertIn("센서 융합", details["query"])
        self.assertIn("동적 객체 추적", details["query"])
        # Elements present at both module/candidate level expand only once.
        self.assertEqual(len(details["expansion_sources"]), 2)
        self.assertEqual(details["expansion_sources"][0]["source_id"], "pub-1")
        self.assertEqual(details["expansion_sources"][0]["quote"], "원문 근거")
        self.assertEqual(result.request.problem, self.request["problem"])
        self.assertEqual(AnalysisState.model_validate_json(result.model_dump_json()), result)
        self.policy.assert_not_called()

    def test_unverified_elements_do_not_expand_queries(self):
        self.technology.return_value = module_result("technology", [element("환각 기술", "pub", verified=False)])
        self.ntis.return_value = module_result("ntis", [element("근거 없는 기술", "ntis", quote="")])
        result = self.orchestrator.run(self.request)
        self.assertEqual(self.ntis.call_args.kwargs["external_technologies"], [])
        self.assertEqual(result.rfp_query_details["expansion_sources"], [])
        self.assertNotIn("환각 기술", result.queries["rfp"])
        self.assertEqual(len(result.warnings), 2)

    def test_wrong_source_is_not_used_as_external_technology(self):
        self.technology.return_value = module_result("technology", [element("법령 기술", "policy")])
        result = self.orchestrator.run(self.request)
        self.assertEqual(result.external_elements, [])

    def test_policy_runs_after_rfp_when_requested(self):
        order = []
        for name, runner in (("technology", self.technology), ("ntis", self.ntis),
                             ("rfp", self.rfp), ("policy", self.policy)):
            returned = runner.return_value
            def record(*args, _name=name, _returned=returned, **kwargs):
                order.append(_name)
                return _returned
            runner.side_effect = record
        result = self.orchestrator.run({**self.request, "policy_question": "기술이전 조건은 무엇인가?"})
        self.assertEqual(order, ["technology", "ntis", "rfp", "policy"])
        self.policy.assert_called_once_with("기술이전 조건은 무엇인가?")
        self.assertEqual(result.policy.module, "policy")

    def test_empty_results_do_not_create_gap_verdicts(self):
        for name, runner in (("technology", self.technology), ("ntis", self.ntis), ("rfp", self.rfp)):
            runner.return_value = ModuleResult(module=name, query="질문")
        result = self.orchestrator.run(self.request)
        self.assertEqual(result.rfp.candidates, [])
        self.assertEqual(result.rfp_query_details["query"], result.rfp_query_details["baseline_query"])
        self.assertEqual(result.request.unmet_elements, [])
        self.assertEqual(len(result.warnings), 5)

    def test_failure_has_stage_and_stops_later_stages(self):
        cause = FileNotFoundError("NTIS 인덱스 없음")
        self.ntis.side_effect = cause
        with self.assertRaises(OrchestrationError) as raised:
            self.orchestrator.run(self.request)
        self.assertEqual(raised.exception.stage, "ntis")
        self.assertIs(raised.exception.__cause__, cause)
        self.rfp.assert_not_called()

    def test_module_identity_validation(self):
        self.technology.return_value = module_result("ntis")
        with self.assertRaises(OrchestrationError) as raised:
            self.orchestrator.run(self.request)
        self.assertEqual(raised.exception.stage, "technology")
        self.ntis.assert_not_called()

    def test_invalid_input_is_rejected_before_execution(self):
        with self.assertRaises(ValidationError):
            self.orchestrator.run({"problem": "   ", "owned_technologies": []})
        self.technology.assert_not_called()

    def test_user_supplied_review_items_and_runner_mutation(self):
        def search(details):
            details["query"] = "덮어쓴 Query"
            return module_result("rfp")
        self.rfp.side_effect = search
        result = self.orchestrator.run({**self.request, "unmet_elements": ["실증", "실증"]})
        self.assertEqual(result.request.unmet_elements, ["실증"])
        self.assertIn("미충족 검토 요소 (기업 입력): 실증", result.queries["rfp"])
        self.assertNotEqual(result.queries["rfp"], "덮어쓴 Query")

    def test_default_pdf_index_is_reused_between_questions(self):
        from app.rfp_rag import pipeline
        orchestrator = RagOrchestrator(technology_runner=self.technology, ntis_runner=self.ntis, backend='local')
        with patch.object(pipeline, "build_index", return_value={"index": "cached"}) as build, \
             patch.object(pipeline, "search_module_result", return_value=module_result("rfp")) as search:
            orchestrator.run(self.request)
            orchestrator.run({**self.request, "problem": "다른 기술문제"})
        self.assertEqual(build.call_count, 1)
        self.assertEqual(search.call_count, 2)


if __name__ == "__main__":
    unittest.main()
