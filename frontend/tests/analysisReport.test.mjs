import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { mockAnalysisReport } from '../src/data/mockAnalysisReport.ts';

const component = readFileSync(new URL('../src/components/AnalysisReportView.tsx', import.meta.url), 'utf8');
const types = readFileSync(new URL('../src/types/analysisReport.ts', import.meta.url), 'utf8');

test('FinalAnswer 계약과 7개 공개 섹션을 사용한다', () => {
  for (const heading of ['1. 우선 추천 나눔기술', '2. 우선 추천 공고', '3. 기술요소 Gap', '4. 관련 RFP', '5. 관련 나눔기술', '6. 관련 법령', '7. 확인이 필요한 사항']) {
    assert.match(mockAnalysisReport.markdown, new RegExp(heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  for (const field of ['method:', 'status:', 'markdown:', 'claims:', 'evidence:', 'warnings:', 'stats:']) assert.match(types, new RegExp(field));
  assert.match(component, /실제 분석 결과가 아니며 실제 API는 연결되지 않았습니다/);
});

test('AnalysisState API를 자동 호출하지 않고 Mock 경계를 유지한다', () => {
  assert.doesNotMatch(component, /fetch\(|api\/analysis/);
  assert.equal(mockAnalysisReport.status, 'template');
  assert.equal(mockAnalysisReport.method, 'local');
});
