import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { mockAnalysisReport } from '../src/data/mockAnalysisReport.ts';
import { parseReportMarkdown, REPORT_HEADINGS, safeLink } from '../src/lib/reportMarkdown.ts';

const component = readFileSync(new URL('../src/components/AnalysisReportView.tsx', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');
const mockViews = ['FlowViews', 'SessionViews', 'DiscoverExplorer'].map(name => readFileSync(new URL(`../src/components/${name}.tsx`, import.meta.url), 'utf8'));
const types = readFileSync(new URL('../src/types/analysisReport.ts', import.meta.url), 'utf8');

test('FinalAnswer 계약과 7개 공개 섹션을 사용한다', () => {
  for (const heading of ['1. 우선 추천 나눔기술', '2. 우선 추천 공고', '3. 기술요소 Gap', '4. 관련 RFP', '5. 관련 나눔기술', '6. 관련 법령', '7. 확인이 필요한 사항']) {
    assert.match(mockAnalysisReport.markdown, new RegExp(heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }
  for (const field of ['method:', 'status:', 'markdown:', 'claims:', 'evidence:', 'warnings:', 'stats:']) assert.match(types, new RegExp(field));
  assert.match(component, /실제 분석 결과가 아닌 Mock 미리보기입니다/);
});

test('AnalysisState API를 자동 호출하지 않고 Mock 경계를 유지한다', () => {
  assert.doesNotMatch(component, /fetch\(|api\/analysis/);
  // 실제 분석은 승인된 Workspace 프로필에서만 실행되며 Mock/데모 화면은 보고서 API에 접근하지 않는다.
  assert.match(app, /if \(!approved \|\| !reportKey/);
  assert.match(wizard, /disabled=\{!approved\} onClick=\{run\}/);
  for (const view of mockViews) assert.doesNotMatch(view, /createAnalysisReport|api\/analysis/);
  assert.match(app, /\{page === 'workspace' && <WorkspaceWizard/);
  assert.equal(app.match(/createAnalysisReport\(/g).length, 1);
  // 같은 승인 버전의 진행 중 요청이 있으면 중복 실행하지 않는다.
  assert.match(app, /reportsInFlight\.current\.has\(reportKey\)\) return;/);
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

test('추천 우선순위, 섹션 이동, 접을 수 있는 원문 인용을 제공한다', () => {
  assert.match(component, /report-priority/);
  assert.match(component, /보고서 섹션 바로가기/);
  assert.match(component, /scrollIntoView/);
  assert.doesNotMatch(component, /href={`#report-section/);
  assert.match(component, /<details className="report-citation">/);
  assert.match(component, /원문 인용 보기/);
});

test('장시간 분석은 가짜 퍼센트 없이 상태와 재시도를 안내한다', () => {
  assert.match(wizard, /role="status"/);
  assert.match(wizard, /실제 진행률은 제공되지 않으며/);
  assert.match(wizard, /role="alert"[^]*다시 시도/);
  assert.doesNotMatch(wizard, /\d+%|progress-bar|ProgressBar/);
});
