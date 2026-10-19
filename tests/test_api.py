import unittest
from os import environ
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api.main import app, get_orchestrator
from app.final_answer import FinalAnswer
from app.orchestrator import OrchestrationError
from app.query_parser import parse_query


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

    def test_capabilities_make_unsupported_mvp_scope_explicit(self):
        response = self.client.get('/api/capabilities')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn('policy_search', body['unsupported_analysis'])
        self.assertIn('company_database_verification', body['unsupported_analysis'])
        self.assertEqual(body['company_input_provenance'], 'user_assertion_not_independently_verified')

    def test_orchestrator_uses_server_backend_environment(self):
        with patch.dict(environ, {'RAG_BACKEND': 'local'}):
            get_orchestrator.cache_clear()
            self.assertEqual(get_orchestrator().backend, 'local')
        get_orchestrator.cache_clear()

    def test_cors_allows_local_frontend(self):
        response = self.client.options('/api/health', headers={
            'Origin': 'http://localhost:5173',
            'Access-Control-Request-Method': 'GET',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:5173')

    @patch('app.api.main.get_orchestrator')
    def test_analysis_rejects_invalid_input_before_running_rag(self, get_orchestrator):
        response = self.client.post('/api/analysis', json={})
        self.assertEqual(response.status_code, 422)
        get_orchestrator.assert_not_called()

    @patch('app.api.main.get_orchestrator')
    def test_analysis_returns_safe_stage_error(self, get_orchestrator):
        get_orchestrator.return_value.run = Mock(side_effect=OrchestrationError('technology', RuntimeError('secret')))
        response = self.client.post('/api/analysis', json={
            'problem': '고장 시점을 예측하고 싶다.',
            'owned_technologies': ['진동 분석'],
        })
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['detail'], {
            'error': 'analysis_failed',
            'stage': 'technology',
            'message': 'RAG 분석 단계 실행에 실패했습니다.',
        })
        self.assertNotIn('secret', response.text)

    @patch('app.api.main.generate_analysis_report')
    def test_report_runs_only_on_explicit_request(self, generate_report):
        generate_report.return_value = FinalAnswer(
            method='llm', status='ok', markdown='# 보고서\n', stats={'generation_calls': 1},
        )

        self.client.get('/api/health')
        generate_report.assert_not_called()

        response = self.client.post('/api/analysis/report', json={
            'problem': '고장 시점을 예측하고 싶다.',
            'owned_technologies': ['진동 분석'],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {
            'method', 'status', 'markdown', 'claims', 'evidence', 'warnings', 'stats',
        })
        self.assertEqual(response.json()['method'], 'llm')
        generate_report.assert_called_once()

    @patch('app.api.main.run_integrated_analysis')
    @patch('app.api.main.get_orchestrator')
    def test_report_pipeline_uses_mocked_dependencies(self, get_orchestrator, run_integrated_analysis):
        answer = FinalAnswer(method='llm', status='ok', markdown='# 보고서\n')
        run_integrated_analysis.return_value = SimpleNamespace(answers={'llm': answer}, errors={})
        response = self.client.post('/api/analysis/report', json={
            'problem': '고장 시점을 예측하고 싶다.',
            'owned_technologies': ['진동 분석'],
        })
        self.assertEqual(response.status_code, 200)
        run_integrated_analysis.assert_called_once_with(
            request=run_integrated_analysis.call_args.kwargs['request'],
            orchestrator=get_orchestrator.return_value,
            modes=('llm',),
        )

    @patch('app.api.main.generate_analysis_report')
    def test_report_rejects_invalid_input_before_running_pipeline(self, generate_report):
        response = self.client.post('/api/analysis/report', json={})
        self.assertEqual(response.status_code, 422)
        generate_report.assert_not_called()

    @patch('app.api.main.generate_analysis_report', side_effect=RuntimeError('secret'))
    def test_report_returns_safe_error(self, _generate_report):
        response = self.client.post('/api/analysis/report', json={
            'problem': '고장 시점을 예측하고 싶다.',
        })
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['detail']['error'], 'report_failed')
        self.assertNotIn('secret', response.text)

    @patch('app.api.main.generate_analysis_report')
    def test_report_surfaces_safe_pipeline_stage(self, generate_report):
        from app.api.main import ReportGenerationError
        generate_report.side_effect = ReportGenerationError('gap_llm')
        response = self.client.post('/api/analysis/report', json={'problem': '고장 예측'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['detail']['stage'], 'gap_llm')

    def _extract_with(self, fake_llm, payload):
        real_parse = parse_query
        # Same retry budget as production (parse_query default), only the LLM is fake.
        with patch('app.api.main.parse_query', lambda query, **kwargs: real_parse(query, llm=fake_llm, **kwargs)), \
                patch('app.api.main.generate_analysis_report') as generate_report, \
                patch('app.api.main.get_orchestrator') as orchestrator:
            response = self.client.post('/api/analysis/extract', json=payload)
        generate_report.assert_not_called()
        orchestrator.assert_not_called()
        return response

    def test_extract_returns_grounded_candidates_without_running_rag(self):
        payload = {'owned_description': '진동 데이터 이상 탐지 기술을 보유', 'required_description': '잔존수명 예측',
                   'problem': '설비 고장을 미리 알고 싶다'}
        seen = []

        def fake_llm(messages, _schema):
            seen.append(messages[1]['content'])
            return {'development_goal': '고장 예측', 'policy_question': None,
                    'owned': [{'name': '진동 데이터 이상 탐지', 'quote': '진동 데이터 이상 탐지 기술을 보유'}],
                    'requested': [{'name': '잔존수명 예측', 'quote': '보완·확보하고 싶은 기술: 잔존수명 예측'}]}

        response = self._extract_with(fake_llm, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t['name'] for t in response.json()['owned']], ['진동 데이터 이상 탐지'])
        self.assertEqual([t['name'] for t in response.json()['requested']], ['잔존수명 예측'])
        self.assertIn('보완·확보하고 싶은 기술: 잔존수명 예측', seen[0])

    def test_extract_uses_exact_original_question_when_provided(self):
        raw = '우리는 진동 분석을 가지고 있는데 잔존수명 예측이 필요할까?'
        seen = []

        def fake_llm(messages, _schema):
            seen.append(messages[1]['content'])
            return {'development_goal': '잔존수명 예측', 'policy_question': None,
                    'owned': [{'name': '진동 분석', 'quote': '진동 분석'}],
                    'requested': [{'name': '잔존수명 예측', 'quote': '잔존수명 예측'}]}

        response = self._extract_with(fake_llm, {
            'owned_description': '진동 분석', 'required_description': '잔존수명 예측',
            'problem': '잔존수명 예측', 'original_query': raw,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(raw, seen[0])
        self.assertNotIn('현재 보유한 기술:', seen[0])

    def test_extract_accepts_whitespace_and_line_break_differences(self):
        payload = {'owned_description': '진동 데이터 이상 탐지 기술을 보유', 'required_description': '잔존수명 예측',
                   'problem': '설비 고장을 미리 알고 싶다'}

        def fake_llm(_messages, _schema):
            return {'development_goal': '고장 예측', 'policy_question': None,
                    'owned': [{'name': '진동데이터 이상탐지', 'quote': '진동 데이터 이상 탐지 기술을 보유 보완·확보하고'}],
                    'requested': [{'name': '잔존수명예측', 'quote': '잔존수명 예측'}]}

        response = self._extract_with(fake_llm, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['owned']), 1)
        self.assertEqual(len(response.json()['requested']), 1)

    def test_extract_recovers_paraphrased_names_with_source_word_spans(self):
        payload = {'owned_description': '진동 데이터 이상 탐지 기술을 보유', 'required_description': '잔존수명 예측',
                   'problem': '설비 고장을 미리 알고 싶다'}
        calls = []

        def fake_llm(_messages, schema):
            calls.append(schema.__name__)
            if len(calls) == 1:  # paraphrase not present in the user's text
                return {'development_goal': '고장 예측', 'policy_question': None,
                        'owned': [{'name': '진동 기반 이상감지', 'quote': '진동 기반 이상감지'}],
                        'requested': [{'name': 'RUL 예측', 'quote': 'RUL 예측'}]}
            # words: 3-6 '진동 데이터 이상 탐지', 12-13 '잔존수명 예측'
            return {'development_goal': '고장 예측', 'policy_question': None,
                    'owned': [{'start_word': 3, 'end_word': 6}], 'requested': [{'start_word': 12, 'end_word': 13}]}

        response = self._extract_with(fake_llm, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, ['ParsedQuery', 'ParsedQuerySpans'])
        self.assertEqual([t['name'] for t in response.json()['owned']], ['진동 데이터 이상 탐지'])
        self.assertEqual([t['name'] for t in response.json()['requested']], ['잔존수명 예측'])
        self.assertTrue(response.json()['warnings'])

    def test_extract_without_b_and_without_explicit_owned_returns_warning_not_error(self):
        seen = []

        def fake_llm(messages, _schema):
            seen.append(messages[1]['content'])
            return {'development_goal': '고장 예측', 'policy_question': None, 'owned': [],
                    'requested': [{'name': '고장 예측', 'quote': '고장 예측'}]}

        response = self._extract_with(fake_llm, {'owned_description': '모터 설비', 'problem': '고장 예측'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['owned'], [])
        self.assertTrue(response.json()['warnings'])
        self.assertNotIn('보완·확보하고 싶은 기술', seen[0])

    def test_extract_rejects_ungrounded_names_and_missing_input(self):
        def fake_llm(_messages, _schema):
            return {'development_goal': '', 'policy_question': None,
                    'owned': [{'name': '양자 컴퓨팅', 'quote': '양자 컴퓨팅'}], 'requested': []}

        response = self._extract_with(fake_llm, {'owned_description': '진동 분석', 'problem': '고장 예측'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail']['error'], 'extraction_unverified')

        response = self._extract_with(fake_llm, {'owned_description': '  ', 'problem': '고장 예측'})
        self.assertEqual(response.status_code, 422)

    def test_extract_returns_safe_error_on_llm_failure(self):
        def fake_llm(_messages, _schema):
            raise RuntimeError('secret-key')

        response = self._extract_with(fake_llm, {'owned_description': '진동 분석', 'problem': '고장 예측'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['detail']['error'], 'extraction_failed')
        self.assertNotIn('secret', response.text)


if __name__ == '__main__':
    unittest.main()
