import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import BaseModel

from app.gap_analysis import OpenAIStructuredLLM
from app.technology_rag.config import load_config
from app.technology_rag.generation.relevance import term_overlap


class MockModel(BaseModel):
    value: str


class MvpHardeningTests(unittest.TestCase):
    def test_default_technology_domain_guard_is_enabled(self):
        self.assertGreaterEqual(load_config().llm.min_term_overlap, 2)

    def test_domain_guard_calibration_rejects_generic_and_keeps_specific_terms(self):
        self.assertEqual(term_overlap(['케이블 절연 열화 진단'], ['철도 전기설비 실시간 진단 시스템']), 0)
        self.assertGreaterEqual(term_overlap(
            ['제설 작업부 노면 접지압력 조정'],
            ['제설기 삽날과 노면의 접지압력을 일정하게 유지하고 조정'],
        ), 2)

    def test_structured_llm_counts_failure_without_sdk_retry(self):
        parse = Mock(side_effect=TimeoutError('timed out'))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
        llm = OpenAIStructuredLLM(client=client, max_retries=0, timeout_seconds=1)
        with self.assertRaises(TimeoutError):
            llm([{'role': 'user', 'content': 'x'}], MockModel)
        self.assertEqual(parse.call_count, 1)
        self.assertEqual(llm.usage['failed_calls'], 1)
        self.assertEqual(llm.max_retries, 0)

    def test_cache_reuse_is_not_invalidated_by_transport_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            messages = [{'role': 'user', 'content': 'x'}]
            a = OpenAIStructuredLLM(client=object(), cache_dir=Path(directory), timeout_seconds=30)
            b = OpenAIStructuredLLM(client=object(), cache_dir=Path(directory), timeout_seconds=60)
            self.assertEqual(a._cache_path(messages, MockModel), b._cache_path(messages, MockModel))


if __name__ == '__main__':
    unittest.main()
