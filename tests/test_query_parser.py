import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app.query_parser import InputTechnology, ParsedQuery, parse_query


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
