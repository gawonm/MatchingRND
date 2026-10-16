import assert from 'node:assert/strict';
import test from 'node:test';
import { activeRun, confirmProfile, createSession, draftDiffers, runProfile, selectedItems, selectionKey, updateRun } from '../src/state/analysisSession.ts';

const input = { technology_domains: [], technology_tags: [], technology_description: '진동 이상 탐지', target_problem: '고장 시점 예측', patent_numbers: ['P-1'] };
const draft = () => ({ ...createSession('p1', 'session-a'), draftInput: input });

test('확정 프로필과 실행은 원문·특허를 보존하고 변경할 때만 새 버전이 된다', () => {
  const first = confirmProfile(draft(), 'run-1', 'profile-1');
  assert.equal(runProfile(first, activeRun(first)).input.patent_numbers[0], 'P-1');
  assert.equal(runProfile(first, activeRun(first)).version, 1);
  assert.equal(confirmProfile(first, 'unused', 'unused'), first);
  const changed = { ...first, draftInput: { ...first.draftInput, target_problem: '다른 문제' } };
  assert.equal(draftDiffers(changed), true);
  const second = confirmProfile(changed, 'run-2', 'profile-2');
  assert.equal(second.runs.length, 2);
  assert.equal(runProfile(second, activeRun(second)).version, 2);
  assert.equal(second.profiles[0].input.target_problem, '고장 시점 예측');
  assert.equal(second.runs[1].profileVersion, 2);
});

test('기술요소가 없어도 원문으로 확정하며 빈 원문은 확정하지 않는다', () => {
  assert.equal(confirmProfile(draft(), 'run-1', 'profile-1').profiles[0].elements.length, 0);
  assert.equal(confirmProfile(createSession('p1', 'empty')).runs.length, 0);
});

test('출처와 모드 및 RFP 세부 과제 ID가 선택 키 충돌을 막는다', () => {
  assert.notEqual(selectionKey('mock', 'technology', '1'), selectionKey('mock', 'ntis', '1'));
  assert.notEqual(selectionKey('mock', 'rfp', '1'), selectionKey('real', 'rfp', '1', 'task-a'));
  assert.notEqual(selectionKey('real', 'rfp', '1', 'task-a'), selectionKey('real', 'rfp', '1', 'task-b'));
  assert.equal(selectionKey('real', 'rfp', '1'), 'real:rfp:1');
  assert.throws(() => selectionKey('real', 'rfp', ''), /원본 식별자/);
});

test('선택과 가정은 해당 실행에만 남고 새 세션에는 복사되지 않는다', () => {
  const first = confirmProfile(draft(), 'run-1', 'profile-1');
  const key = selectionKey('real', 'technology', '1');
  const item = { key, mode: 'real', source: 'technology', title: '후보', evidence: [] };
  const selected = updateRun(first, 'run-1', run => ({ ...run, items: [item], selectedKeys: [key], assumedKeys: [key] }));
  assert.deepEqual(selectedItems(activeRun(selected)), [item]);
  const changed = { ...selected, draftInput: { ...selected.draftInput, target_problem: '새 문제' } };
  const second = confirmProfile(changed, 'run-2', 'profile-2');
  assert.deepEqual(selectedItems(activeRun(second)), []);
  assert.deepEqual(second.runs[1].assumedKeys, []);
  assert.deepEqual(selected.runs[0].selectedKeys, [key]);
  assert.deepEqual(createSession('p1', 'session-b').runs, []);
});
