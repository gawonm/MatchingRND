import assert from 'node:assert/strict';
import test from 'node:test';
import { API_BASE_URL, createAnalysisReport, createAnalysisReportView, extractTechnologyElements, getHealth } from '../src/api.ts';

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

test('report-view는 같은 요청 본문으로 한 번만 POST하고 report·view를 함께 반환한다', async () => {
  const originalFetch = globalThis.fetch;
  try {
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push([url, options.method, JSON.parse(options.body)]);
      return new Response(JSON.stringify({ report: { method: 'llm', status: 'ok', markdown: '# 결과', claims: [], evidence: [], warnings: [], stats: {} }, view: null, view_status: 'failed', view_error: 'projection_error' }), { status: 200 });
    };
    const body = { problem: '고장 예측', owned_technologies: ['진동 분석'], unmet_elements: [] };
    const result = await createAnalysisReportView(body);
    assert.deepEqual(calls, [['http://127.0.0.1:8000/api/analysis/report-view', 'POST', body]]);
    assert.equal(result.report.markdown, '# 결과');
    assert.equal(result.view_status, 'failed');

    globalThis.fetch = async () => new Response('', { status: 500 });
    await assert.rejects(createAnalysisReportView(body), /HTTP 500/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('기술요소 추출은 A/B/문제를 분리 전송하고 후보를 승인 전 요소로 변환하며 실패 메시지를 보존한다', async () => {
  const originalFetch = globalThis.fetch;
  try {
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push(url);
      assert.deepEqual(JSON.parse(options.body), { owned_description: '진동 분석', required_description: null, problem: '고장 예측' });
      return new Response(JSON.stringify({ owned: [{ name: '진동 분석', quote: '진동 분석' }], requested: [{ name: '고장 예측', quote: '고장 예측' }], warnings: ['w'] }), { status: 200 });
    };
    const result = await extractTechnologyElements({ technology_domains: [], technology_tags: [], technology_description: '진동 분석', target_problem: '고장 예측', required_technology: ' ' });
    assert.deepEqual(calls, ['http://127.0.0.1:8000/api/analysis/extract']);
    assert.deepEqual(result.elements.map(e => [e.name, e.role, e.source, e.evidence]), [['진동 분석', 'owned', 'AI 추출', '진동 분석'], ['고장 예측', 'goal', 'AI 추출', '고장 예측']]);
    assert.deepEqual(result.warnings, ['w']);

    globalThis.fetch = async () => new Response(JSON.stringify({ detail: { error: 'extraction_unverified', message: '원문 확인 불가' } }), { status: 422 });
    await assert.rejects(extractTechnologyElements({ technology_domains: [], technology_tags: [], technology_description: 'a', target_problem: 'b' }), /원문 확인 불가/);
    globalThis.fetch = async () => new Response('oops', { status: 502 });
    await assert.rejects(extractTechnologyElements({ technology_domains: [], technology_tags: [], technology_description: 'a', target_problem: 'b' }), /HTTP 502/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('원문 질문을 제공하면 추출 API에 손실 없이 전달한다', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, options) => {
      assert.equal(JSON.parse(options.body).original_query, '원문 질문 전체?');
      return new Response(JSON.stringify({ owned: [], requested: [], warnings: [], policy_question: null }), { status: 200 });
    };
    await extractTechnologyElements({ technology_domains: [], technology_tags: [], technology_description: 'A', target_problem: 'B', original_query: ' 원문 질문 전체? ' });
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
