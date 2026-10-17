import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.analysis_view import ProjectionError, project_analysis_view
from app.api.main import app
from app.common.schemas import Evidence, ExternalTechCandidate, GapLabel, ModuleResult, TechElement
from app.final_answer import AnswerDraft, CitationRequest, DraftClaim, SupportDecision, SupportReview, collect_evidence, generate_final_answer
from app.gap_analysis import GapItem, GapReport, SourceMatch
from app.integrated_analysis import AnalysisRun
from app.orchestrator import AnalysisRequest, AnalysisState

TRACKING = "동적 객체 추적 기술을 개발한다."
LIDAR = "라이다 센서 융합 기술을 개발한다."
BATTERY = "배터리 열관리 기술을 개발한다."
TECH_QUOTE = "카메라 영상으로 동적 객체 추적을 수행한다."


def rfp(doc_id, task_id, title, text, **extra):
    evidence = Evidence(doc_id=doc_id, source="rfp", quote=text, verified=True, page=0, extra=dict(extra))
    return ExternalTechCandidate(doc_id=doc_id, title=title, relevance_score=0.5, relation_summary="", evidences=[evidence],
                                 extra={"task_id": task_id, "requirements": {"개발내용": [{"text": text, "page": 1}]}, **extra})


def fixture():
    tech_ev = Evidence(doc_id="pub-1", source="pub", quote=TECH_QUOTE, verified=True)
    tech1 = ExternalTechCandidate(doc_id="pub-1", title="영상 기반 객체 추적", provider="기관A", relevance_score=0.9,
                                  relation_summary="[동일] 객체 추적", evidences=[tech_ev], extra={"match_level": "same"})
    tech2 = ExternalTechCandidate(doc_id="pub-2", title="열화상 진단", relevance_score=0.8, relation_summary="")
    notice = {"notice_titles": ["2026 자율주행 공고"], "notice_urls": ["https://example.go.kr/n?id=1 https://footer"]}
    t1 = rfp("rfp-1", "t1", "추적 과제", TRACKING, **notice)
    t2 = rfp("rfp-1", "t2", "센서 융합 과제", LIDAR)
    t3 = rfp("rfp-2", "t3", "배터리 과제", BATTERY)
    request = AnalysisRequest(problem="충돌을 줄이고 싶다.", owned_technologies=["SLAM"])
    state = AnalysisState(
        request=request,
        technology=ModuleResult(module="technology", query="q", candidates=[tech1, tech1.model_copy(deep=True), tech2]),
        ntis=ModuleResult(module="ntis", query="q"),
        rfp=ModuleResult(module="rfp", query="q", candidates=[t1, t2, t1.model_copy(deep=True), t3]))
    requirement = lambda name, text: TechElement(element_id=f"te-{name}", name=name, origin="rfp", evidences=[
        Evidence(doc_id="rfp-1", source="rfp", quote=text, verified=True)])
    report = GapReport(problem=request.problem, method="llm", stats={"rfps_analyzed": ["rfp-1", "rfp-1"], "rfps_skipped": ["rfp-1", "rfp-2"]}, items=[
        GapItem(requirement=requirement("동적 객체 추적", TRACKING), rfp_doc_ids=["rfp-1"], requirement_clear=True,
                label=GapLabel.EXTERNAL, decision_path="외부기술 보완",
                external=[SourceMatch(source="pub", element_name="객체 추적", coverage="full", reason="r", verified=True,
                                      doc_id="pub-1", title=tech1.title, evidences=[tech_ev])]),
        # Inconsistent with its (empty) matches: the final answer downgrades it to 근거부족.
        GapItem(requirement=requirement("라이다 센서 융합", LIDAR), rfp_doc_ids=["rfp-1"], requirement_clear=True,
                label=GapLabel.EXTERNAL, decision_path="외부기술 보완"),
    ])
    return state, report


class FakeLLM:
    def __init__(self, evidence_id):
        self.evidence_id, self.calls = evidence_id, []

    def __call__(self, messages, model):
        self.calls.append(model.__name__)
        if model is AnswerDraft:
            return AnswerDraft(claims=[DraftClaim(section="gap", gap_index=0, text="동적 객체 추적은 외부기술로 보완할 수 있습니다.",
                                                  citations=[CitationRequest(evidence_id=self.evidence_id, quote=TRACKING)])])
        return SupportReview(decisions=[SupportDecision(claim_index=0, supported=True, reason="ok")])


def run_fixture():
    state, report = fixture()
    eid = next(r.evidence_id for r in collect_evidence(state, report) if r.evidence.quote == TRACKING)
    llm = FakeLLM(eid)
    return state, report, generate_final_answer(state, report, llm=llm), llm


def markdown_section(markdown, number):
    return markdown.split(f"## {number}.")[1].split("\n## ")[0]


class AnalysisViewTests(unittest.TestCase):
    def setUp(self):
        self.state, self.report, self.answer, self.llm = run_fixture()
        calls = len(self.llm.calls)
        with patch("app.gap_analysis.OpenAIStructuredLLM", side_effect=AssertionError("LLM 호출 금지")):
            self.view = project_analysis_view(self.state, self.report, self.answer)
        self.assertEqual(len(self.llm.calls), calls)  # projection makes no LLM call

    def test_evidence_ids_match_final_answer_and_claim_links_use_accepted_citations(self):
        self.assertEqual([e.id for e in self.view.evidence_items], [r.evidence_id for r in self.answer.evidence])
        self.assertEqual([e.quote for e in self.view.evidence_items], [r.evidence.quote for r in self.answer.evidence])
        accepted = {i for i, c in enumerate(self.answer.claims) if c.accepted}
        self.assertTrue(accepted)
        cited = {c.evidence_id for i in accepted for c in self.answer.claims[i].citations if c.ok}
        for item in self.view.evidence_items:
            self.assertEqual(bool(item.claim_indices), item.id in cited)
            self.assertTrue(set(item.claim_indices) <= accepted)
        known = {e.id for e in self.view.evidence_items}
        for row in (*self.view.technologies, *self.view.rfps, *self.view.gap_items):
            self.assertTrue(set(row.evidence_ids) <= known)

    def test_gap_labels_and_scope_match_markdown(self):
        labels = {g.requirement_name: g.label for g in self.view.gap_items}
        self.assertEqual(labels, {"동적 객체 추적": GapLabel.EXTERNAL, "라이다 센서 융합": GapLabel.INSUFFICIENT})
        self.assertEqual(self.report.items[1].label, GapLabel.EXTERNAL)  # raw report differs; view follows the answer
        table = dict(re.findall(r"^\| (\S+) \| (\d+) \|", markdown_section(self.answer.markdown, 3), re.M))
        self.assertEqual(table, {k: str(v) for k, v in self.view.overview.gap_label_counts.items() if v})
        self.assertEqual(self.view.gap_items[0].technology_ids, ["pub-1"])
        self.assertEqual(self.view.gap_items[0].claim_indices, [i for i, c in enumerate(self.answer.claims) if c.accepted])
        self.assertEqual(self.view.overview.gap_label_counts[GapLabel.RND_NEEDED.value], 0)  # enum value kept

    def test_candidate_order_and_dedup_match_markdown(self):
        rfp_rows = re.findall(r"^\| (\d+)[^|]*\| ([^|]+) \|", markdown_section(self.answer.markdown, 4), re.M)
        tech_rows = re.findall(r"^\| (\d+)[^|]*\| ([^|]+) \|", markdown_section(self.answer.markdown, 5), re.M)
        self.assertEqual([(str(r.rank), r.title) for r in self.view.rfps], [(n, t.strip()) for n, t in rfp_rows])
        self.assertEqual([(str(t.rank), t.title) for t in self.view.technologies], [(n, t.strip()) for n, t in tech_rows])
        self.assertEqual([r.id for r in self.view.rfps], ["t1", "t2", "t3"])
        self.assertEqual(self.view.overview.primary_rfp_id, "t1")
        self.assertEqual(self.view.overview.primary_technology_id, "pub-1")

    def test_shared_pdf_tasks_and_gap_analysis_status_are_separated(self):
        t1, t2, t3 = self.view.rfps
        self.assertEqual((t1.document_id, t2.document_id), ("rfp-1", "rfp-1"))
        self.assertEqual(t1.gap_item_ids, ["gap-0"])
        self.assertEqual(t2.gap_item_ids, ["gap-1"])
        self.assertEqual([r.gap_analysis_status for r in self.view.rfps], ["analyzed", "analyzed", "not_analyzed"])
        self.assertEqual(t3.gap_item_ids, [])
        self.assertEqual(t1.notice_urls, ["https://example.go.kr/n?id=1"])
        by_id = {e.id: e for e in self.view.evidence_items}
        self.assertTrue(all(by_id[eid].quote == TRACKING for eid in t1.evidence_ids))
        self.assertTrue(all(by_id[eid].quote == LIDAR for eid in t2.evidence_ids))
        self.assertIsNone(by_id[t2.evidence_ids[0]].source_title)  # shared PDF: no single task title

    def test_not_analyzed_task_sharing_pdf_is_not_added_to_gap_rfp_ids(self):
        state = self.state.model_copy(deep=True)
        skipped = rfp("rfp-1", "t-skipped", "미분석 같은 PDF 과제", TRACKING)
        state.rfp.candidates.append(skipped)
        view = project_analysis_view(state, self.report, self.answer)
        self.assertEqual(next(r for r in view.rfps if r.id == "t-skipped").gap_analysis_status, "not_analyzed")
        self.assertNotIn("t-skipped", {rfp_id for gap in view.gap_items for rfp_id in gap.rfp_ids})

    def test_missing_fields_stay_empty_and_technology_links_are_verified_only(self):
        tech1, tech2 = self.view.technologies
        self.assertEqual(tech1.gap_item_ids, ["gap-0"])
        self.assertEqual(tech2.gap_item_ids, [])
        self.assertEqual((tech2.rationale, tech2.provider, tech2.match_level, tech2.evidence_ids), (None, None, None, []))
        self.assertEqual((self.view.rfps[2].notice_titles, self.view.rfps[2].notice_urls), ([], []))
        self.assertNotIn("description", tech1.model_dump())
        self.assertNotIn("key_gap_item_ids", self.view.overview.model_dump())

    def test_gap_item_ids_reference_gap_items_in_both_directions(self):
        gaps = {g.id: g for g in self.view.gap_items}
        rfp_links = [(r.id, gid) for r in self.view.rfps for gid in r.gap_item_ids]
        tech_links = [(t.id, gid) for t in self.view.technologies for gid in t.gap_item_ids]
        self.assertTrue(rfp_links and tech_links)
        for rfp_id, gid in rfp_links:
            self.assertIn(rfp_id, gaps[gid].rfp_ids)
        for tech_id, gid in tech_links:
            self.assertIn(tech_id, gaps[gid].technology_ids)
        # The reverse direction is complete for analyzed RFPs and for every technology.
        analyzed = {r.id for r in self.view.rfps if r.gap_analysis_status == "analyzed"}
        self.assertEqual(sorted(rfp_links), sorted((rid, g.id) for g in self.view.gap_items for rid in g.rfp_ids if rid in analyzed))
        self.assertEqual(sorted(tech_links), sorted((tid, g.id) for g in self.view.gap_items for tid in g.technology_ids
                                                    if tid in {t.id for t in self.view.technologies}))
        for candidate in (*self.view.rfps, *self.view.technologies):
            self.assertNotIn("matched_requirement_ids", candidate.model_dump())

    def test_unknown_analysis_scope_and_evidence_mismatch(self):
        report = self.report.model_copy(update={"stats": {}})
        unknown = project_analysis_view(self.state, report, self.answer).rfps
        self.assertEqual({r.gap_analysis_status for r in unknown}, {"unknown"})
        self.assertEqual([r.gap_item_ids for r in unknown], [[], [], []])  # no analyzed Gap links without a known scope
        other = self.answer.model_copy(deep=True)
        other.evidence[0].evidence_id = "E999"
        with self.assertRaises(ProjectionError) as caught:
            project_analysis_view(self.state, self.report, other)
        self.assertEqual(caught.exception.code, "evidence_mismatch")


class ReportViewApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.state, self.report, self.answer, _ = run_fixture()
        self.payload = {"problem": self.state.request.problem, "owned_technologies": ["SLAM"]}

    def post(self, **patches):
        run = AnalysisRun(reports={"llm": self.report}, answers={"llm": self.answer})
        with patch("app.api.main.get_orchestrator") as orchestrator, \
                patch("app.api.main.run_integrated_analysis", return_value=run) as integrated:
            orchestrator.return_value.run.return_value = self.state
            if patches:
                with patch("app.api.main.project_analysis_view", **patches):
                    response = self.client.post("/api/analysis/report-view", json=self.payload)
            else:
                response = self.client.post("/api/analysis/report-view", json=self.payload)
        orchestrator.return_value.run.assert_called_once()
        integrated.assert_called_once()
        self.assertIs(integrated.call_args.kwargs["state"], self.state)
        self.assertNotIn("request", integrated.call_args.kwargs)  # retrieval is not run a second time
        return response

    def test_report_view_runs_analysis_once_and_keeps_final_answer_unchanged(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"report", "view", "view_status", "view_error"})
        self.assertEqual(body["report"], self.answer.model_dump(mode="json"))
        self.assertEqual((body["view_status"], body["view_error"]), ("ok", None))
        self.assertEqual(set(body["view"]), {"technologies", "rfps", "gap_items", "evidence_items", "overview"})
        gap_ids = {g["id"] for g in body["view"]["gap_items"]}
        for candidate in (*body["view"]["rfps"], *body["view"]["technologies"]):
            self.assertNotIn("matched_requirement_ids", candidate)
            self.assertLessEqual(set(candidate["gap_item_ids"]), gap_ids)
        self.assertEqual([r["gap_item_ids"] for r in body["view"]["rfps"]], [["gap-0"], ["gap-1"], []])
        self.assertEqual([t["gap_item_ids"] for t in body["view"]["technologies"]], [["gap-0"], []])

    def test_projection_failure_returns_report_with_null_view(self):
        response = self.post(side_effect=RuntimeError("secret-detail"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["report"]["markdown"], self.answer.markdown)
        self.assertEqual((body["view"], body["view_status"], body["view_error"]), (None, "failed", "projection_error"))
        self.assertNotIn("secret", response.text)
        response = self.post(side_effect=ProjectionError("evidence_mismatch", "detail"))
        self.assertEqual(response.json()["view_error"], "evidence_mismatch")

    def test_report_view_rejects_invalid_input_before_running_analysis(self):
        with patch("app.api.main.get_orchestrator") as orchestrator:
            response = self.client.post("/api/analysis/report-view", json={})
        self.assertEqual(response.status_code, 422)
        orchestrator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
