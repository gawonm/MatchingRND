import assert from 'node:assert/strict';
import test from 'node:test';
import { toggleTechnologyTag } from '../src/utils/technologyInput.ts';
const empty = { technology_domains: [], technology_tags: [], technology_description: '진동 데이터 기반 이상 탐지 모델', target_problem: '고장 사전 예측' };

test('cross-domain selection retains tags and free text without mutating the previous value', () => {
  const machine = toggleTechnologyTag(empty, '예지보전');
  const mixed = toggleTechnologyTag(machine, '이상 탐지');
  assert.deepEqual(mixed.technology_domains, ['기계·제조', 'AI·정보통신']);
  assert.deepEqual(mixed.technology_tags, ['예지보전', '이상 탐지']);
  assert.equal(mixed.technology_description, empty.technology_description);
  assert.equal(mixed.target_problem, empty.target_problem);
  assert.deepEqual(machine.technology_tags, ['예지보전']);
  assert.deepEqual(empty.technology_tags, []);
});
test('removal retains a domain until its last selected technology is removed', () => {
  let input = toggleTechnologyTag(toggleTechnologyTag(toggleTechnologyTag(empty, '예지보전'), '센서·계측'), '이상 탐지');
  input = toggleTechnologyTag(input, '예지보전');
  assert.deepEqual(input.technology_domains, ['기계·제조', 'AI·정보통신']);
  input = toggleTechnologyTag(input, '센서·계측');
  assert.deepEqual(input.technology_domains, ['AI·정보통신']);
  assert.deepEqual(input.technology_tags, ['이상 탐지']);
  assert.deepEqual(toggleTechnologyTag(input, '이상 탐지'), empty);
});
test('unknown choices are ignored and toggling cannot create duplicate tags', () => {
  assert.equal(toggleTechnologyTag(empty, '없는 기술'), empty);
  const once = toggleTechnologyTag(empty, '예지보전');
  assert.deepEqual(toggleTechnologyTag(toggleTechnologyTag(once, '예지보전'), '예지보전'), once);
});
