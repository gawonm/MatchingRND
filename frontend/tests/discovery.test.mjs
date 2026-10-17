import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { DiscoveryRequestTracker, mergeDiscoveryItems, searchDiscovery } from '../src/discovery.ts';
import { activeRun, confirmProfile, createSession, ensureMockRun } from '../src/state/analysisSession.ts';

const component = readFileSync(new URL('../src/components/DiscoverExplorer.tsx', import.meta.url), 'utf8');
const input = { technology_domains: [], technology_tags: [], technology_description: '센서 융합', target_problem: '제설 자동화' };

test('technology·ntis·rfp 검색은 실제 Discovery API에 출처와 페이지를 전달한다', async () => {
  const originalFetch = globalThis.fetch;
  const urls = [];
  globalThis.fetch = async url => {
    urls.push(String(url));
    return { ok: true, json: async () => ({ items: [], total: 0, page: 2, page_size: 10, has_next: false, status: 'empty' }) };
  };
  try {
    for (const source of ['technology', 'ntis', 'rfp']) await searchDiscovery(source, '센서 융합', 2, 10);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(urls.length, 3);
  for (const [index, source] of ['technology', 'ntis', 'rfp'].entries()) {
    const url = new URL(urls[index]);
    assert.equal(url.pathname, '/api/discovery/search');
    assert.deepEqual(Object.fromEntries(url.searchParams), { source, q: '센서 융합', page: '2', page_size: '10' });
  }
});

test('API의 빈 결과와 HTTP 오류를 서로 다른 결과로 유지한다', async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ items: [], total: 0, page: 1, page_size: 20, has_next: false, status: 'empty' }) });
    assert.equal((await searchDiscovery('technology', '없음')).status, 'empty');
    globalThis.fetch = async () => ({ ok: false, status: 503 });
    await assert.rejects(searchDiscovery('technology', '오류'), /HTTP 503/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('요청 추적기는 빠른 중복 요청을 막고 최신 검색만 반영한다', () => {
  const tracker = new DiscoveryRequestTracker();
  const first = tracker.start('rfp', '제설', 1);
  assert.equal(tracker.start('rfp', '제설', 1), null);
  const newer = tracker.start('rfp', '로봇', 1);
  assert.equal(tracker.finish('rfp', '제설', 1, first), false);
  assert.equal(tracker.finish('rfp', '로봇', 1, newer), true);
});

test('더 보기 결과는 key 기준으로 갱신되어 중복 페이지를 만들지 않는다', () => {
  const first = { key: 'real:rfp:d:t1', mode: 'real', source: 'rfp', title: '첫 과제', evidence: [] };
  const updated = { ...first, title: '갱신된 과제' };
  const second = { key: 'real:rfp:d:t2', mode: 'real', source: 'rfp', title: '둘째 과제', evidence: [] };
  assert.deepEqual(mergeDiscoveryItems([first], [updated, second]), [updated, second]);
});

test('확정 프로필 실행은 Real, 프로필 없는 명시적 Demo 실행은 Mock이다', () => {
  const demo = activeRun(ensureMockRun(createSession('p1', 's1'), 'demo'));
  const real = activeRun(confirmProfile({ ...createSession('p1', 's2'), draftInput: input }, 'real', 'profile'));
  assert.equal(demo.mode, 'mock');
  assert.equal(real.mode, 'real');
  assert.notEqual(demo.id, real.id);
});

test('Discover 화면은 상태·모드·상세 근거를 구분하고 sourcePath를 링크로 만들지 않는다', () => {
  for (const token of ["state.status === 'loading'", "state.status === 'empty'", "state.status === 'error'", 'state.hasNext', 'loadingMore', 'provider', 'year', 'taskId', 'evidence.section', 'evidence.page', 'evidence.sourcePath']) {
    assert.match(component, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  assert.match(component, /item\.mode === current\.mode/);
  assert.match(component, /candidate\.mode === run\.mode/);
  assert.match(component, /sourceFileName\(evidence\.sourcePath\)/);
  assert.match(component, /evidence\.sourcePath &&/);
  assert.match(component, /출처 파일명은 저장 위치 정보이며 공개 URL로 변환하지 않습니다/);
  assert.doesNotMatch(component, /출처 경로: \{evidence\.sourcePath\}/);
  assert.doesNotMatch(component, /href=\{evidence\.sourcePath/);
});
