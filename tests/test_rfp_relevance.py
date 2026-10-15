"""RFP pair filtering with injected LLM judgments; no API or model downloads."""
import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.rfp_rag.pipeline import search, search_module_result
from app.rfp_rag.retrieval.eligibility import TechnologyRelevanceGate, query_constraints, _quote_sections
from app.rfp_rag.retrieval.query import build_query


def fixture(pairs):
    docs, tasks, judgments = [], {}, {}
    for number, (owned, requested) in enumerate(pairs):
        task_id = f'task-{number}'
        fragments = [SimpleNamespace(page_content=f'{task_id} 보유 측 요구 원문', metadata={'page': 1,
                     'source': 'rfp.pdf', 'kind': 'text'}),
                     SimpleNamespace(page_content=f'{task_id} 보완 측 요구 원문', metadata={'page': 2,
                     'source': 'rfp.pdf', 'kind': 'text'})]
        tasks[task_id] = {'task_id': task_id, 'fields': {'요구기술': fragments}}
        judgments[task_id] = [
            {'technology_index': i, 'reason': '기술 기능을 비교한 LLM 판단', 'relation': relation,
             'section_index': i if relation in {'same', 'similar'} else -1,
             'quote': fragments[i].page_content if relation in {'same', 'similar'} else ''}
            for i, relation in enumerate((owned, requested))
        ]
        # Two chunks in the same task; each side can be on a different page.
        for i, fragment in enumerate(fragments):
            docs.append(SimpleNamespace(page_content=fragment.page_content, metadata={
                'chunk_id': f'{task_id}-{i}', 'task_id': task_id, 'document_id': 'shared-pdf',
                'source': 'rfp.pdf', 'filename': 'rfp.pdf', 'title': task_id, 'pages': [i + 1],
                'item': '요구기술', 'original_text': fragment.page_content,
            }))
    index = {'docs': docs, 'chunks_by_id': {d.metadata['chunk_id']: d for d in docs},
             'dataset': {'tasks': list(tasks.values()), 'notices': {}}, 'tasks_by_id': tasks,
             'tokenizer': SimpleNamespace(encode=lambda text, **kw: list(text)),
             'TOP_K': 20, 'CONTEXT_TOKENS': 100000, 'max_query_tokens': 10000, 'RRF_K': 60}
    retrieved = [(d.metadata['chunk_id'], 0) for d in docs]

    def llm(messages, model):
        payload = json.loads(messages[-1]['content'])
        task_id = payload['sections'][0]['text'].split()[0]
        technology_index = payload['technologies'][0]['index']
        return model(matches=[m for m in judgments[task_id] if m['technology_index'] == technology_index])

    return index, (retrieved, retrieved, docs), Mock(side_effect=llm), judgments


def question(**options):
    return build_query(['보유 A'], 'A와 B를 결합하고 싶다', unmet_elements=['요청 B'],
                       return_details=True, **options)


class RfpRelevanceTests(unittest.TestCase):
    def test_llm_progress_is_silent_unless_verbose(self):
        from app.rfp_rag.scripts import try_search

        response = object()
        messages = [{'role': 'user', 'content': json.dumps({'technologies': [{'name': '테스트 기술'}]})}]
        for verbose in (False, True):
            console = io.StringIO()
            with patch('app.gap_analysis.OpenAIStructuredLLM') as factory, redirect_stdout(console):
                factory.return_value.return_value = response
                judge = try_search.progress_llm(verbose=verbose)
                self.assertIs(judge(messages, object), response)
            if verbose:
                self.assertIn('LLM 원문 비교 1: 테스트 기술', console.getvalue())
            else:
                self.assertEqual(console.getvalue(), '')

    def test_wrapped_pdf_quote_keeps_relevant_task_and_original_locations(self):
        first = '- 멀티센서 데이터의 수집, 시간동기화, 좌표 정합 및 클라우드 기반 저장·전처'
        second = '리·품질관리 체계의 기본 설계'
        quote = first + second
        task = {'fields': {'개발내용': [
            SimpleNamespace(page_content=first, metadata={'page': 3, 'source': 'a.pdf', 'bbox': [0, 0, 10, 10]}),
            SimpleNamespace(page_content=second, metadata={'page': 3, 'source': 'a.pdf', 'bbox': [0, 10, 10, 20]}),
            SimpleNamespace(page_content='Digital Twin 모델 및 공통 데이터 구조 설계',
                            metadata={'page': 4, 'source': 'a.pdf'}),
        ]}}
        def llm(messages, model):
            i = json.loads(messages[-1]['content'])['technologies'][0]['index']
            return model(matches=[dict(technology_index=i, reason='기능 대응', relation='same',
                                       section_index=0 if i == 0 else 2,
                                       quote=quote if i == 0 else task['fields']['개발내용'][2].page_content)])
        check = TechnologyRelevanceGate(question(), llm).check(task)
        self.assertTrue(check['accepted'])
        spans = check['matches'][0]['verified_sections']
        self.assertEqual([s['text'] for s in spans], [first, second])
        self.assertEqual([s['bbox'] for s in spans], [[0, 0, 10, 10], [0, 10, 10, 20]])

    def test_quote_cannot_skip_text_cross_boundaries_or_start_in_wrong_fragment(self):
        def section(text, **changes):
            return {'item': '개발내용', 'page': 3, 'source': 'a.pdf', 'text': text, **changes}
        self.assertTrue(_quote_sections([section('시간 동기화 및 전처'), section('리 설계')], 0,
                                        '시간동기화 및 전처리 설계'))
        for sections, quote in [
            ([section('앞문장'), section('중간 문장'), section('뒷문장')], '앞문장뒷문장'),
            ([section('앞문장'), section('뒷문장', page=4)], '앞문장뒷문장'),
            ([section('앞문장'), section('뒷문장', source='b.pdf')], '앞문장뒷문장'),
            ([section('앞문장'), section('뒷문장', item='지원조건')], '앞문장뒷문장'),
            ([section('앞문장'), section('뒷문장')], '뒷문장'),
            ([section('실제 문장')], '만들어낸 문장'),
        ]:
            with self.subTest(sections=sections, quote=quote):
                self.assertEqual(_quote_sections(sections, 0, quote), [])

    def test_interactive_input_search_and_saved_results(self):
        from app.rfp_rag.scripts import try_search

        for pair, expected_count in [(('same', 'similar'), 1), (('different', 'same'), 0)]:
            with self.subTest(pair=pair), tempfile.TemporaryDirectory() as directory:
                index, retrieved, llm, _ = fixture([pair])
                console = io.StringIO()
                with patch.object(try_search, 'load_index', return_value=index) as loader, \
                     patch.object(try_search, 'progress_llm', return_value=llm), \
                     patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved), \
                     patch('builtins.input', side_effect=['보유 A', '요청 B', '결합 문제', '']), \
                     redirect_stdout(console):
                    self.assertEqual(try_search.main(['--backend', 'local', '--output-dir', directory]), 0)
                loader.assert_called_once_with('local')
                outputs = list(Path(directory).glob('rfp_search_*.json'))
                self.assertEqual(len(outputs), 1)
                saved = json.loads(outputs[0].read_text(encoding='utf-8'))
                self.assertEqual(saved['query_details']['owned_technologies'], ['보유 A'])
                self.assertEqual(saved['query_details']['unmet_elements'], ['요청 B'])
                self.assertEqual(len(saved['hits']), expected_count)
                self.assertIn('task-0' if expected_count else '관련 공고가 없습니다.', console.getvalue())

    def test_all_nine_combinations_and_no_leak_through_adapter(self):
        pairs = [(a, b) for a in ('same', 'similar', 'different')
                 for b in ('same', 'similar', 'different')]
        index, retrieved, llm, _ = fixture(pairs)
        with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
            result = search_module_result(index, question(), relevance_llm=llm)
        accepted = {'task-0', 'task-1', 'task-3', 'task-4'}
        self.assertEqual({c.extra['task_id'] for c in result.candidates}, accepted)
        self.assertEqual({h.extra['task_id'] for h in result.hits}, accepted)
        self.assertEqual({s['task_id'] for s in result.extra['sources']}, accepted)
        for task_id in {'task-2', 'task-5', 'task-6', 'task-7', 'task-8'}:
            self.assertNotIn(task_id, result.extra['context'])
        self.assertEqual(llm.call_count, 18)  # once per technology/task, not per chunk

    def test_no_match_is_empty_even_when_retrievers_return_candidates(self):
        index, retrieved, llm, _ = fixture([('same', 'different'), ('different', 'similar')])
        with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
            result = search(index, question(), relevance_llm=llm)
        for key in ('hits', 'sources', 'ranking'):
            self.assertEqual(result[key], [])
        self.assertEqual(result['context'], '')
        self.assertEqual(result['status'], 'no_matches')
        self.assertEqual(result['message'], '관련 공고가 없습니다.')

    def test_rejected_top_results_do_not_consume_top_k(self):
        index, retrieved, llm, _ = fixture([('same', 'different'), ('different', 'same'),
                                            ('similar', 'similar')])
        with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
            result = search(index, question(), relevance_llm=llm, top_k=1)
        self.assertEqual([h['task_id'] for h in result['hits']], ['task-2'])
        self.assertEqual(llm.call_count, 6)

    def test_missing_forged_negative_and_duplicate_judgments_fail_closed(self):
        for mode in ('forged', 'missing', 'different', 'duplicate', 'insufficient'):
            with self.subTest(mode=mode):
                index, retrieved, llm, judgments = fixture([('same', 'same')])
                rows = judgments['task-0']
                if mode == 'forged':
                    rows[1]['quote'] = '원문에 없는 그럴듯한 인용문'
                elif mode == 'missing':
                    rows.pop()
                elif mode in ('different', 'insufficient'):
                    rows[1]['relation'] = mode
                else:
                    rows.append(dict(rows[0]))
                with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
                    result = search(index, question(), relevance_llm=llm)
                self.assertEqual(result['status'], 'no_matches')

    def test_missing_requirements_cannot_use_sibling_task_in_same_pdf(self):
        index, retrieved, llm, _ = fixture([('same', 'same'), ('same', 'same')])
        index['tasks_by_id']['task-0']['fields'] = {'지원조건': index['tasks_by_id']['task-1']['fields']['요구기술']}
        with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
            result = search(index, question(), relevance_llm=llm)
        self.assertEqual([h['task_id'] for h in result['hits']], ['task-1'])
        self.assertEqual(llm.call_count, 2)

    def test_query_roles_survive_string_api_and_expansion_does_not_replace_request(self):
        details = question(external_elements=[{'technology': '무관 C', 'quote': 'C 원문', 'source_id': 'c'}],
                           ntis_elements=[{'technology': '무관 D', 'quote': 'D 원문', 'source_id': 'd'}])
        self.assertEqual(query_constraints(details), (['보유 A'], ['요청 B'], True))
        self.assertEqual(query_constraints(details['query']), query_constraints(details))
        index, retrieved, llm, _ = fixture([('same', 'different')])
        with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
            result = search(index, details['query'], relevance_llm=llm)
        self.assertEqual(result['hits'], [])
        self.assertEqual([t['name'] for call in llm.call_args_list
                          for t in json.loads(call.args[0][-1]['content'])['technologies']], ['보유 A', '요청 B'])

    def test_api_failure_is_not_reported_as_no_matches(self):
        index, retrieved, _, _ = fixture([('same', 'same')])
        with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
            with self.assertRaisesRegex(RuntimeError, 'API 실패'):
                search(index, question(), relevance_llm=Mock(side_effect=RuntimeError('API 실패')))

    def test_unstructured_search_does_not_invent_technology_roles(self):
        index, retrieved, llm, _ = fixture([('same', 'different')])
        with patch('app.rfp_rag.retrieval.pipeline._retrieve', return_value=retrieved):
            result = search(index, '일반 기술 키워드 검색', relevance_llm=llm)
        self.assertEqual(len(result['hits']), 1)
        llm.assert_not_called()

    def test_every_explicit_request_needs_evidence_but_owned_portfolio_can_have_extras(self):
        details = build_query(['A', 'A2'], '문제', unmet_elements=['B', 'B2'], return_details=True)
        matches = [dict(technology_index=i, reason='판단', relation=relation,
                        section_index=0, quote='원문') for i, relation in enumerate(
                            ['same', 'different', 'similar', 'different'])]
        def llm(messages, model):
            i = json.loads(messages[-1]['content'])['technologies'][0]['index']
            return model(matches=[matches[i]])
        gate = TechnologyRelevanceGate(details, llm)
        task = {'fields': {'요구기술': [SimpleNamespace(page_content='원문', metadata={'page': 1})]}}
        self.assertFalse(gate.check(task)['accepted'])
        matches[-1]['relation'] = 'similar'
        self.assertTrue(gate.check(task)['accepted'])


if __name__ == '__main__':
    unittest.main()
