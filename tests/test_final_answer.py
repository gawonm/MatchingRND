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
from app.integrated_analysis import run_integrated_analysis
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
    def test_automatic_support_linking_does_not_remove_other_row_citations(self):
        state, report = fixture()
        other = Evidence(doc_id='rfp-2', source='rfp', quote='다른 과제는 수소 생산 공정 개발을 요구한다.', verified=True)
        state.rfp.candidates.append(ExternalTechCandidate(doc_id='rfp-2', title='다른 과제', relevance_score=1,
            relation_summary='', evidences=[other], extra={'requirements': {
                '개발내용': [{'text': other.quote, 'page': 1}]}}))
        answer = generate_final_answer(state, report,
            llm=FakeLLM(evidence_id='E2', quote=other.quote), max_retries=0)
        self.assertFalse(answer.claims[0].accepted)
        self.assertEqual({c.evidence_id for c in answer.claims[0].draft.citations}, {'E1', 'E2'})
        self.assertIn('해당 Gap 행', answer.claims[0].reason)

    def test_source_and_gap_linkage_are_enforced_by_response_schema(self):
        from pydantic import ValidationError
        for section, gap_index in [('rfp', 0), ('external', 2), ('gap', None)]:
            with self.subTest(section=section, gap_index=gap_index), self.assertRaises(ValidationError):
                AnswerDraft.model_validate({'claims': [{'section': section, 'gap_index': gap_index,
                    'text': 'claim', 'citations': [{'evidence_id': 'E1', 'quote': None}]}]})

    def test_optional_large_context_cannot_crowd_out_requirement_evidence(self):
        state, report = fixture()
        ev = Evidence(doc_id='pub-optional', source='pub', quote='任意の長い参考資料です。' * 300, verified=True)
        state.technology.candidates = [ExternalTechCandidate(doc_id=ev.doc_id, title='optional',
            relevance_score=1, relation_summary='', evidences=[ev])]
        def llm(messages, model):
            payload = json.loads(messages[-1]['content'])
            if model is AnswerDraft:
                ids = payload['gap'][0]['evidence_ids']['rfp']
                self.assertTrue(ids)
                self.assertLessEqual(sum(len(row['quote']) for row in payload['evidence']), 40)
                return AnswerDraft(claims=[DraftClaim(section='gap', gap_index=0,
                    text='추가 검토 후보입니다.', citations=[CitationRequest(evidence_id=ids[0])])])
            return SupportReview(decisions=[SupportDecision(claim_index=0, supported=True, reason='지원됨')])
        answer = generate_final_answer(state, report, llm=llm, max_evidence_chars=40)
        self.assertEqual(answer.status, 'ok')

    def test_duplicate_semantic_reviews_remain_rejected(self):
        state, report = fixture()
        def llm(messages, model):
            if model is AnswerDraft:
                return AnswerDraft(claims=[DraftClaim(section='gap', gap_index=0, text='추가 검토 후보입니다.',
                                                     citations=[CitationRequest(evidence_id='E1')])])
            return SupportReview(decisions=[SupportDecision(claim_index=0, supported=True, reason='first'),
                                            SupportDecision(claim_index=0, supported=True, reason='duplicate')])
        answer = generate_final_answer(state, report, llm=llm, max_retries=0)
        self.assertEqual(answer.status, 'insufficient')
        self.assertFalse(answer.claims[0].accepted)

    def test_evidence_id_selects_exact_supplied_quote_and_row_mapping_reaches_reviewer(self):
        state, report = fixture()
        payloads = []
        def llm(messages, model):
            payload = json.loads(messages[-1]['content'])
            payloads.append(payload)
            if model is AnswerDraft:
                ids = payload['gap'][0]['evidence_ids']['rfp']
                return AnswerDraft(claims=[DraftClaim(section='gap', gap_index=0,
                    text='현재 제공 자료에서 충족 근거를 확인하지 못하여 추가 개발 검토 후보입니다.',
                    citations=[CitationRequest(evidence_id=ids[0])])])
            self.assertEqual(payload['claims'][0]['gap']['label'], GapLabel.RND_NEEDED.value)
            self.assertIn('assessment_scope', payload['claims'][0]['gap'])
            return SupportReview(decisions=[SupportDecision(claim_index=0, supported=True, reason='분석 범위와 근거 일치')])
        answer = generate_final_answer(state, report, llm=llm)
        self.assertEqual(answer.status, 'ok')
        self.assertEqual(answer.claims[0].draft.citations[0].quote, '동적 객체 추적 기술을 개발한다.')
        self.assertEqual(len(payloads), 2)

    def test_invalid_reference_is_regenerated_with_feedback_and_never_auto_accepted(self):
        state, report = fixture()
        generated = 0
        def llm(messages, model):
            nonlocal generated
            payload = json.loads(messages[-1]['content'])
            if model is AnswerDraft:
                generated += 1
                if generated > 1:
                    self.assertIn('repair', payload)
                return AnswerDraft(claims=[DraftClaim(section='gap', gap_index=0, text='추가 검토 후보입니다.',
                    citations=[CitationRequest(evidence_id='invented' if generated == 1 else 'E1')])])
            return SupportReview(decisions=[SupportDecision(claim_index=0, supported=True, reason='지원됨')])
        answer = generate_final_answer(state, report, llm=llm)
        self.assertEqual(answer.status, 'ok')
        self.assertEqual(len(answer.stats['draft_attempts']), 2)
        self.assertFalse(answer.stats['draft_attempts'][0]['claims'][0]['accepted'])
        self.assertTrue(answer.claims[0].accepted)

    def test_external_gap_requires_both_RFP_and_matching_external_evidence(self):
        from app.gap_analysis import SourceMatch
        state, report = fixture()
        ev = Evidence(doc_id='pub-1', source='pub', quote='동적 객체 추적을 지원하는 외부 센서 기술입니다.', verified=True)
        state.technology.candidates = [ExternalTechCandidate(doc_id='pub-1', title='센서',
            relevance_score=1, relation_summary='', evidences=[ev])]
        report.items[0].external = [SourceMatch(source='pub', element_name='센서', coverage='full',
            verified=True, reason='일치', evidences=[ev])]
        report.items[0].label = GapLabel.EXTERNAL
        # Generation links the row's real mandatory source, while the standalone guard stays strict.
        answer = generate_final_answer(state, report, llm=FakeLLM(evidence_id='E2'), max_retries=0)
        self.assertTrue(answer.claims[0].accepted)
        from app.final_answer import _check_claim
        bank = {r.evidence_id: r for r in answer.evidence}
        unlinked = DraftClaim(section='gap', gap_index=0, text='외부기술보완입니다.',
                              citations=[CitationRequest(evidence_id='E2', quote=bank['E2'].evidence.quote)])
        self.assertFalse(_check_claim(unlinked, bank, report).accepted)

    def test_accepted_claims_are_preserved_while_only_rejected_claims_are_repaired(self):
        state, report = fixture()
        generated = 0
        def llm(messages, model):
            nonlocal generated
            if model is AnswerDraft:
                generated += 1
                if generated == 1:
                    return AnswerDraft(claims=[
                        DraftClaim(section='gap', gap_index=0, text='추가 검토 후보입니다.', citations=[CitationRequest(evidence_id='E1')]),
                        DraftClaim(section='rfp', gap_index=None, text='RFP 원문을 확인하세요.', citations=[CitationRequest(evidence_id='bad')])])
                return AnswerDraft(claims=[DraftClaim(section='rfp', gap_index=None,
                    text='동적 객체 추적을 요구합니다.', citations=[CitationRequest(evidence_id='E1')])])
            payload = json.loads(messages[-1]['content'])
            return SupportReview(decisions=[SupportDecision(claim_index=row['claim_index'], supported=True, reason='지원됨')
                                             for row in payload['claims']])
        answer = generate_final_answer(state, report, llm=llm)
        self.assertEqual(answer.status, 'ok')
        self.assertEqual(len(answer.claims), 2)
        self.assertTrue(all(claim.accepted for claim in answer.claims))

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
            answer = generate_final_answer(state, report, llm=llm, max_retries=0)
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
        self.assertIn("동적 객체 추적 기술을 개발한다.", answer.markdown)
        llm.assert_not_called()

    def test_template_contract_has_seven_sections_citation_table_and_url_without_llm(self):
        from app.answer_format import HEADINGS

        state, report = fixture("local")
        state.rfp.candidates[0].extra.update({
            "notice_titles": ["2026년도 지원 공고"],
            "notice_urls": ["https://example.go.kr/notice?id=1"],
        })
        llm = Mock(side_effect=AssertionError("LLM must not run"))
        answer = generate_final_answer(state, report, llm=llm, template_only=True)

        self.assertEqual(
            [line[3:] for line in answer.markdown.splitlines() if line.startswith("## ")],
            list(HEADINGS),
        )
        self.assertIn("> 동적 객체 추적 기술을 개발한다.", answer.markdown)
        self.assertIn("| 판정 | 기술요소 수 |", answer.markdown)
        self.assertIn("[원 공고](https://example.go.kr/notice?id=1)", answer.markdown)
        llm.assert_not_called()

    def test_common_rnd_notices_are_always_shown(self):
        from app.answer_format import COMMON_RND_INTRO, COMMON_RND_NOTICES

        state, report = fixture()
        for kwargs in ({"template_only": True}, {"llm": FakeLLM()}):
            answer = generate_final_answer(state, report, **kwargs)
            self.assertIn("## 6. 공통 R&D 유의사항", answer.markdown)
            for line in COMMON_RND_INTRO:
                self.assertIn(line, answer.markdown)
            for notice in COMMON_RND_NOTICES:
                self.assertIn(f"- {notice}", answer.markdown)
        self.assertNotIn("## 6. 관련 법령", answer.markdown)
        # 근거 없는 상태(후보 없음)에서도 같은 문구가 나온다.
        state.rfp.candidates = []
        empty = generate_final_answer(state, GapReport(problem=state.request.problem), template_only=True)
        for notice in COMMON_RND_NOTICES:
            self.assertIn(notice, empty.markdown)

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
    def test_cli_reuses_saved_state_without_retrieval_calls(self):
        from app.scripts.run_analysis import main
        state, report = fixture()
        def run_saved_state(**options):
            return run_integrated_analysis(**options, gap_runner=lambda *args, **kwargs: report,
                                           llm_factory=FakeLLM)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "state.json").write_text(state.model_dump_json(), encoding="utf-8")
            with patch("app.scripts.run_analysis.run_integrated_analysis", side_effect=run_saved_state), \
                 patch("app.scripts.run_analysis.RagOrchestrator") as orchestrator, redirect_stdout(io.StringIO()):
                code = main(["--state", str(root / "state.json"),
                             "--template-only", "--output-dir", str(root / "run")])
            self.assertEqual(code, 0)
            orchestrator.return_value.run.assert_not_called()
            result = json.loads((root / "run" / "comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(result["primary_method"], "llm")
            self.assertEqual(list(result["answers"]), ["llm"])
            self.assertTrue((root / "run" / "answer.md").exists())

    def test_retrieval_snapshot_outputs(self):
        state, report = fixture()
        request = state.request
        orchestrator = Mock()
        orchestrator.run.return_value = state
        snapshots = []
        def runner(state, **options):
            snapshots.append(state.request.problem)
            returned = report.model_copy(deep=True)
            returned.method = "llm"
            state.request.problem = "변경된 입력"
            return returned
        with tempfile.TemporaryDirectory() as temp:
            result = run_integrated_analysis(request=request, orchestrator=orchestrator,
                gap_runner=runner, llm_factory=FakeLLM,
                template_only=True, output_dir=temp)
            self.assertFalse(result.errors)
            self.assertEqual(list(result.answers), ["llm"])
            for name in ("state.json", "gap_llm.json", "answer.md", "answer_llm.md", "comparison.json"):
                self.assertTrue((Path(temp) / name).is_file())
            json.loads((Path(temp) / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshots, [request.problem])
        orchestrator.run.assert_called_once_with(request)

    def test_gap_failure_is_reported_without_generating_an_answer(self):
        state, _ = fixture()
        answer_generator = Mock()
        result = run_integrated_analysis(state=state, template_only=True, llm_factory=FakeLLM,
            gap_runner=Mock(side_effect=RuntimeError("모델 호출 실패")),
            answer_generator=answer_generator)
        self.assertEqual(result.errors, {"gap_llm": "모델 호출 실패"})
        self.assertEqual(result.answers, {})
        answer_generator.assert_not_called()

    def test_removed_local_mode_is_rejected_before_retrieval(self):
        state, _ = fixture()
        orchestrator = Mock()
        with self.assertRaisesRegex(ValueError, "llm만 지원"):
            run_integrated_analysis(request=state.request, modes=("llm", "local"),
                                    orchestrator=orchestrator)
        orchestrator.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
