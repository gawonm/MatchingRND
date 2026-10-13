import json
import unittest
from unittest.mock import Mock

from app.common.schemas import Evidence, ExternalTechCandidate, GapLabel, ModuleResult, TechElement
from app.gap_analysis import (
    AlignmentJudgements, CoverageJudgement, GapReport, RequirementExtraction, SourceMatch, decide_label,
    run_gap_analysis,
)
from app.orchestrator import AnalysisRequest, AnalysisState


def requirement(name, quote, *, clear=True, synonyms=(), technology=True):
    return {"name": name, "is_technology": technology, "synonyms": list(synonyms), "broader": [],
            "narrower": [], "function": None, "target": None, "quote": quote, "clear": clear}


def rfp_candidate(doc_id, title, lines):
    fragments = [{"text": text, "page": 3, "bbox": [1, 2, 3, 4], "source": "rfp.pdf", "source_kind": "text"}
                 for text in lines]
    return ExternalTechCandidate(doc_id=doc_id, title=title, relevance_score=0.9, relation_summary="",
                                 extra={"task_id": doc_id, "requirements": {"요구기술": fragments}})


def tech_element(name, source, doc_id, quote):
    return TechElement(element_id=f"te-{name}", name=name, origin=source,
                       evidences=[Evidence(doc_id=doc_id, source=source, quote=quote, verified=True)])


def make_state(owned, rfp_candidates, *, external=(), external_candidates=(), ntis=()):
    return AnalysisState(
        request=AnalysisRequest(problem="작업자와 지게차의 충돌을 줄이고 싶다.", owned_technologies=owned),
        technology=ModuleResult(module="technology", query="q", candidates=list(external_candidates)),
        ntis=ModuleResult(module="ntis", query="q"),
        rfp=ModuleResult(module="rfp", query="q", candidates=list(rfp_candidates)),
        external_elements=list(external), ntis_elements=list(ntis),
    )


class FakeLLM:
    """RFP 제목별 추출 결과와 (요구기술, 후보명)별 충족도를 돌려준다."""

    def __init__(self, extraction, coverage=None):
        self.extraction = extraction
        self.coverage = coverage or {}
        self.alignment_payloads = []

    def __call__(self, messages, response_model):
        payload = json.loads(messages[-1]["content"])
        if response_model is RequirementExtraction:
            return response_model(requirements=self.extraction.get(payload["rfp_title"], []))
        self.alignment_payloads.append(payload)
        name = payload["requirement"]["name"]
        judgements = []
        for candidate in payload["candidates"]:
            coverage, quote = self.coverage.get((name, candidate["name"]), ("none", ""))
            judgements.append({"candidate_index": candidate["index"], "coverage": coverage,
                               "reason": "테스트 판단", "quote": quote})
        return AlignmentJudgements(judgements=judgements)


class GapAnalysisScenarioTests(unittest.TestCase):
    """PROJECT_PLAN 사용자 시나리오: 보유 A, 외부보완 B, 추가 R&D C, 모호한 요구 D."""

    def setUp(self):
        rfp = rfp_candidate("rfp-1", "제조현장 자율주행 안전", [
            "SLAM 기반 위치추정 기술 개발",
            "LiDAR 기반 동적 객체 인지 기술 확보",
            "작업자 동선 기반 동적 객체예측 알고리즘 개발",
            "스마트 제조 고도화",
        ])
        external = tech_element("LiDAR 객체 인지", "pub", "pub-2026-001", "3D LiDAR 점군으로 동적 객체를 인지")
        external_candidate = ExternalTechCandidate(
            doc_id="pub-2026-001", title="LiDAR 객체 인지 기술", provider="한국기계연구원",
            transfer_condition="통상실시", relevance_score=0.8, relation_summary="",
        )
        ntis = tech_element("동적 객체 추적", "ntis", "ntis-1", "제조현장 동적 객체 추적")
        self.state = make_state(["SLAM 기반 자율주행", "영상 객체 인식"], [rfp], external=[external],
                                external_candidates=[external_candidate], ntis=[ntis])
        self.llm = FakeLLM(
            {"제조현장 자율주행 안전": [
                requirement("SLAM", "SLAM 기반 위치추정"),
                requirement("LiDAR 객체 인지", "LiDAR 기반 동적 객체 인지"),
                requirement("동적 객체예측", "동적 객체예측 알고리즘"),
                requirement("스마트 제조", "스마트 제조 고도화", clear=False),
            ]},
            {("SLAM", "SLAM 기반 자율주행"): ("full", "SLAM 기반 자율주행"),
             ("LiDAR 객체 인지", "LiDAR 객체 인지"): ("full", "동적 객체를 인지"),
             ("동적 객체예측", "동적 객체 추적"): ("full", "동적 객체 추적")},
        )
        self.report = run_gap_analysis(self.state, llm=self.llm)
        self.items = {item.requirement.name: item for item in self.report.items}

    def test_labels_follow_decision_priority(self):
        self.assertEqual(self.items["SLAM"].label, GapLabel.OWNED)
        self.assertEqual(self.items["LiDAR 객체 인지"].label, GapLabel.EXTERNAL)
        self.assertEqual(self.items["동적 객체예측"].label, GapLabel.RND_NEEDED)
        self.assertEqual(self.items["스마트 제조"].label, GapLabel.INSUFFICIENT)
        self.assertEqual(self.report.summary, {
            "기존보유": 1, "외부기술보완": 1, "부분충족": 0, "추가R&D검토후보": 1, "근거부족": 1,
        })

    def test_external_match_reports_where_to_supplement(self):
        match = self.items["LiDAR 객체 인지"].external[0]
        self.assertEqual((match.doc_id, match.provider, match.transfer_condition),
                         ("pub-2026-001", "한국기계연구원", "통상실시"))
        self.assertTrue(match.verified)
        self.assertEqual(match.evidences[0].quote, "3D LiDAR 점군으로 동적 객체를 인지")
        self.assertIn("통상실시", self.items["LiDAR 객체 인지"].policy_check[0])

    def test_ntis_is_reference_only(self):
        item = self.items["동적 객체예측"]
        self.assertEqual(item.ntis_references[0].doc_id, "ntis-1")
        self.assertEqual(item.external, [])
        self.assertIn("국가 R&D 과제 참여·수행 조건 확인", item.policy_check)

    def test_requirement_evidence_points_to_rfp_location(self):
        evidence = self.items["SLAM"].requirement.evidences[0]
        self.assertTrue(evidence.verified)
        self.assertEqual((evidence.doc_id, evidence.section, evidence.page), ("rfp-1", "요구기술", 2))
        self.assertEqual(evidence.bbox.as_tuple(), (1, 2, 3, 4))

    def test_unmatched_owned_technology_and_json_roundtrip(self):
        self.assertEqual(self.report.owned_not_required, ["영상 객체 인식"])
        self.assertEqual(GapReport.model_validate_json(self.report.model_dump_json()), self.report)


class GapAnalysisRuleTests(unittest.TestCase):
    def run_single(self, coverage, *, owned=("SLAM 기반 자율주행",), quote="센서 융합 기술"):
        rfp = rfp_candidate("rfp-1", "과제", ["다중 센서 융합 기술 개발"])
        external = tech_element("센서 융합", "pos", "pos-2025-001", "카메라와 레이더 센서 융합")
        llm = FakeLLM({"과제": [requirement("센서 융합", quote)]}, coverage)
        state = make_state(list(owned), [rfp], external=[external])
        return run_gap_analysis(state, llm=llm), llm

    def test_company_partial_is_partial_even_with_external_full(self):
        report, _ = self.run_single({
            ("센서 융합", "SLAM 기반 자율주행"): ("partial", "SLAM"),
            ("센서 융합", "센서 융합"): ("full", "센서 융합"),
        })
        item = report.items[0]
        self.assertEqual(item.label, GapLabel.PARTIAL)
        self.assertEqual(item.external[0].coverage, "full")
        self.assertTrue(item.policy_check)

    def test_external_partial_is_partial(self):
        report, _ = self.run_single({("센서 융합", "센서 융합"): ("partial", "레이더 센서 융합")})
        self.assertEqual(report.items[0].label, GapLabel.PARTIAL)

    def test_unverified_match_quote_is_not_used(self):
        report, _ = self.run_single({("센서 융합", "센서 융합"): ("full", "원문에 없는 문장")})
        item = report.items[0]
        self.assertFalse(item.external[0].verified)
        self.assertEqual(item.label, GapLabel.RND_NEEDED)
        self.assertEqual(item.policy_check, ["국가 R&D 과제 참여·수행 조건 확인"])

    def test_hallucinated_rfp_quote_is_insufficient_without_alignment(self):
        report, llm = self.run_single({}, quote="RFP에 없는 요구")
        self.assertEqual(report.items[0].label, GapLabel.INSUFFICIENT)
        self.assertFalse(report.items[0].requirement.evidences[0].verified)
        self.assertEqual(llm.alignment_payloads, [])
        self.assertTrue(any("확인하지 못했습니다" in warning for warning in report.warnings))

    def test_same_requirement_from_multiple_rfps_is_merged(self):
        rfps = [rfp_candidate("rfp-1", "과제1", ["다중 센서 융합 기술 개발"]),
                rfp_candidate("rfp-2", "과제2", ["Sensor Fusion 기반 인지"])]
        llm = FakeLLM({"과제1": [requirement("센서 융합", "센서 융합", synonyms=["Sensor Fusion"])],
                       "과제2": [requirement("Sensor Fusion", "Sensor Fusion")]})
        report = run_gap_analysis(make_state([], rfps), llm=llm)
        self.assertEqual(len(report.items), 1)
        self.assertEqual(report.items[0].rfp_doc_ids, ["rfp-1", "rfp-2"])
        self.assertEqual(len(report.items[0].requirement.evidences), 2)

    def test_shortlist_limits_candidates_per_source(self):
        owned = ["경로계획", "SLAM", "센서 융합 모듈", "영상 객체 인식", "용접 자동화"]
        rfp = rfp_candidate("rfp-1", "과제", ["다중 센서 융합 기술 개발"])
        llm = FakeLLM({"과제": [requirement("센서 융합", "센서 융합 기술")]})
        run_gap_analysis(make_state(owned, [rfp]), llm=llm, max_candidates=2)
        names = [c["name"] for c in llm.alignment_payloads[0]["candidates"] if c["source"] == "company"]
        self.assertEqual(len(names), 2)
        self.assertEqual(names[0], "센서 융합 모듈")

    def test_empty_rfp_does_not_call_llm(self):
        llm = Mock()
        report = run_gap_analysis(make_state(["SLAM"], []), llm=llm)
        llm.assert_not_called()
        self.assertEqual(report.items, [])
        self.assertEqual(report.owned_not_required, ["SLAM"])
        self.assertIn("추가 R&D 필요를 의미하지 않습니다", report.warnings[0])

    def test_rfp_without_requirement_text_is_warned(self):
        rfp = ExternalTechCandidate(doc_id="rfp-9", title="빈 과제", relevance_score=0.1, relation_summary="")
        report = run_gap_analysis(make_state([], [rfp]), llm=FakeLLM({}))
        self.assertEqual(report.items, [])
        self.assertTrue(any("rfp-9" in warning for warning in report.warnings))


class QuoteLocationTests(unittest.TestCase):
    """PDF 줄바꿈으로 갈라진 문장도 원문 근거로 인정한다."""

    def run_quote(self, lines, quote, *, pages=None):
        rfp = rfp_candidate("rfp-1", "과제", lines)
        if pages:
            for fragment, page in zip(rfp.extra["requirements"]["요구기술"], pages):
                fragment["page"] = page
        llm = FakeLLM({"과제": [requirement("품질예측", quote)]})
        item = run_gap_analysis(make_state([], [rfp]), llm=llm).items[0]
        return item, item.requirement.evidences[0]

    def test_quote_spanning_lines_is_verified_with_all_locations(self):
        item, evidence = self.run_quote(
            ["제조 Foundation Model을 기반으로 품질예측,", "이상탐지 등 다양한 서비스를 생성하는 기술"],
            "품질예측, 이상탐지 등 다양한 서비스")
        self.assertTrue(evidence.verified)
        self.assertEqual(item.label, GapLabel.RND_NEEDED)  # 근거부족으로 잘못 빠지지 않는다
        self.assertEqual(evidence.page, 2)                 # 같은 페이지면 페이지는 유지
        self.assertIsNone(evidence.bbox)                   # 여러 조각이면 단일 좌표를 만들지 않는다
        self.assertEqual(len(evidence.extra["locations"]), 2)

    def test_quote_spanning_pages_has_no_single_page(self):
        _, evidence = self.run_quote(["첫 줄은 품질예측을 위해", "다음 줄에서 이어지는 문장"],
                                     "품질예측을 위해 다음 줄에서 이어지는", pages=[3, 4])
        self.assertTrue(evidence.verified)
        self.assertIsNone(evidence.page)
        self.assertEqual([loc["page"] for loc in evidence.extra["locations"]], [3, 4])

    def test_single_line_quote_keeps_exact_position(self):
        _, evidence = self.run_quote(["앞 줄", "SLAM 기반 위치추정 기술 개발"], "SLAM 기반 위치추정")
        self.assertEqual((evidence.page, evidence.bbox.as_tuple()), (2, (1, 2, 3, 4)))
        self.assertEqual(len(evidence.extra["locations"]), 1)

    def test_leading_bullet_in_quote_is_ignored(self):
        _, evidence = self.run_quote(["SLAM 기반 위치추정 기술 개발"], "- SLAM 기반 위치추정")
        self.assertTrue(evidence.verified)
        self.assertEqual(evidence.quote, "SLAM 기반 위치추정")

    def test_changed_wording_is_still_rejected(self):
        item, evidence = self.run_quote(["SLAM 기반 위치추정 기술 개발"], "원문과 다르게 바꿔 쓴 문장")
        self.assertFalse(evidence.verified)
        self.assertEqual(item.label, GapLabel.INSUFFICIENT)

    def test_reason_is_generated_before_coverage(self):
        self.assertEqual(list(CoverageJudgement.model_fields),
                         ["candidate_index", "reason", "coverage", "quote"])


class NonTechnologyExclusionTests(unittest.TestCase):
    def test_non_technology_requirements_are_excluded_and_reported(self):
        rfp = rfp_candidate("rfp-1", "과제", ["SLAM 기반 위치추정 기술 개발", "부유식 풍력 실증 주관사와 합의 필요"])
        llm = FakeLLM({"과제": [
            requirement("SLAM", "SLAM 기반 위치추정"),
            requirement("실증 주관사 합의", "부유식 풍력 실증 주관사와 합의", technology=False),
        ]})
        report = run_gap_analysis(make_state([], [rfp]), llm=llm)
        self.assertEqual([item.requirement.name for item in report.items], ["SLAM"])
        self.assertEqual(report.stats["excluded_requirements"],
                         [{"rfp": "rfp-1", "text": "실증 주관사 합의", "reason": "LLM이 기술 요구가 아니라고 판단"}])
        self.assertEqual(report.summary["추가R&D검토후보"], 1)


class DecideLabelTests(unittest.TestCase):
    @staticmethod
    def match(source, coverage, verified=True):
        return SourceMatch(source=source, element_name="x", coverage=coverage, reason="", verified=verified)

    def test_priority_table(self):
        cases = [
            (False, True, [self.match("company", "full")], [], GapLabel.INSUFFICIENT),
            (True, True, [self.match("company", "full")], [self.match("pub", "full")], GapLabel.OWNED),
            (True, True, [self.match("company", "partial")], [], GapLabel.PARTIAL),
            (True, True, [], [self.match("pub", "full")], GapLabel.EXTERNAL),
            (True, True, [], [self.match("pos", "partial")], GapLabel.PARTIAL),
            (True, True, [], [self.match("pub", "full", verified=False)], GapLabel.RND_NEEDED),
            (True, False, [], [], GapLabel.INSUFFICIENT),
        ]
        for verified, clear, company, external, expected in cases:
            with self.subTest(expected=expected, company=company, external=external):
                label, _ = decide_label(requirement_verified=verified, requirement_clear=clear,
                                        company=company, external=external)
                self.assertEqual(label, expected)


if __name__ == "__main__":
    unittest.main()
