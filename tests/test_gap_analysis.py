import json
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.common.schemas import (
    Evidence, ExternalTechCandidate, GapLabel, ModuleResult, RetrievalHit, TechElement,
)
from app.gap_analysis import (
    BatchJudgement, BatchJudgements, GapReport, OpenAIStructuredLLM, RequirementExtraction,
    SourceMatch, decide_label, run_gap_analysis,
)
from app.orchestrator import AnalysisRequest, AnalysisState


NL = chr(10)


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


def make_state(owned, rfp_candidates, *, external=(), external_candidates=(), ntis=(), tech_hits=()):
    return AnalysisState(
        request=AnalysisRequest(problem="작업자와 지게차의 충돌을 줄이고 싶다.", owned_technologies=owned),
        technology=ModuleResult(module="technology", query="q", candidates=list(external_candidates),
                                hits=list(tech_hits)),
        ntis=ModuleResult(module="ntis", query="q"),
        rfp=ModuleResult(module="rfp", query="q", candidates=list(rfp_candidates)),
        external_elements=list(external), ntis_elements=list(ntis),
    )


def unrelated_external():
    """요구기술과 무관한 기술나눔 기술. 기술나눔 후보가 있는 상태에서 매칭이 없는 경우를 만든다."""
    return tech_element("냉각수 순환", "pos", "pos-9", "냉각수 순환 펌프 제어")


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
        judgements = []
        for requirement in payload["requirements"]:
            for candidate in payload["candidates"]:
                coverage, quote = self.coverage.get((requirement["name"], candidate["name"]), ("none", ""))
                judgements.append({"requirement_index": requirement["index"], "candidate_index": candidate["index"],
                                   "coverage": coverage, "reason": "테스트 판단", "quote": quote})
        return BatchJudgements(judgements=judgements)


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
            ("센서 융합", "카메라 센서 융합 모듈"): ("partial", "센서 융합"),
            ("센서 융합", "센서 융합"): ("full", "센서 융합"),
        }, owned=("카메라 센서 융합 모듈",))
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

    def test_s01_s02_incidental_external_overlap_is_rejected(self):
        cases = [
            ("중온 열원용 고효율 터빈 개발", "연소로의 열회수장치",
             "초고온 배가스 폐열을 회수하기 위한 고효율 열회수장치"),
            ("발전 전력의 소내 재활용을 통한 에너지 저감량 검증", "연소로의 열회수장치",
             "용융염으로 배가스 현열을 회수하여 증기 생산에 활용"),
            ("위험도 기반 제설 경로 계획 소프트웨어 설계", "제설기용 삽날의 노면 접지압력 조정장치",
             "제설기 삽날과 노면의 접지압력을 일정하게 유지"),
            ("보더링 압력 스트로크 정렬 조건 제어변수 보정", "제설기용 삽날의 노면 접지압력 조정장치",
             "압력조정수단으로 제설기 삽날의 접지압력을 조정"),
        ]
        for required, offered, quote in cases:
            with self.subTest(required=required):
                rfp = rfp_candidate("rfp-1", "과제", [required])
                external = tech_element(offered, "pub", "pub-1", quote)
                llm = FakeLLM({"과제": [requirement(required, required)]},
                              {(required, offered): ("full", quote)})
                item = run_gap_analysis(make_state([], [rfp], external=[external]), llm=llm).items[0]
                self.assertFalse(item.external[0].verified)
                self.assertEqual(item.label, GapLabel.RND_NEEDED)

    def test_specific_external_function_and_target_still_match(self):
        required = "제설 작업부 노면 접지압력 조정"
        offered = "제설기용 삽날의 노면 접지압력 조정장치"
        quote = "제설기 삽날과 노면의 접지압력을 일정하게 유지하고 조정"
        rfp = rfp_candidate("rfp-1", "과제", [required])
        llm = FakeLLM({"과제": [requirement(required, required)]}, {(required, offered): ("full", quote)})
        item = run_gap_analysis(make_state([], [rfp], external=[tech_element(offered, "pub", "pub-1", quote)]),
                                llm=llm).items[0]
        self.assertTrue(item.external[0].verified)
        self.assertEqual(item.label, GapLabel.EXTERNAL)

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
        item = run_gap_analysis(make_state([], [rfp], external=[unrelated_external()]), llm=llm).items[0]
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

    def test_trailing_punctuation_added_by_llm_is_ignored(self):
        for suffix in (".", " .", "。", ",", "…"):
            with self.subTest(suffix=suffix):
                item, evidence = self.run_quote(["SLAM 기반 위치추정 기술 개발"], "SLAM 기반 위치추정 기술 개발" + suffix)
                self.assertTrue(evidence.verified)
                self.assertEqual(evidence.quote, "SLAM 기반 위치추정 기술 개발")  # 저장되는 근거는 원문 그대로
                self.assertEqual(item.label, GapLabel.RND_NEEDED)

    def test_meaningful_closing_bracket_is_not_trimmed(self):
        item, evidence = self.run_quote(["지속학습 및 자가진화(Self-evolving)"], "자가진화(Self-evolving)")
        self.assertTrue(evidence.verified)
        self.assertEqual(evidence.quote, "자가진화(Self-evolving)")

    def test_trailing_punctuation_on_match_quote_is_ignored(self):
        rfp = rfp_candidate("rfp-1", "과제", ["SLAM 기반 위치추정 기술 개발"])
        llm = FakeLLM({"과제": [requirement("SLAM", "SLAM 기반 위치추정")]},
                      {("SLAM", "SLAM 기반 위치추정"): ("full", "SLAM 기반 위치추정.")})
        item = run_gap_analysis(make_state(["SLAM 기반 위치추정"], [rfp]), llm=llm).items[0]
        self.assertTrue(item.company[0].verified)
        self.assertEqual(item.label, GapLabel.OWNED)

    def test_changed_wording_is_still_rejected(self):
        item, evidence = self.run_quote(["SLAM 기반 위치추정 기술 개발"], "원문과 다르게 바꿔 쓴 문장")
        self.assertFalse(evidence.verified)
        self.assertEqual(item.label, GapLabel.INSUFFICIENT)

    def test_reason_is_generated_before_coverage(self):
        self.assertEqual(list(BatchJudgement.model_fields),
                         ["requirement_index", "candidate_index", "reason", "coverage", "quote"])


class NonTechnologyExclusionTests(unittest.TestCase):
    def test_non_technology_requirements_are_excluded_and_reported(self):
        rfp = rfp_candidate("rfp-1", "과제", ["SLAM 기반 위치추정 기술 개발", "부유식 풍력 실증 주관사와 합의 필요"])
        llm = FakeLLM({"과제": [
            requirement("SLAM", "SLAM 기반 위치추정"),
            requirement("실증 주관사 합의", "부유식 풍력 실증 주관사와 합의", technology=False),
        ]})
        report = run_gap_analysis(make_state([], [rfp], external=[unrelated_external()]), llm=llm)
        self.assertEqual([item.requirement.name for item in report.items], ["SLAM"])
        self.assertEqual(report.stats["excluded_requirements"],
                         [{"rfp": "rfp-1", "text": "실증 주관사 합의", "reason": "LLM이 기술 요구가 아니라고 판단"}])
        self.assertEqual(report.summary["추가R&D검토후보"], 1)


def tech_candidate(doc_id, title, provider="포스코그룹", condition="통상실시"):
    return ExternalTechCandidate(doc_id=doc_id, title=title, provider=provider, transfer_condition=condition,
                                 relevance_score=0.5, relation_summary="")


def tech_hit(doc_id, text, rank=1, source="pos"):
    return RetrievalHit(chunk_id=f"{doc_id}#{rank}", doc_id=doc_id, source=source, text=text, final_rank=rank)


class CandidatePoolTests(unittest.TestCase):
    """기술요소로 추출되지 않은 기술나눔 후보도 검색 본문으로 비교한다."""

    def setUp(self):
        self.rfp = rfp_candidate("rfp-1", "과제", ["설비 베어링 이상 실시간 감지 기술 개발"])
        self.hit_text = "베어링 이탈 검출장치 (실시간 이상 진단)\n[기술 개요]\n기울기 센서로 베어링 이탈을 실시간 감지"
        self.name = "베어링 이탈 검출장치 (실시간 이상 진단)"

    def test_candidate_without_element_is_compared_using_hit_body(self):
        llm = FakeLLM({"과제": [requirement("베어링 이상 감지", "베어링 이상 실시간 감지")]},
                      {("베어링 이상 감지", self.name): ("full", "기울기 센서로 베어링 이탈을 실시간 감지")})
        state = make_state([], [self.rfp], external_candidates=[tech_candidate("pos-1", "베어링 이탈 검출장치")],
                           tech_hits=[tech_hit("pos-1", self.hit_text)])
        report = run_gap_analysis(state, llm=llm)
        item = report.items[0]
        self.assertEqual(item.label, GapLabel.EXTERNAL)
        match = item.external[0]
        self.assertEqual((match.doc_id, match.provider, match.transfer_condition),
                         ("pos-1", "포스코그룹", "통상실시"))
        # 기술명 접두어와 섹션 제목 줄은 근거에서 빠진다
        self.assertEqual(match.evidences[0].quote, "기울기 센서로 베어링 이탈을 실시간 감지")
        self.assertEqual(match.evidences[0].extra["from"], "retrieval_hit")
        self.assertEqual(report.stats["pool_size"]["technology"], 1)

    def test_document_already_covered_by_element_is_not_duplicated(self):
        element = tech_element("베어링 이탈 감지", "pos", "pos-1", "기울기 센서로 베어링 이탈을 실시간 감지")
        llm = FakeLLM({"과제": [requirement("베어링 이상 감지", "베어링 이상 실시간 감지")]})
        state = make_state([], [self.rfp], external=[element],
                           external_candidates=[tech_candidate("pos-1", "베어링 이탈 검출장치")],
                           tech_hits=[tech_hit("pos-1", self.hit_text)])
        run_gap_analysis(state, llm=llm)
        names = [c["name"] for c in llm.alignment_payloads[0]["candidates"]]
        self.assertEqual(names, ["베어링 이탈 감지"])

    def test_candidate_without_hits_is_skipped(self):
        llm = FakeLLM({"과제": [requirement("베어링 이상 감지", "베어링 이상 실시간 감지")]})
        state = make_state([], [self.rfp], external_candidates=[tech_candidate("pos-1", "베어링 이탈 검출장치")])
        report = run_gap_analysis(state, llm=llm)
        self.assertEqual(report.stats["pool_size"]["technology"], 0)
        self.assertTrue(any("기술나눔 후보가 없어" in w for w in report.warnings))


MULTI_SECTION_TEXT = NL.join([
    "난방배관 관리 시스템 (수처리·이상 진단)",
    "[기술 개요]",
    "본 기술은 난방배관 회수관에서 수질을 측정하여 배관 이상 유무를 판단함",
    "약품 소모 속도로 배관 이상을 판단함",
    "[산업계 문제 해결 포인트]",
    "배관 이상 발생 시 조기 발견이 어려워 누수가 대형 사고로 이어짐",
    "[주요 적용 산업 및 활용처]",
    "지역난방 열병합 아파트 공공건축물",
    "[시장성 및 사업화 가능성]",
    "글로벌 지역난방 시장 연평균 6~7% 성장 전망",
]) + NL


def compact(text):
    """팀원의 최종 답변 검증(app/final_answer.py)과 같은 규칙: 공백을 모두 없앤 뒤 연속 포함 여부 확인."""
    return "".join(text.split())


class HitEvidenceTests(unittest.TestCase):
    """검색 본문 근거는 원문 청크의 연속된 부분이어야 한다 (최종 답변의 인용 검증과 맞물림)."""

    def test_sections_are_split_and_never_joined_across_titles(self):
        from app.gap_analysis import _hit_bodies
        bodies = _hit_bodies(MULTI_SECTION_TEXT)
        self.assertEqual(len(bodies), 2)  # 적용 산업, 시장성 섹션은 제외
        self.assertTrue(bodies[0].startswith("본 기술은 난방배관 회수관"))
        self.assertIn("약품 소모 속도로 배관 이상을 판단함", bodies[0])  # 같은 섹션의 두 줄은 이어 붙임
        self.assertNotIn("배관 이상 발생 시", bodies[0])
        self.assertTrue(bodies[1].startswith("배관 이상 발생 시"))
        for body in bodies:
            self.assertIn(compact(body), compact(MULTI_SECTION_TEXT))

    def test_pool_evidence_passes_the_final_answer_containment_check(self):
        from app.gap_analysis import build_pool
        hit = tech_hit("pub-1", MULTI_SECTION_TEXT, source="pub")
        state = make_state([], [rfp_candidate("rfp-1", "과제", ["배관 이상 감지 기술 개발"])],
                           external_candidates=[tech_candidate("pub-1", "난방배관 관리 시스템", "한국지역난방공사")],
                           tech_hits=[hit])
        evidences = [ev for item in build_pool(state) for ev in item.element.evidences
                     if ev.extra.get("from") == "retrieval_hit"]
        self.assertEqual(len(evidences), 2)
        for evidence in evidences:
            self.assertIn(compact(evidence.quote), compact(hit.text))

    def test_market_only_chunk_gives_no_evidence(self):
        from app.gap_analysis import _hit_bodies
        text = NL.join(["기술명", "[주요 적용 산업 및 활용처]", "철강 산업", "[시장성 및 사업화 가능성]", "시장 규모 전망"])
        self.assertEqual(_hit_bodies(text), [])

    def test_long_section_is_truncated_but_stays_contiguous(self):
        from app.gap_analysis import HIT_QUOTE_CHARS, _hit_bodies
        line = "배관 누수 신호와 압력강하율을 비교 판단함 " * 40
        text = NL.join(["기술명", "[기술 개요]", line])
        (body,) = _hit_bodies(text)
        self.assertLessEqual(len(body), HIT_QUOTE_CHARS)
        self.assertIn(compact(body), compact(text))

    def test_evidence_count_per_candidate_is_capped_across_hits(self):
        from app.gap_analysis import HITS_PER_CANDIDATE, build_pool
        hits = [tech_hit("pub-1", MULTI_SECTION_TEXT, rank=1, source="pub"),
                tech_hit("pub-1", MULTI_SECTION_TEXT, rank=2, source="pub")]
        state = make_state([], [rfp_candidate("rfp-1", "과제", ["배관 이상 감지 기술 개발"])],
                           external_candidates=[tech_candidate("pub-1", "난방배관 관리 시스템")], tech_hits=hits)
        (item,) = [i for i in build_pool(state) if i.doc_id == "pub-1"]
        self.assertEqual(len(item.element.evidences), HITS_PER_CANDIDATE)


class RfpSelectionTests(unittest.TestCase):
    def setUp(self):
        self.rfps = [rfp_candidate(f"rfp-{i}", f"과제{i}", [f"요구 기술 {i}번 개발"]) for i in (1, 2, 3)]
        self.llm = FakeLLM({f"과제{i}": [requirement(f"기술{i}", f"요구 기술 {i}번")] for i in (1, 2, 3)})

    def test_only_top_rfps_are_analyzed_by_default(self):
        report = run_gap_analysis(make_state([], self.rfps), llm=self.llm)
        self.assertEqual([i.rfp_doc_ids[0] for i in report.items], ["rfp-1", "rfp-2"])
        self.assertEqual(report.stats["rfps_analyzed"], ["rfp-1", "rfp-2"])
        self.assertEqual(report.stats["rfps_skipped"], ["rfp-3"])

    def test_none_analyzes_all_rfps(self):
        report = run_gap_analysis(make_state([], self.rfps), llm=self.llm, max_rfps=None)
        self.assertEqual(len(report.items), 3)
        self.assertEqual(report.stats["rfps_skipped"], [])

    def test_invalid_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            run_gap_analysis(make_state([], self.rfps), llm=self.llm, max_rfps=0)


class NonTechnologyNameRuleTests(unittest.TestCase):
    def test_rule_excludes_items_the_llm_marked_as_technology(self):
        rfp = rfp_candidate("rfp-1", "과제", ["시제품 제작 및 SLAM 기반 위치추정 기술 개발"])
        llm = FakeLLM({"과제": [requirement("시제품 제작 기술", "시제품 제작"),
                                requirement("SLAM", "SLAM 기반 위치추정")]})
        report = run_gap_analysis(make_state([], [rfp]), llm=llm)
        self.assertEqual([i.requirement.name for i in report.items], ["SLAM"])
        self.assertEqual(report.stats["excluded_requirements"][0]["reason"], "비기술 항목 단어: 시제품")


class ParallelAndCacheTests(unittest.TestCase):
    def test_parallel_run_gives_same_result_in_same_order(self):
        lines = [f"센서 {i}번 융합 기술 개발" for i in range(8)]
        rfp = rfp_candidate("rfp-1", "과제", lines)
        extraction = {"과제": [requirement(f"센서{i}", f"센서 {i}번 융합") for i in range(8)]}
        coverage = {(f"센서{i}", "센서 융합"): ("partial" if i % 2 else "full", "센서 융합") for i in range(8)}
        state = make_state(["센서 융합"], [rfp])
        serial = run_gap_analysis(state, llm=FakeLLM(extraction, coverage), workers=1)
        parallel = run_gap_analysis(state, llm=FakeLLM(extraction, coverage), workers=4)
        self.assertEqual(serial.model_dump(exclude={"stats"}), parallel.model_dump(exclude={"stats"}))

    def test_cache_reuses_response_for_same_input(self):
        calls = []
        lock = threading.Lock()

        def parse(**kwargs):
            with lock:
                calls.append(kwargs["messages"])
            parsed = kwargs["response_format"](requirements=[])
            message = SimpleNamespace(refusal=None, parsed=parsed)
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                                   choices=[SimpleNamespace(message=message)])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
        with tempfile.TemporaryDirectory() as cache_dir:
            llm = OpenAIStructuredLLM(client=client, cache_dir=cache_dir)
            messages = [{"role": "user", "content": "같은 입력"}]
            first = llm(messages, RequirementExtraction)
            second = llm(messages, RequirementExtraction)
            llm([{"role": "user", "content": "다른 입력"}], RequirementExtraction)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2)                    # 같은 입력은 한 번만 호출
        self.assertEqual(llm.usage["cache_hits"], 1)
        self.assertEqual(llm.usage["prompt_tokens"], 20)   # 캐시 응답은 토큰을 쓰지 않는다


class OmittedCandidatesTests(unittest.TestCase):
    """LLM이 관련 없는 후보를 응답에서 생략해도 none으로 처리한다."""

    class OmittingLLM(FakeLLM):
        def __call__(self, messages, response_model):
            answer = super().__call__(messages, response_model)
            if response_model is BatchJudgements:
                answer = BatchJudgements(
                    judgements=[j for j in answer.judgements if j.coverage != "none"])
            return answer

    def test_omitted_candidates_are_treated_as_no_match(self):
        rfp = rfp_candidate("rfp-1", "과제", ["SLAM 기반 위치추정 기술 개발"])
        llm = self.OmittingLLM({"과제": [requirement("SLAM", "SLAM 기반 위치추정")]},
                               {("SLAM", "SLAM 기반 위치추정"): ("full", "SLAM 기반 위치추정")})
        state = make_state(["SLAM 기반 위치추정", "용접 로봇 제어"], [rfp])
        item = run_gap_analysis(state, llm=llm).items[0]
        self.assertEqual([m.element_name for m in item.company], ["SLAM 기반 위치추정"])
        self.assertEqual(item.label, GapLabel.OWNED)

    def test_empty_judgement_list_means_no_match(self):
        rfp = rfp_candidate("rfp-1", "과제", ["SLAM 기반 위치추정 기술 개발"])
        llm = self.OmittingLLM({"과제": [requirement("SLAM", "SLAM 기반 위치추정")]})
        state = make_state(["용접 로봇 제어"], [rfp], external=[unrelated_external()])
        item = run_gap_analysis(state, llm=llm).items[0]
        self.assertEqual((item.company, item.label), ([], GapLabel.RND_NEEDED))

    def test_prompt_asks_for_matches_only(self):
        from app.gap_analysis import ALIGNMENT_PROMPT
        self.assertIn("빈 목록", ALIGNMENT_PROMPT)
        self.assertNotIn("모든 후보에 대해", ALIGNMENT_PROMPT)


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


class BatchAlignmentTests(unittest.TestCase):
    """요구기술을 묶어 판단해도 결과는 같고 LLM 호출만 줄어든다. NTIS는 코드로 참고 근거만 붙인다."""

    def setUp(self):
        self.lines = [f"센서{i}번 융합 기술 개발" for i in range(12)]
        self.rfp = rfp_candidate("rfp-1", "과제", self.lines)
        self.extraction = {"과제": [requirement(f"센서{i}", f"센서{i}번 융합") for i in range(12)]}
        self.coverage = {(f"센서{i}", "센서 융합"): ("full", "센서 융합") for i in range(12)}

    def alignment_calls(self, batch_size):
        llm = FakeLLM(self.extraction, self.coverage)
        report = run_gap_analysis(make_state(["센서 융합"], [self.rfp]), llm=llm, batch_size=batch_size)
        return report, len(llm.alignment_payloads)

    def test_requirements_are_batched_into_fewer_calls(self):
        report, calls = self.alignment_calls(10)
        self.assertEqual(calls, 2)                      # 12개 -> 10개 + 2개
        self.assertEqual(len(report.items), 12)
        self.assertEqual({item.label for item in report.items}, {GapLabel.OWNED})

    def test_batch_size_does_not_change_report(self):
        one, calls_one = self.alignment_calls(1)
        ten, _ = self.alignment_calls(10)
        self.assertEqual(calls_one, 12)
        self.assertEqual(one.model_dump(exclude={"stats"}), ten.model_dump(exclude={"stats"}))

    def test_invalid_batch_size_is_rejected(self):
        with self.assertRaises(ValueError):
            run_gap_analysis(make_state([], [self.rfp]), llm=FakeLLM({}), batch_size=0)

    def test_ntis_is_never_sent_to_llm_but_attached_as_reference(self):
        ntis = tech_element("센서3번 융합", "ntis", "ntis-1", "센서3번 융합 선행 연구")
        state = make_state(["센서 융합"], [self.rfp], ntis=[ntis])
        llm = FakeLLM(self.extraction, self.coverage)
        report = run_gap_analysis(state, llm=llm)
        sent = {c["source"] for payload in llm.alignment_payloads for c in payload["candidates"]}
        self.assertNotIn("ntis", sent)
        item = {i.requirement.name: i for i in report.items}["센서3"]
        self.assertEqual([m.doc_id for m in item.ntis_references], ["ntis-1"])
        self.assertEqual(item.ntis_references[0].coverage, "none")


class NoExternalCandidateTests(unittest.TestCase):
    """기술나눔 후보가 없고 보유기술 근거도 없으면 추가 R&D가 아니라 근거부족이다."""

    def run_one(self, owned, coverage=None, external=()):
        rfp = rfp_candidate("rfp-1", "과제", ["SLAM 기반 위치추정 기술 개발"])
        llm = FakeLLM({"과제": [requirement("SLAM", "SLAM 기반 위치추정")]}, coverage)
        return run_gap_analysis(make_state(owned, [rfp], external=list(external)), llm=llm).items[0]

    def test_no_candidates_and_no_company_match_is_insufficient(self):
        item = self.run_one(["용접 로봇 제어"])
        self.assertEqual(item.label, GapLabel.INSUFFICIENT)

    def test_company_match_still_wins_without_external_candidates(self):
        item = self.run_one(["SLAM 기반 자율주행"], {("SLAM", "SLAM 기반 자율주행"): ("full", "SLAM 기반 자율주행")})
        self.assertEqual(item.label, GapLabel.OWNED)

    def test_candidates_exist_but_unmatched_stays_rnd_candidate(self):
        item = self.run_one(["용접 로봇 제어"], external=[unrelated_external()])
        self.assertEqual(item.label, GapLabel.RND_NEEDED)

    def test_decide_label_flag(self):
        label, _ = decide_label(requirement_verified=True, requirement_clear=True, company=[], external=[],
                                external_available=False)
        self.assertEqual(label, GapLabel.INSUFFICIENT)
