import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { claimsForEvidence, COMMON_RND_INTRO, COMMON_RND_NOTICES, COMMON_RND_NOTICE_TITLE, viewAvailability } from '../src/lib/analysisView.ts';

const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');
const explorer = readFileSync(new URL('../src/components/analysis/EvidenceExplorer.tsx', import.meta.url), 'utf8');

const claim = (text, evidenceId, { accepted = true, ok = true } = {}) => ({
  draft: { section: 'gap', gap_index: 0, text, citations: [{ evidence_id: evidenceId, quote: 'q' }] },
  accepted, reason: '', citations: [{ evidence_id: evidenceId, quote: 'q', ok, reason: '' }],
});
const record = id => ({ evidence_id: id, evidence: { doc_id: 'd', source: 'rfp', section: null, page: null, bbox: null, quote: 'q', verified: true, extra: {} } });
const item = (id, claim_indices = [], extra = {}) => ({ id, source_type: 'rfp', document_id: 'd', chunk_id: null, section: null, page: null, quote: '원문', source_title: null, notice_urls: [], claim_indices, ...extra });
const response = ({ status = 'ok', claims = [], evidence = ['E1', 'E2'], items = [item('E1', [0])], view_status = 'ok', view = true } = {}) => ({
  report: { method: 'llm', status, markdown: '# 결과', claims, evidence: evidence.map(record), warnings: [], stats: {} },
  view: view ? { technologies: [], rfps: [], gap_items: [], evidence_items: items, overview: { primary_technology_id: null, primary_rfp_id: null, gap_label_counts: {} } } : null,
  view_status, view_error: view_status === 'ok' ? null : 'projection_error',
});

test('응답 상태: Projection 실패·근거 0건·다른 실행 근거 혼입을 보고서 상태와 분리해 판정한다', () => {
  const claims = [claim('주장', 'E1')];
  assert.equal(viewAvailability(response({ claims })), 'ok');
  assert.equal(viewAvailability(response({ status: 'partial', claims })), 'ok'); // 보고서 partial ≠ view 실패
  assert.equal(viewAvailability(response({ view_status: 'failed', view: false })), 'failed');
  assert.equal(viewAvailability(response({ items: [] })), 'empty');
  assert.equal(viewAvailability(response({ claims, items: [item('E9')] })), 'mismatch'); // 이 응답에 없는 근거
  // 없는 claim 인덱스는 패널 전체를 닫지 않고 해당 연결만 버린다.
  const broken = response({ claims, items: [item('E1', [3])] });
  assert.equal(viewAvailability(broken), 'ok');
  assert.deepEqual(claimsForEvidence(broken.report, broken.view.evidence_items[0]), []);
});

test('claim 연결은 accepted이고 이 근거를 유효하게 인용한 claim만 사용한다', () => {
  const claims = [claim('검증된 주장', 'E1'), claim('거절된 주장', 'E1', { accepted: false }), claim('다른 근거', 'E2'), claim('무효 인용', 'E1', { ok: false })];
  const report = response({ claims }).report;
  assert.deepEqual(claimsForEvidence(report, item('E1', [0, 1, 2, 3, 7])).map(c => c.text), ['검증된 주장']);
  assert.deepEqual(claimsForEvidence(report, item('E1')), []);
});

test('근거 상세는 RFP 공고 링크만 표시하고 URL을 만들지 않으며 키보드로 닫을 수 있다', () => {
  assert.match(explorer, /item\.source_type === 'rfp' \? httpLinks\(item\.notice_urls\) : \[\]/);
  assert.match(explorer, /공고 링크/);
  assert.doesNotMatch(explorer, /PDF|pdf_url|document_url|`https?:/);
  assert.match(explorer, /event\.key === 'Escape'/);
  assert.match(explorer, /opener\.current\?\.focus\(\)/);
  assert.match(explorer, /heading\.current\?\.focus\(\)/);
  assert.match(explorer, /aria-pressed/);
});

test('공통 R&D 유의사항 4개 문구와 도입 문구는 백엔드 섹션 6과 같고 Overview에 항상 표시한다', () => {
  assert.deepEqual([...COMMON_RND_NOTICES], [
    '국가 R&D 과제 참여 시 국가연구개발혁신법 적용 여부 확인',
    '연구개발비 사용 및 정산 기준 확인',
    '연구개발성과의 소유·활용 조건 확인',
    '나눔기술 도입 시 기술이전 조건 및 지식재산권 확인',
  ]);
  // 백엔드(app/answer_format.py) 상수와 문자열이 그대로 일치해야 한다.
  const backend = readFileSync(new URL('../../app/answer_format.py', import.meta.url), 'utf8');
  for (const text of [...COMMON_RND_INTRO, ...COMMON_RND_NOTICES]) assert.ok(backend.includes(`'${text}'`), text);
  assert.ok(backend.includes(`'6. ${COMMON_RND_NOTICE_TITLE}'`));
  // Overview는 보고서 섹션 6을 그리지 않으므로 보고서 내용과 무관하게 항상 표시한다.
  assert.doesNotMatch(wizard, /reportHasCommonNotice/);
  assert.match(wizard, /\n\s*<section className="app-card p-3 mt-3" aria-labelledby="common-rnd-notice">/);
  assert.match(wizard, /\{COMMON_RND_INTRO\.join\(' '\)\}/);
  assert.doesNotMatch(wizard, /적합(합니다|함|성 확인 완료)|법령 검증 완료/);
});

test('Projection 실패여도 Report 탭은 같은 report를 그대로 표시한다', () => {
  assert.match(wizard, /<AnalysisReportView report=\{report\.result\.report\} mode="real" \/>/);
  assert.match(wizard, /보고서는 정상 생성되었으며 Report 탭에서 확인할 수 있습니다/);
});
