import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.api.main import app
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


if __name__ == '__main__':
    unittest.main()
