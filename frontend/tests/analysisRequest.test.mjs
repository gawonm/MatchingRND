import assert from 'node:assert/strict';
import test from 'node:test';
import { analysisRequestFromInput } from '../src/lib/analysisRequest.ts';

const elements = [
  { role: 'owned', name: '보유 A' },
  { role: 'goal', name: '필요 B' },
  { role: 'uncertain', name: '보류 C' },
];

test('원문 질문과 승인된 A/B를 그대로 AnalysisRequest에 전달한다', () => {
  const request = analysisRequestFromInput({ technology_description: 'A 설명', required_technology: 'B 설명', target_problem: '문제', original_query: '  원문 질문 전체?  ', policy_question: '조건?' }, elements);
  assert.deepEqual(request, { problem: '원문 질문 전체?', owned_technologies: ['보유 A'], unmet_elements: ['필요 B'], policy_question: '조건?' });
});

test('원문 질문이 없으면 세 입력칸의 문맥을 모두 보존한다', () => {
  const request = analysisRequestFromInput({ technology_description: 'A 설명', required_technology: 'B 설명', target_problem: '문제' }, elements);
  assert.equal(request.problem, '현재 보유한 기술: A 설명\n보완·확보하고 싶은 기술: B 설명\n해결하려는 문제: 문제');
});
