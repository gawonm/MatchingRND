import assert from 'node:assert/strict';
import test from 'node:test';
import { activeRun, confirmProfile, createSession, ensureMockRun, hasUnconfirmedChanges, isHistoricalRun, runProfile, selectedItems, toggleSelection, updateRun } from '../src/state/analysisSession.ts';
import { isNavigation, pageFromHash } from '../src/state/useNavigation.ts';

const input = { technology_domains: [], technology_tags: [], technology_description: '진동 센서 분석', target_problem: '모터 고장 예측' };
const item = { key: 'mock:technology:candidate', mode: 'mock', source: 'technology', title: '예시 후보', evidence: [] };

test('프로필 없는 탐색은 가짜 프로필 없이 독립된 Mock 실행을 만들고 재진입 시 유지한다', () => {
  const session = ensureMockRun(createSession('p1', 's1'), 'browse');
  const run = activeRun(session);
  assert.equal(run.mode, 'mock');
  assert.equal(run.id, 'browse');
  assert.equal(run.profileId, null);
  assert.equal(run.profileVersion, null);
  assert.equal(runProfile(session, run), null);
  assert.deepEqual(session.profiles, []);
  assert.equal(ensureMockRun(session, 'unused'), session);
  const confirmed = confirmProfile({ ...session, draftInput: input }, 'profile-run', 'profile');
  assert.equal(confirmed.runs.length, 2);
  assert.equal(confirmed.runs[0].profileId, null);
  assert.equal(confirmed.profiles[0].elements.length, 0);
  assert.equal(activeRun(confirmed).profileVersion, 1);
});

test('최신 편집본 변경과 과거 실행 조회를 독립적으로 판정한다', () => {
  const first = confirmProfile({ ...createSession('p1', 's1'), draftInput: input }, 'r1', 'p1');
  const pending = { ...first, draftInput: { ...input, target_problem: '펌프 고장 예측' } };
  assert.equal(hasUnconfirmedChanges(pending), true);
  const second = confirmProfile(pending, 'r2', 'p2');
  const history = { ...second, activeRunId: 'r1' };
  assert.equal(isHistoricalRun(history, activeRun(history)), true);
  assert.equal(hasUnconfirmedChanges(history), false);
  assert.equal(runProfile(history, activeRun(history)).input.target_problem, input.target_problem);
  assert.equal(confirmProfile(history, 'unused', 'unused').activeRunId, 'r2');
  assert.equal(second.runs.length, 2);
});

test('검색 출처와 선택은 실행에 저장되어 화면 이동 후 같은 상태로 읽힌다', () => {
  let session = ensureMockRun(createSession('p1', 's1'), 'browse');
  session = updateRun(session, 'browse', run => ({ ...run, activeSource: 'ntis', items: [item] }));
  session = updateRun(session, 'browse', run => toggleSelection(run, item.key));
  assert.equal(activeRun(session).activeSource, 'ntis');
  assert.deepEqual(selectedItems(activeRun(session)), [item]);
  const confirmed = confirmProfile({ ...session, draftInput: input }, 'r2', 'p2');
  assert.equal(confirmed.runs[0].activeSource, 'ntis');
  assert.deepEqual(selectedItems(confirmed.runs[0]), [item]);
  assert.deepEqual(selectedItems(activeRun(confirmed)), []);
});

test('존재하지 않거나 다른 모드의 자료는 선택에 추가되지 않는다', () => {
  const run = activeRun(ensureMockRun(createSession('p1', 's1'), 'browse'));
  assert.equal(toggleSelection(run, 'missing'), run);
  const mixed = { ...run, items: [{ ...item, mode: 'real' }] };
  assert.equal(toggleSelection(mixed, item.key), mixed);
  assert.deepEqual(selectedItems(run), []);
});

test('선택 해제는 가정·근거 초점도 제거하고 재선택은 가정을 되살리지 않는다', () => {
  const run = { ...activeRun(ensureMockRun(createSession('p1', 's1'), 'browse')), items: [item], selectedKeys: [item.key], assumedKeys: [item.key], reviewFocusKey: item.key };
  const removed = toggleSelection(run, item.key);
  assert.deepEqual(removed.selectedKeys, []);
  assert.deepEqual(removed.assumedKeys, []);
  assert.equal(removed.reviewFocusKey, null);
  const reselected = toggleSelection(removed, item.key);
  assert.deepEqual(reselected.selectedKeys, [item.key]);
  assert.deepEqual(reselected.assumedKeys, []);
  assert.deepEqual(run.assumedKeys, [item.key]);
});

test('브라우저 이동 이력은 페이지·세션·실행·데모 모드를 함께 식별한다', () => {
  assert.equal(pageFromHash('#discover'), 'discover');
  assert.equal(pageFromHash('#unknown'), 'home');
  assert.equal(isNavigation({ page: 'workspace', sessionId: 's1', runId: 'r1', mode: 'demo' }), true);
  assert.equal(isNavigation({ page: 'discover', sessionId: 's1', runId: null, mode: 'review' }), true);
  assert.equal(isNavigation({ page: 'workspace', sessionId: 's1', runId: 'r1', mode: 'real' }), false);
  assert.equal(isNavigation({ page: 'unknown', sessionId: 's1', runId: 'r1', mode: 'review' }), false);
});
