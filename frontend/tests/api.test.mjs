import assert from 'node:assert/strict';
import test from 'node:test';
import { API_BASE_URL, getHealth } from '../src/api.ts';

test('API base URL은 기본 FastAPI 주소를 사용한다', () => {
  assert.equal(API_BASE_URL, 'http://127.0.0.1:8000');
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
