import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from app.common.schemas import Evidence, ExternalTechCandidate, GapLabel, ModuleResult, TechElement
from app.final_answer import AnswerDraft, DraftClaim, CitationRequest, SupportReview, SupportDecision, generate_final_answer
from app.gap_analysis import GapItem, GapReport
from app.integrated_analysis import compare_reports, run_integrated_analysis
from app.orchestrator import AnalysisRequest, AnalysisState


def fixture(method="llm"):
    text = "동적 객체 추적 기술을 개발한다."
    evidence = Evidence(doc_id="rfp-1", source="rfp", quote=text, verified=True, page=0)
    candidate = ExternalTechCandidate(doc_id="rfp-1", title="안전주행 과제", relevance_score=0.5,
        relation_summary="", evidences=[evidence], extra={"requirements": {
            "개발내용": [{"text": text, "page": 1, "bbox": [0, 0, 100, 20]}]}})
    request = AnalysisRequest(problem="충돌을 줄이고 싶다.", owned_technologies=["SLAM"])
    state = AnalysisState(request=request, technology=ModuleResult(module="technology", query="질문"),
        ntis=ModuleResult(module="ntis", query="질문"),
        rfp=ModuleResult(module="rfp", query="질문", candidates=[candidate]))
    report = GapReport(problem=request.problem, method=method, items=[GapItem(
        requirement=TechElement(element_id="te-1", name="동적 객체 추적", origin="rfp", evidences=[evidence]),
        rfp_doc_ids=["rfp-1"], requirement_clear=True, label=GapLabel.RND_NEEDED,
        decision_path="RFP가 명확히 요구하나 기업·외부기술 충족 근거 없음")])
    return state, report


class FakeLLM:
    def __init__(self, *, evidence_id="E1", quote="동적 객체 추적 기술을 개발한다.", supported=True,
                 gap_index=0, empty_review=False):
        self.evidence_id, self.quote, self.supported = evidence_id, quote, supported
        self.gap_index, self.empty_review = gap_index, empty_review
        self.calls = []

    def __call__(self, messages, model):
        self.calls.append(model.__name__)
        if model is AnswerDraft:
            return AnswerDraft(claims=[DraftClaim(section="gap", gap_index=self.gap_index,
                text="동적 객체 추적은 추가 개발을 검토할 후보입니다.",
                citations=[CitationRequest(evidence_id=self.evidence_id, quote=self.quote)])])
        return SupportReview(decisions=[] if self.empty_review else [
            SupportDecision(claim_index=0, supported=self.supported, reason="근거 검토 결과")])


class FinalAnswerTests(unittest.TestCase):
    def test_valid_citation_and_semantic_review(self):
        state, report = fixture()
        llm = FakeLLM()
        answer = generate_final_answer(state, report, llm=llm)
        self.assertEqual(answer.status, "ok")
        self.assertTrue(answer.claims[0].accepted)
        self.assertIn("추가 개발을 검토할 후보", answer.markdown)
        self.assertIn("1쪽", answer.markdown)
        self.assertEqual(llm.calls, ["AnswerDraft", "SupportReview"])

    def test_unknown_or_invented_quote_is_removed(self):
        for options in ({"evidence_id": "E999"}, {"quote": "원문에 없는 실시간 추론 기술"}):
            state, report = fixture()
            llm = FakeLLM(**options)
            answer = generate_final_answer(state, report, llm=llm)
            self.assertFalse(answer.claims[0].accepted)
            self.assertNotIn("추가 개발을 검토할 후보", answer.markdown)
            self.assertEqual(llm.calls, ["AnswerDraft"])

    def test_semantic_rejection_and_missing_review(self):
        for options in ({"supported": False}, {"empty_review": True}):
            state, report = fixture()
            answer = generate_final_answer(state, report, llm=FakeLLM(**options))
            self.assertEqual(answer.status, "insufficient")
            self.assertFalse(answer.claims[0].accepted)

    def test_gap_index_must_match(self):
        state, report = fixture()
        answer = generate_final_answer(state, report, llm=FakeLLM(gap_index=12))
        self.assertFalse(answer.claims[0].accepted)

    def test_forged_rfp_requirement_cannot_support_final_label(self):
        state, report = fixture()
        report.items[0].requirement.evidences[0] = Evidence(
            doc_id="another-doc", source="rfp", quote="존재하지 않는 RFP 요구기술", verified=True)
        answer = generate_final_answer(state, report, template_only=True)
        self.assertIn("근거부족", answer.markdown)
        self.assertNotIn("| 추가R&D검토후보 |", answer.markdown)

    def test_inconsistent_coverage_label_is_not_published(self):
        state, report = fixture()
        report.items[0].label = GapLabel.OWNED
        answer = generate_final_answer(state, report, template_only=True)
        self.assertIn("근거부족", answer.markdown)
        self.assertNotIn("| 기존보유 |", answer.markdown)
        self.assertEqual(report.items[0].label, GapLabel.OWNED)

    def test_local_template_does_not_call_llm(self):
        state, report = fixture("local")
        llm = Mock(side_effect=AssertionError("LLM must not run"))
        answer = generate_final_answer(state, report, llm=llm, template_only=True)
        self.assertIn("잠정 판정", answer.markdown)
        self.assertIn("[E1](#e1)", answer.markdown)
        llm.assert_not_called()

    def test_unseen_suffix_of_truncated_evidence_cannot_be_cited(self):
        state, report = fixture()
        long_quote = "실제 원문 내용입니다." * 200 + "마지막 부분에만 있는 특수 근거입니다."
        evidence = state.rfp.candidates[0].evidences[0]
        evidence.quote = long_quote
        state.rfp.candidates[0].extra["requirements"]["개발내용"][0]["text"] = long_quote
        report.items[0].requirement.evidences[0] = evidence
        answer = generate_final_answer(state, report, llm=FakeLLM(quote="마지막 부분에만 있는 특수 근거입니다."))
        self.assertFalse(answer.claims[0].accepted)

    def test_empty_rfp_does_not_call_generation(self):
        state, _ = fixture()
        state.rfp.candidates = []
        report = GapReport(problem=state.request.problem)
        llm = Mock(side_effect=AssertionError("Empty report must not call a model"))
        answer = generate_final_answer(state, report, llm=llm)
        self.assertEqual(answer.status, "insufficient")
        llm.assert_not_called()


class IntegratedAnalysisTests(unittest.TestCase):
    def test_cli_reuses_saved_state_without_remote_calls(self):
        from app.scripts.run_analysis import main
        state, _ = fixture()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "state.json").write_text(state.model_dump_json(), encoding="utf-8")
            with patch("app.gap_analysis_local.default_tokenizer", return_value=lambda text: text.split()), redirect_stdout(io.StringIO()):
                code = main(["--state", str(root / "state.json"), "--mode", "local",
                             "--template-only", "--output-dir", str(root / "run")])
            self.assertEqual(code, 0)
            result = json.loads((root / "run" / "comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(result["primary_method"], "llm")
            self.assertIn("local", result["answers"])
            self.assertFalse((root / "run" / "answer.md").exists())

    def test_shared_retrieval_snapshot_outputs_and_main_first(self):
        state, report = fixture()
        request = state.request
        orchestrator = Mock()
        orchestrator.run.return_value = state
        snapshots = []
        def runner(state, **options):
            snapshots.append(state.request.problem)
            returned = report.model_copy(deep=True)
            returned.method = "llm" if "llm" in options else "local"
            state.request.problem = "변경된 입력"
            return returned
        with tempfile.TemporaryDirectory() as temp:
            result = run_integrated_analysis(request=request, orchestrator=orchestrator,
                gap_runners={"llm": runner, "local": runner}, llm_factory=FakeLLM,
                template_only=True, output_dir=temp)
            self.assertFalse(result.errors)
            self.assertEqual(list(result.answers), ["llm", "local"])
            for name in ("state.json", "gap_llm.json", "gap_local.json", "answer.md", "answer_llm.md", "answer_local.md", "comparison.json"):
                self.assertTrue((Path(temp) / name).is_file())
            json.loads((Path(temp) / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshots, [request.problem, request.problem])
        orchestrator.run.assert_called_once_with(request)

    def test_one_mode_failure_does_not_hide_other_result(self):
        state, report = fixture("local")
        result = run_integrated_analysis(state=state, template_only=True, llm_factory=FakeLLM,
            gap_runners={"llm": Mock(side_effect=RuntimeError("모델 호출 실패")),
                         "local": lambda *args, **kwargs: report})
        self.assertIn("gap_llm", result.errors)
        self.assertIn("local", result.answers)

    def test_different_extraction_granularity_not_reported_as_accuracy(self):
        _, report = fixture()
        other = report.model_copy(deep=True)
        other.method = "local"
        other.items[0].requirement.name = "동적 객체를 추적하는 기능을 개발"
        comparison = compare_reports(report, other)
        self.assertEqual(comparison["shared_exact_requirements"], [])
        self.assertEqual(len(comparison["llm_only"]), 1)
        self.assertEqual(len(comparison["local_only"]), 1)


if __name__ == "__main__":
    unittest.main()
