import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from app.query_parser import InputTechnology, ParsedQuery, ParsedQuerySpans, SourceWordSpan, parse_query


QUERY = "우리는 압연 설비 운전과 공정 데이터 수집 기술을 가지고 있는데, 압연 설비의 고장을 미리 예측하는 예지보전 체계를 개발하고자 한다. 이를 위해 파단 예측과 설비 잔존수명 예측 기술을 보완하고자 하는데, 관련 나눔기술과 공고가 있을까?"


def interpretation():
    return ParsedQuery(
        development_goal="압연 설비 고장 예측을 위한 예지보전 체계 개발",
        owned=[InputTechnology(name=name, quote="압연 설비 운전과 공정 데이터 수집 기술을 가지고 있는데")
               for name in ("압연 설비 운전", "공정 데이터 수집")],
        requested=[InputTechnology(name=name, quote="파단 예측과 설비 잔존수명 예측 기술을 보완하고자 하는데")
                   for name in ("파단 예측", "설비 잔존수명 예측")],
        policy_question=None,
    )


class QueryParserTests(unittest.TestCase):
    def test_retry_selects_original_word_spans_without_rewriting_source(self):
        query = 'owned A provided. need B requested.'
        invalid = ParsedQuery(development_goal='goal', owned=[InputTechnology(name='invented', quote=query)],
                              requested=[InputTechnology(name='B', quote=query)], policy_question=None)
        spans = ParsedQuerySpans(development_goal='goal', owned=[SourceWordSpan(start_word=0, end_word=1)],
                                 requested=[SourceWordSpan(start_word=3, end_word=4)], policy_question=None)
        llm = Mock(side_effect=[invalid, spans])
        result = parse_query(query, llm=llm)
        self.assertIs(llm.call_args.args[1], ParsedQuerySpans)
        self.assertEqual(result.request.owned_technologies, ['owned A'])
        self.assertEqual(result.request.unmet_elements, ['need B'])
        self.assertEqual(result.parsed.owned[0].quote, query)
        self.assertEqual(result.extraction_method, 'word_spans')

    def test_span_repair_rejects_out_of_bounds_and_dropped_roles(self):
        invalid = interpretation()
        invalid.owned[0].quote = 'not in source'
        for spans in (
            ParsedQuerySpans(development_goal='goal', owned=[SourceWordSpan(start_word=0, end_word=99999)],
                             requested=[SourceWordSpan(start_word=0, end_word=1)], policy_question=None),
            ParsedQuerySpans(development_goal='goal', owned=[], requested=[], policy_question=None),
        ):
            with self.subTest(spans=spans):
                llm = Mock(side_effect=[invalid, spans])
                with self.assertRaises(ValueError):
                    parse_query(QUERY, llm=llm, max_retries=1)

    def test_source_error_is_repaired_without_accepting_paraphrased_names(self):
        invalid = interpretation()
        invalid.requested[0].name = '원문에 없는 기술명'
        llm = Mock(side_effect=[invalid, interpretation()])
        result = parse_query(QUERY, llm=llm)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(result.validation_errors), 1)
        self.assertEqual(result.request.unmet_elements, ['파단 예측', '설비 잔존수명 예측'])
        self.assertIn('validation_error', llm.call_args.args[0][-1]['content'])

    def test_source_repair_is_bounded_and_never_drops_invalid_ownership(self):
        invalid = interpretation()
        invalid.owned[0].quote = '원문에 없는 근거'
        llm = Mock(return_value=invalid)
        with self.assertRaisesRegex(ValueError, '3회'):
            parse_query(QUERY, llm=llm)
        self.assertEqual(llm.call_count, 3)

    def test_general_connection_condition_is_not_a_policy_question(self):
        query = '폐열 회수 기술을 가지고 있다. 이 연결 조건을 고려할 때 관련 나눔기술과 공고를 확인할 수 있을까?'
        parsed = ParsedQuery(development_goal='연결 검토', owned=[], requested=[],
                             policy_question='이 연결 조건을 고려할 때 관련 나눔기술과 공고를 확인할 수 있을까?')
        result = parse_query(query, llm=lambda *args: parsed)
        self.assertIsNone(result.request.policy_question)
        self.assertTrue(result.warnings)

    def test_explicit_technology_transfer_question_is_preserved(self):
        query = '기술이전 조건과 국가 R&D 참여자격을 알려주세요.'
        parsed = ParsedQuery(development_goal='제도 확인', owned=[], requested=[], policy_question=query)
        self.assertEqual(parse_query(query, llm=lambda *args: parsed).request.policy_question, query)

    def test_api_errors_are_not_treated_as_extractable_input(self):
        llm = Mock(side_effect=RuntimeError('API error'))
        with self.assertRaisesRegex(RuntimeError, 'API error'):
            parse_query(QUERY, llm=llm)
        self.assertEqual(llm.call_count, 1)

    def test_natural_question_retains_original_and_distinguishes_requested_technology(self):
        result = parse_query(QUERY, llm=lambda *args: interpretation())
        self.assertEqual(result.request.problem, QUERY)
        self.assertEqual(result.request.owned_technologies, ["압연 설비 운전", "공정 데이터 수집"])
        self.assertEqual(result.request.unmet_elements, ["파단 예측", "설비 잔존수명 예측"])
        self.assertIsNone(result.request.policy_question)

    def test_invented_technology_or_quote_is_rejected(self):
        parsed = interpretation()
        parsed.owned[0].name = "딥러닝 모델 개발"
        with self.assertRaises(ValueError):
            parse_query(QUERY, llm=lambda *args: parsed)

    def test_no_declared_ownership_is_preserved_as_empty(self):
        parsed = ParsedQuery(development_goal="설비 고장 예측", owned=[], requested=[], policy_question=None)
        result = parse_query("설비 고장을 예측할 기술과 공고가 있을까요?", llm=lambda *args: parsed)
        self.assertEqual(result.request.owned_technologies, [])
        self.assertTrue(result.warnings)

    def test_invented_legal_question_is_rejected(self):
        parsed = interpretation()
        parsed.policy_question = "신청자격을 알려주세요."
        with self.assertRaises(ValueError):
            parse_query(QUERY, llm=lambda *args: parsed)

    def test_cli_question_file_input_can_be_reviewed_before_retrieval(self):
        from app.scripts.run_analysis import main
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "question.txt"
            source.write_text(QUERY, encoding="utf-8")
            with patch("app.scripts.run_analysis.OpenAIStructuredLLM", return_value=lambda *args: interpretation()), \
                 redirect_stdout(io.StringIO()):
                result = main(["--query-file", str(source), "--parse-only", "--output-dir", str(root / "result")])
            self.assertEqual(result, 0)
            self.assertIn(QUERY, (root / "result" / "input.json").read_text(encoding="utf-8"))
            self.assertFalse((root / "result" / "state.json").exists())

    def test_interactive_question_accepts_a_single_sentence(self):
        from app.scripts.run_analysis import main
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "result"
            with patch("builtins.input", return_value=QUERY), \
                 patch("app.scripts.run_analysis.OpenAIStructuredLLM", return_value=lambda *args: interpretation()), \
                 redirect_stdout(io.StringIO()):
                result = main(["--parse-only", "--output-dir", str(target)])
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
