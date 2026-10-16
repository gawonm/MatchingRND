import re
import unittest

from app.common.schemas import Evidence, ExternalTechCandidate, GapLabel, ModuleResult, TechElement
from app.gap_analysis import GapReport
from app.gap_analysis_local import LocalThresholds, run_gap_analysis_local
from app.orchestrator import AnalysisRequest, AnalysisState


def tokenize(text):
    """Kiwi 없이 공백·기호 기준으로 나누는 테스트용 토크나이저."""
    return [w.lower() for w in re.findall(r"[가-힣A-Za-z]{2,}|\d{2,}", text)]


def rfp_candidate(doc_id, lines, item="요구기술", extra_items=None):
    def fragments(texts):
        return [{"text": t, "page": 3, "bbox": [1, 2, 3, 4], "source": "rfp.pdf", "source_kind": "text"}
                for t in texts]
    requirements = {item: fragments(lines), **{k: fragments(v) for k, v in (extra_items or {}).items()}}
    return ExternalTechCandidate(doc_id=doc_id, title=f"{doc_id} 과제", relevance_score=0.9,
                                 relation_summary="", extra={"requirements": requirements})


def tech_element(name, source, doc_id, quote):
    return TechElement(element_id=f"te-{name}", name=name, origin=source,
                       evidences=[Evidence(doc_id=doc_id, source=source, quote=quote, verified=True)])


def make_state(owned, rfps, *, external=(), candidates=(), ntis=()):
    return AnalysisState(
        request=AnalysisRequest(problem="작업자와 지게차의 충돌을 줄이고 싶다.", owned_technologies=list(owned)),
        technology=ModuleResult(module="technology", query="q", candidates=list(candidates)),
        ntis=ModuleResult(module="ntis", query="q"),
        rfp=ModuleResult(module="rfp", query="q", candidates=list(rfps)),
        external_elements=list(external), ntis_elements=list(ntis),
    )


class LocalGapScenarioTests(unittest.TestCase):
    def setUp(self):
        rfp = rfp_candidate("rfp-1", [
            "SLAM 기반 위치추정 기술 개발",
            "LiDAR 동적 객체 인지 기술 확보",
            "Edge 실시간 추론 최적화 기술 개발",
        ], extra_items={"성능지표": ["위치추정 정확도 5cm 이하 달성 목표"]})
        external = tech_element("LiDAR 객체 인지", "pub", "pub-2026-001", "3D LiDAR 점군으로 동적 객체를 인지")
        candidate = ExternalTechCandidate(
            doc_id="pub-2026-001", title="LiDAR 객체 인지 기술", provider="한국기계연구원",
            transfer_condition="통상실시", relevance_score=0.8, relation_summary="")
        ntis = tech_element("Edge 추론", "ntis", "ntis-1", "Edge 실시간 추론 최적화 연구")
        self.state = make_state(["SLAM 기반 위치추정", "영상 객체 인식"], [rfp], external=[external],
                                candidates=[candidate], ntis=[ntis])
        self.report = run_gap_analysis_local(self.state, tokenizer=tokenize)
        self.items = {item.requirement.surface_forms[0]: item for item in self.report.items}

    def test_labels_and_method(self):
        self.assertEqual(self.report.method, "local")
        self.assertEqual(self.items["SLAM 기반 위치추정 기술 개발"].label, GapLabel.OWNED)
        self.assertEqual(self.items["LiDAR 동적 객체 인지 기술 확보"].label, GapLabel.EXTERNAL)
        # NTIS에서만 비슷한 기술이 있어도 판정 근거가 되지 않는다.
        item = self.items["Edge 실시간 추론 최적화 기술 개발"]
        self.assertEqual(item.label, GapLabel.RND_NEEDED)
        self.assertEqual(item.ntis_references[0].doc_id, "ntis-1")

    def test_only_technology_items_are_requirements(self):
        self.assertEqual(len(self.report.items), 3)
        self.assertFalse(any("정확도" in name for name in self.items))

    def test_external_match_carries_source_information(self):
        match = self.items["LiDAR 동적 객체 인지 기술 확보"].external[0]
        self.assertEqual((match.provider, match.transfer_condition, match.doc_id),
                         ("한국기계연구원", "통상실시", "pub-2026-001"))
        self.assertIn("로컬 점수 판정", match.reason)
        self.assertEqual(match.evidences[0].quote, "3D LiDAR 점군으로 동적 객체를 인지")

    def test_requirement_evidence_points_to_rfp_location(self):
        evidence = self.items["SLAM 기반 위치추정 기술 개발"].requirement.evidences[0]
        self.assertEqual((evidence.doc_id, evidence.section, evidence.page), ("rfp-1", "요구기술", 2))
        self.assertTrue(evidence.verified)

    def test_stats_report_no_llm_usage_and_json_roundtrip(self):
        self.assertEqual(self.report.stats["calls"], 0)
        self.assertFalse(self.report.stats["embedding"])
        self.assertEqual(GapReport.model_validate_json(self.report.model_dump_json()), self.report)
        self.assertEqual(self.report.owned_not_required, ["영상 객체 인식"])


class LocalGapRuleTests(unittest.TestCase):
    def run_one(self, owned, line="SLAM 기반 위치추정 기술 개발", **kwargs):
        state = make_state(owned, [rfp_candidate("rfp-1", [line])],
                           external=[tech_element("냉각수 순환", "pos", "pos-9", "냉각수 순환 펌프 제어")])
        return run_gap_analysis_local(state, tokenizer=tokenize, **kwargs).items[0]

    def test_partial_when_only_some_keywords_match(self):
        item = self.run_one(["SLAM 자율주행"])
        self.assertEqual(item.label, GapLabel.PARTIAL)
        self.assertEqual(item.company[0].coverage, "partial")

    def test_no_shared_keyword_means_no_match(self):
        item = self.run_one(["용접 로봇 제어"])
        self.assertEqual(item.company, [])
        self.assertEqual(item.label, GapLabel.RND_NEEDED)

    def test_thresholds_change_the_outcome(self):
        strict = self.run_one(["SLAM 자율주행"], thresholds=LocalThresholds(partial=0.9, full=0.95))
        self.assertEqual(strict.label, GapLabel.RND_NEEDED)

    def test_embedding_cannot_create_a_match_without_shared_keywords(self):
        item = self.run_one(["용접 로봇 제어"], embed=lambda texts: [[1.0, 0.0] for _ in texts])
        self.assertEqual(item.company, [])

    def test_embedding_score_is_used_and_reported(self):
        embed = lambda texts: [[1.0, 0.0] for _ in texts]
        item = self.run_one(["SLAM 자율주행"], embed=embed)
        self.assertIn("임베딩 1.00", item.company[0].reason)
        self.assertEqual(item.label, GapLabel.OWNED)  # 0.6 × 1.0 + 0.4 × 0.5 = 0.80 ≥ full, keyword 0.5

    def test_duplicate_lines_across_rfps_are_merged_and_short_lines_skipped(self):
        rfps = [rfp_candidate("rfp-1", ["□ SLAM 기반 위치추정 기술 개발", "요구기술"]),
                rfp_candidate("rfp-2", ["1) SLAM 기반 위치추정 기술 개발", "짧은 줄"])]
        report = run_gap_analysis_local(make_state([], rfps), tokenizer=tokenize)
        self.assertEqual(len(report.items), 1)
        self.assertEqual(report.items[0].rfp_doc_ids, ["rfp-1", "rfp-2"])
        self.assertEqual(len(report.items[0].requirement.evidences), 2)

    def test_empty_rfp_and_missing_requirement_items(self):
        report = run_gap_analysis_local(make_state(["SLAM"], []), tokenizer=tokenize)
        self.assertEqual((report.method, report.items), ("local", []))
        only_metrics = rfp_candidate("rfp-9", [], item="성능지표")
        report = run_gap_analysis_local(make_state([], [only_metrics]), tokenizer=tokenize)
        self.assertEqual(report.items, [])
        self.assertTrue(any("rfp-9" in w for w in report.warnings))


def fragment(text, *, page=3, kind="text"):
    return {"text": text, "page": page, "bbox": [1, 2, 3, 4], "source": "rfp.pdf", "source_kind": kind}


def candidate_with(items, doc_id="rfp-1"):
    return ExternalTechCandidate(doc_id=doc_id, title=f"{doc_id} 과제", relevance_score=0.9, relation_summary="",
                                 extra={"requirements": items})


class LocalExtractionTests(unittest.TestCase):
    """PDF 줄바꿈·표·소제목·비기술 항목 처리."""

    def extract(self, items, **kwargs):
        state = make_state([], [candidate_with(items)])
        report = run_gap_analysis_local(state, tokenizer=tokenize, **kwargs)
        return report, [item.requirement.surface_forms[0] for item in report.items]

    def test_wrapped_lines_are_merged_into_one_sentence(self):
        long_line = "ㅇ 반잠수식 부유체 계류시스템의 핵심부품 중 국내 기술의 실해역 실증을 통하여 상용"
        report, names = self.extract({"개발목표": [fragment(long_line), fragment("프로젝트 적용에 요구되는 트랙레코드 확보")]})
        self.assertEqual(len(names), 1)
        self.assertIn("실증을 통하여 상용 프로젝트 적용에 요구되는", names[0])
        evidence = report.items[0].requirement.evidences[0]
        self.assertEqual(len(evidence.extra["locations"]), 2)
        self.assertIsNone(evidence.bbox)

    def test_short_lines_are_not_merged(self):
        _, names = self.extract({"요구기술": [fragment("SLAM 기반 위치추정 기술 개발"),
                                              fragment("LiDAR 동적 객체 인지 기술 확보")]})
        self.assertEqual(len(names), 2)

    def test_bulleted_lines_start_new_items_and_bullets_are_removed(self):
        _, names = self.extract({"개발내용": [fragment("ㅇ 부유식 실증에 적용을 위한 국산 계류시스템 핵심 요소부품 선정"),
                                              fragment("※ 페어리드, 계류선, 앵커, 부속재 등 요소부품 목록 정리")]})
        self.assertEqual(names[0], "부유식 실증에 적용을 위한 국산 계류시스템 핵심 요소부품 선정")
        self.assertEqual(len(names), 2)

    def test_table_row_is_split_by_cells_and_labels_are_dropped(self):
        row = ("연차별\n기술\n개발 | 1차\n년도 | ∙ 폐열활용을 위한 공정 분석 및 요소 기술 확보\n"
               "- 주조 핵심 공정 분석을 통한 개선 공정 도출")
        _, names = self.extract({"개발내용": [fragment(row, kind="table_row")]})
        self.assertEqual(names, ["폐열활용을 위한 공정 분석 및 요소 기술 확보", "주조 핵심 공정 분석을 통한 개선 공정 도출"])

    def test_metric_table_is_skipped_and_titles_are_dropped(self):
        _, names = self.extract({"개발내용": [
            fragment("성능지표: CO 배출량 저감\n2 | 단위: % | 개발 목표치: 15% 이상", kind="metric_table"),
            fragment("□ 개발내용"), fragment("1. 개념 및 개발내용"), fragment("ㅇ 센서 융합 기반 노면 인식 알고리즘 개발")]})
        self.assertEqual(names, ["센서 융합 기반 노면 인식 알고리즘 개발"])

    def test_non_technology_items_are_excluded_and_reported(self):
        report, names = self.extract({"개발내용": [
            fragment("ㅇ 센서 융합 기반 노면 인식 알고리즘 개발"),
            fragment("※ MW급 부유식 실증 주관사 합의"),
            fragment("※ 성능 검증 방법 및 결과 포함 시제품에 대한 인증 필수"),
            fragment("- 연구개발계획서 제출시 정량적 평가방법 제시 필요")]})
        self.assertEqual(names, ["센서 융합 기반 노면 인식 알고리즘 개발"])
        excluded = report.stats["excluded_requirements"]
        self.assertEqual([row["reason"] for row in excluded],
                         ["비기술 항목 단어: 주관사", "비기술 항목 단어: 인증", "비기술 항목 단어: 계획서"])

    def test_technical_requirement_with_proposal_wording_is_kept(self):
        _, names = self.extract({"개발내용": [fragment("ㅇ 이기종 모빌리티 연동을 위한 표준 API 및 프로토콜 제시")]})
        self.assertEqual(len(names), 1)

    def test_falls_back_to_other_items_when_no_requirement_item_exists(self):
        items = {"성능지표": [fragment("성능지표: CO 배출량 저감 | 개발 목표치: 15%", kind="metric_table"),
                              fragment("1차 년도 | ∙ 폐열활용을 위한 공정 분석 및 요소 기술 확보", kind="table_row")]}
        report, names = self.extract(items)
        self.assertEqual(names, ["폐열활용을 위한 공정 분석 및 요소 기술 확보"])
        self.assertTrue(any("대체했습니다" in warning for warning in report.warnings))


if __name__ == "__main__":
    unittest.main()
