"""Count requests and verify isolation, fallback, budgets and cache reuse."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import BaseModel

from app.common.relevance_batch import BatchedRelevanceLLM
from app.gap_analysis import OpenAIStructuredLLM


class Judgment(BaseModel):
    quote: str


def requests(n):
    return [[{'role': 'system', 'content': 'Compare one technology to its own source.'},
             {'role': 'user', 'content': json.dumps({'technology': 'A', 'source': str(i)})}]
            for i in range(n)]


def fake(messages, model):
    payload = json.loads(messages[-1]['content'])
    if 'jobs' in payload:
        return model(results=[{'job_index': job['job_index'], 'judgment': {'quote': job['input']['source']}}
                              for job in reversed(payload['jobs'])])
    return model(quote=payload['source'])


class RelevanceBatchTests(unittest.TestCase):
    def test_32_candidates_need_7_calls_not_32_and_preserve_order(self):
        llm = Mock(side_effect=fake)
        runner = BatchedRelevanceLLM(lambda: llm)
        result = runner.map(requests(32), Judgment)
        self.assertEqual([r.quote for r in result], list(map(str, range(32))))
        self.assertEqual(llm.call_count, 7)
        self.assertEqual(runner.stats['api_calls'], 7)

    def test_invalid_batch_indices_fall_back_without_losing_candidates(self):
        for indices in ([0], [0, 0], [0, 9]):
            with self.subTest(indices=indices):
                def respond(messages, model):
                    payload = json.loads(messages[-1]['content'])
                    if 'jobs' in payload:
                        return model(results=[{'job_index': i, 'judgment': {'quote': 'invalid batch'}} for i in indices])
                    return fake(messages, model)
                llm = Mock(side_effect=respond)
                runner = BatchedRelevanceLLM(lambda: llm)
                self.assertEqual([r.quote for r in runner.map(requests(2), Judgment)], ['0', '1'])
                self.assertEqual(runner.stats['fallback_requests'], 2)
                self.assertEqual(llm.call_count, 3)

    def test_char_budget_splits_sources_without_truncation(self):
        reqs = requests(3)
        limit = len(reqs[0][-1]['content']) + 1
        llm = Mock(side_effect=fake)
        runner = BatchedRelevanceLLM(lambda: llm, max_chars=limit)
        self.assertEqual([r.quote for r in runner.map(reqs, Judgment)], ['0', '1', '2'])
        self.assertEqual(llm.call_count, 3)

    def test_batch_size_one_is_legacy_mode_and_failures_surface(self):
        llm = Mock(side_effect=fake)
        runner = BatchedRelevanceLLM(lambda: llm, batch_size=1)
        runner.map(requests(5), Judgment)
        self.assertEqual(llm.call_count, 5)
        broken = BatchedRelevanceLLM(lambda: Mock(side_effect=RuntimeError('API failed')))
        with self.assertRaisesRegex(RuntimeError, 'API failed'):
            broken.map(requests(2), Judgment)

    def test_schema_parse_error_also_falls_back(self):
        def respond(messages, model):
            if 'jobs' in json.loads(messages[-1]['content']):
                return model.model_validate({'results': [{'job_index': 0}]})
            return fake(messages, model)
        runner = BatchedRelevanceLLM(lambda: Mock(side_effect=respond))
        self.assertEqual([r.quote for r in runner.map(requests(2), Judgment)], ['0', '1'])
        self.assertEqual(runner.stats['fallback_requests'], 2)

    def test_batch_cannot_borrow_another_projects_evidence(self):
        from app.ntis_rag.retrieval.eligibility import TechnologyRelevanceGate
        def respond(messages, model):
            jobs = json.loads(messages[-1]['content'])['jobs']
            return model(results=[{'job_index': job['job_index'], 'judgment': {
                'relation': 'same', 'reason': 'incorrect cross-source quote',
                'quote': jobs[1 - job['job_index']]['input']['project_text']}} for job in jobs])
        gate = TechnologyRelevanceGate('B', ['A'], llm=respond)
        checks = gate.check_many([{'text': 'first independent source'}, {'text': 'second different source'}])
        self.assertTrue(all(not c['accepted'] for c in checks))

    def test_baseline_scale_pipeline_counts_and_results_are_preserved(self):
        from test_rfp_relevance import fixture, question
        from test_ntis_relevance import fixtures
        from app.rfp_rag.pipeline import search_module_result
        from app.ntis_rag.pipeline import run_ntis_pipeline
        from app.ntis_rag.generation import analysis
        report = {}
        for batch_size in (1, 5):
            with patch.dict('os.environ', {'RFP_RELEVANCE_BATCH_SIZE': str(batch_size),
                                           'RFP_RELEVANCE_BATCH_MODE': 'chars',
                                           'NTIS_RELEVANCE_BATCH_SIZE': str(batch_size)}):
                index, retrieved, judge, _ = fixture([('same', 'different')] * 30 + [('same', 'same')] * 2)
                with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
                    rfp = search_module_result(index, question(), top_k=2, relevance_llm=judge)
                projects, judge = fixtures([('same', 'different')] * 18 + [('same', 'same')] * 2)
                responses = [
                    {'core_problem': 'B', 'key_technologies': ['A'], 'search_query': 'B'},
                    *[{'research_topic': 'research', 'technology_elements': [
                        {'element': 'sensor fusion', 'evidence': 'sensor fusion'}]}] * 2,
                    {'items': [{'item_id': i, 'canonical_name': 'sensor fusion'} for i in range(2)]},
                    {'groups': [{'axis': 'research axis', 'technology_ids': [0]}]},
                ]
                with patch.object(analysis, 'llm', Mock()) as llm:
                    llm.invoke.side_effect = [SimpleNamespace(content=json.dumps(r)) for r in responses]
                    ntis = run_ntis_pipeline('B', ['A'], requested_technologies=['B'], analysis_top_n=2,
                                            relevance_llm=judge, _retriever=Mock(return_value=projects))
                report[batch_size] = (rfp, ntis)
        before_rfp, before_ntis = report[1]
        after_rfp, after_ntis = report[5]
        self.assertEqual([c.doc_id for c in before_rfp.candidates], [c.doc_id for c in after_rfp.candidates])
        self.assertEqual(before_ntis['related_projects'], after_ntis['related_projects'])
        self.assertEqual(before_ntis['prior_rd_axes'], after_ntis['prior_rd_axes'])
        for result, expected in ((before_rfp, 32), (after_rfp, 7)):
            self.assertEqual(result.extra['diagnostics']['technology_relevance']['llm_usage']['api_calls'], expected)
        self.assertEqual(before_ntis['diagnostics']['llm_usage']['total'], 45)
        self.assertEqual(after_ntis['diagnostics']['llm_usage']['total'], 13)

    def test_token_budget_counts_envelope_and_schema_without_truncating_sources(self):
        reqs = requests(3)
        reqs[0][-1]['content'] = json.dumps({'technology': 'A', 'source': 'x' * 100})
        counted = []
        def count(text):
            counted.append(json.loads(text))
            return len(text)
        llm = Mock(side_effect=fake)
        runner = BatchedRelevanceLLM(lambda: llm, max_chars=1,
                                     max_tokens=3700, count_tokens=count)
        result = runner.map(reqs, Judgment)
        self.assertEqual([r.quote for r in result], ['x' * 100, '1', '2'])
        self.assertTrue(all('messages' in row and 'schema' in row for row in counted))
        self.assertLess(llm.call_count, 3)  # max_chars is inactive in token mode.

    def test_oversized_single_is_preserved_and_next_source_is_separate(self):
        llm = Mock(side_effect=fake)
        runner = BatchedRelevanceLLM(lambda: llm, max_tokens=1, count_tokens=len)
        self.assertEqual([r.quote for r in runner.map(requests(2), Judgment)], ['0', '1'])
        self.assertEqual(llm.call_count, 2)

    def test_real_structured_client_reuses_disk_cache_and_invalidates_changed_source(self):
        parse = Mock()
        def respond(**kwargs):
            result = fake(kwargs['messages'], kwargs['response_format'])
            return SimpleNamespace(usage=None, choices=[SimpleNamespace(
                message=SimpleNamespace(parsed=result, refusal=None))])
        parse.side_effect = respond
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
        with tempfile.TemporaryDirectory() as directory:
            def make_runner():
                return BatchedRelevanceLLM(lambda: OpenAIStructuredLLM(client=client, cache_dir=Path(directory)))
            first = make_runner()
            first.map(requests(5), Judgment)
            second = make_runner()
            second.map(requests(5), Judgment)
            self.assertEqual(parse.call_count, 1)
            self.assertEqual(second.stats['api_calls'], 0)
            self.assertEqual(second.stats['cache_hits'], 1)
            changed = requests(5)
            changed[-1][-1]['content'] = json.dumps({'technology': 'A', 'source': 'changed'})
            make_runner().map(changed, Judgment)
            self.assertEqual(parse.call_count, 2)

    def test_ntis_stage_counter_includes_extraction_retries_and_is_scoped(self):
        from app.ntis_rag.generation import analysis
        with patch.object(analysis, 'llm', Mock()) as llm:
            llm.invoke.return_value = SimpleNamespace(content='{}')
            with analysis.track_llm_calls() as usage:
                analysis.extract_project_tech({'project_id': 'p', 'text': 'original'}, max_retries=1)
            self.assertEqual(usage['technology_extraction'], 2)
            with analysis.track_llm_calls() as fresh:
                self.assertEqual(sum(fresh.values()), 0)


if __name__ == '__main__':
    unittest.main()
