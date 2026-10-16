import assert from 'node:assert/strict';
import test from 'node:test';
import { API_BASE_URL, createAnalysisReport, getHealth } from '../src/api.ts';

test('API base URL은 기본 FastAPI 주소를 사용한다', () => {
  assert.equal(API_BASE_URL, 'http://127.0.0.1:8000');
});

test('보고서는 명시적 POST 요청으로만 생성한다', async () => {
  const originalFetch = globalThis.fetch;
  try {
    let calls = 0;
    globalThis.fetch = async (url, options) => {
      calls += 1;
      assert.equal(url, 'http://127.0.0.1:8000/api/analysis/report');
      assert.equal(options.method, 'POST');
      assert.deepEqual(JSON.parse(options.body), {
        problem: '고장 예측', owned_technologies: ['진동 분석'], unmet_elements: [],
      });
      return new Response(JSON.stringify({ method: 'llm', status: 'ok', markdown: '# 결과', claims: [], evidence: [], warnings: [], stats: {} }), { status: 200 });
    };
    assert.equal(calls, 0);
    assert.equal((await createAnalysisReport({ problem: '고장 예측', owned_technologies: ['진동 분석'], unmet_elements: [] })).method, 'llm');
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('health 요청은 성공 응답을 반환하고 HTTP 오류를 사용자 오류로 바꾼다', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async url => {
      assert.equal(url, 'http://127.0.0.1:8000/api/health');
      return new Response(JSON.stringify({ status: 'ok', message: 'ready' }), { status: 200 });
    };
    assert.equal((await getHealth()).status, 'ok');

    globalThis.fetch = async () => new Response('', { status: 503 });
    await assert.rejects(getHealth(), /HTTP 503/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
