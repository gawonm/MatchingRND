import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { mockAnalysisReport } from '../src/data/mockAnalysisReport.ts';
import { parseReportMarkdown, REPORT_HEADINGS, safeLink } from '../src/lib/reportMarkdown.ts';

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

test('f2723bd render_answer fixture의 heading, quote, table, URL을 구조화한다', () => {
  const markdown = readFileSync(new URL('./fixtures/render-answer-f2723bd.md', import.meta.url), 'utf8');
  const sections = parseReportMarkdown(markdown);
  assert.deepEqual(sections.slice(1).map(section => section.heading), REPORT_HEADINGS);
  assert.equal(sections[1].blocks.some(block => block.type === 'quote'), true);
  assert.equal(sections[3].blocks.some(block => block.type === 'table'), true);
  assert.equal(sections[4].blocks.some(block => block.type === 'table' && block.rows[1][3].includes('https://example.go.kr/notice?id=1')), true);
  assert.equal(sections[6].blocks[0].type, 'paragraph');
});

test('외부 링크 프로토콜을 제한하고 HTML을 직접 주입하지 않는다', () => {
  assert.equal(safeLink('https://example.go.kr/notice?id=1'), 'https://example.go.kr/notice?id=1');
  assert.equal(safeLink('#e1'), '#e1');
  assert.equal(safeLink('javascript:alert(1)'), null);
  assert.doesNotMatch(component, /dangerouslySetInnerHTML/);
  assert.match(component, /noopener noreferrer/);
});
