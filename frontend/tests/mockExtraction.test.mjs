import assert from 'node:assert/strict';
import test from 'node:test';
import { mockExtractTechnologyElements } from '../src/utils/mockExtraction.ts';

test('mock suggestions preserve source sentences and keep owned and goal elements separate', () => {
  const input = {
    technology_description: '진동 데이터를 분석합니다. 센서 신호를 사용합니다.',
    target_problem: '고장 시점을 예측하고 싶습니다.',
  };
  const elements = mockExtractTechnologyElements(input);
  assert.deepEqual(elements.map(item => item.role), ['owned', 'owned', 'goal']);
  assert.deepEqual(elements.map(item => item.evidence), [
    '진동 데이터를 분석합니다.', '센서 신호를 사용합니다.', '고장 시점을 예측하고 싶습니다.',
  ]);
  assert.ok(elements.every(item => item.category === '미분류'));
  assert.ok(elements.every(item => item.name === ''));
});

test('mock suggestions do not invent elements for blank input', () => {
  assert.deepEqual(mockExtractTechnologyElements({
    technology_description: '  ', target_problem: '\n ',
  }), []);
});

test('identical source sentences are shown once without merging different sources', () => {
  const elements = mockExtractTechnologyElements({
    technology_description: '진동 분석. 진동 분석.',
    target_problem: '진동 분석.',
  });
  assert.deepEqual(elements.map(item => [item.source, item.evidence]), [
    ['보유 기술', '진동 분석.'], ['기술 문제', '진동 분석.'],
  ]);
});
