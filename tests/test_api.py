import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api.main import app
from app.final_answer import FinalAnswer
from app.orchestrator import OrchestrationError


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

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


if __name__ == '__main__':
    unittest.main()
