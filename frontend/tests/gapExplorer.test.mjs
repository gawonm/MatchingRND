import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { GAP_LABELS, gapClaims, gapLabelText, gapSelection, gapTechnologies, rejectedGapClaimReasons } from '../src/lib/analysisView.ts';

const gapView = readFileSync(new URL('../src/components/analysis/GapExplorer.tsx', import.meta.url), 'utf8');
const rfpView = readFileSync(new URL('../src/components/analysis/RfpExplorer.tsx', import.meta.url), 'utf8');
const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');

const rfp = (id, gap_item_ids, status = 'analyzed') => ({ id, document_id: `doc-${id}`, rank: 1, title: id, notice_titles: [], notice_urls: [], gap_analysis_status: status, gap_item_ids, evidence_ids: [] });
const gap = (index, extra = {}) => ({ id: `gap-${index}`, gap_index: index, requirement_id: `req-${index}`, requirement_name: `요구 ${index}`, requirement_clear: true, label: '부분충족', decision_path: 'company:partial', rfp_ids: ['r1'], technology_ids: [], owned_technologies: [], evidence_ids: [], claim_indices: [], ...extra });
const tech = (id, gap_item_ids) => ({ id, rank: 1, title: id, provider: null, transfer_condition: null, match_level: 'same', rationale: null, gap_item_ids, evidence_ids: [] });
const claim = (text, { section = 'gap', gap_index = 0, accepted = true, ok = true, evidence_id = 'E1', reason = '' } = {}) => ({
  draft: { section, gap_index, text, citations: [{ evidence_id, quote: 'q' }] }, accepted, reason, citations: [{ evidence_id, quote: 'q', ok, reason: '' }],
});
const report = claims => ({ method: 'llm', status: 'ok', markdown: '', claims, evidence: [{ evidence_id: 'E1', evidence: {} }], warnings: [], stats: {} });

test('Gap 5분류는 그대로 표시하고 알 수 없는 label은 5분류로 바꾸지 않는다', () => {
  assert.deepEqual(Object.values(GAP_LABELS), ['기존보유', '외부기술보완', '부분충족', '추가 R&D 검토 후보', '근거부족']);
  for (const label of ['기존보유', '외부기술보완', '부분충족', '근거부족']) assert.equal(gapLabelText(label), label);
  assert.equal(gapLabelText('추가R&D검토후보'), '추가 R&D 검토 후보');
  assert.equal(gapLabelText('충족'), '판정 확인 불가 (충족)');
  assert.equal(gapLabelText('toString'), '판정 확인 불가 (toString)');
  assert.match(gapView, /근거부족은 기술이 없다는 판정이 아니라/);
  assert.match(gapView, /!gap\.requirement_clear && <p className="small mb-0">요구기술 표현의 명확성 확인 필요<\/p>/);
  assert.doesNotMatch(gapView, /decision_path|markdown|%|score/); // 내부 판정 경로·보고서 재추출·점수를 쓰지 않는다
});

test('선택 RFP와 양방향으로 연결된 Gap만 gap_index 순으로 보여주고 같은 이름도 id로 구분한다', () => {
  const items = [gap(2, { requirement_name: '같은 이름' }), gap(0), gap(1, { rfp_ids: ['r2'] }), gap(3, { requirement_name: '같은 이름' }), gap(0, { requirement_name: '중복 id' })];
  const result = gapSelection(rfp('r1', ['gap-3', 'gap-1', 'gap-0', 'gap-2', 'gap-9']), items, null);
  assert.deepEqual(result.ordered.map(g => [g.id, g.requirement_name]), [['gap-0', '요구 0'], ['gap-2', '같은 이름'], ['gap-3', '같은 이름']]);
  assert.equal(result.selected.id, 'gap-0');
  assert.equal(result.duplicates, 1); // 같은 gap-0이 두 번 오면 첫 항목만
  assert.equal(result.unresolved, 2); // gap-1(다른 RFP), gap-9(없음)
  assert.equal(gapSelection(rfp('r1', ['gap-3', 'gap-0']), items, 'gap-3').selected.id, 'gap-3');
  assert.equal(gapSelection(rfp('r1', ['gap-0']), items, 'gap-3').selected.id, 'gap-0'); // 사라진 선택은 첫 항목
  assert.deepEqual(gapSelection(rfp('r1', []), items, null), { ordered: [], selected: null, duplicates: 0, unresolved: 0 });
  for (const status of ['not_analyzed', 'unknown']) assert.equal(gapSelection(rfp('r1', ['gap-0'], status), items, null).selected, null);
});

test('검증된 설명은 같은 gap_index의 accepted gap claim이 이 응답의 근거를 유효하게 인용할 때만 쓴다', () => {
  const claims = [claim('검증된 설명'), claim('거절', { accepted: false, reason: '의미 검토 실패' }), claim('다른 행', { gap_index: 1 }), claim('다른 섹션', { section: 'rfp' }),
    claim('무효 인용', { ok: false }), claim('없는 근거', { evidence_id: 'E9' })];
  assert.deepEqual(gapClaims(report(claims), gap(0, { claim_indices: [0, 1, 2, 3, 4, 5, 7, 0] })), ['검증된 설명']);
  assert.deepEqual(gapClaims(report(claims), gap(0)), []);
  assert.deepEqual(rejectedGapClaimReasons(report(claims), gap(0)), ['의미 검토 실패']);
  assert.deepEqual(rejectedGapClaimReasons(report(claims), gap(1)), []);
  assert.match(gapView, /생성된 판정 설명이 검증을 통과하지 못해 표시되지 않았습니다\. Gap 라벨은 별도의 근거·판정 규칙 결과입니다\./);
  assert.match(gapView, /별도의 검증된 설명이 제공되지 않았습니다\. 아래 연결 기술과 근거를 확인하세요\./);
  assert.match(gapView, /별도의 검증된 설명과 연결된 기술·근거가 제공되지 않았습니다\./);
});

test('외부 나눔기술은 technology_ids와 gap_item_ids 양쪽이 확인될 때만 연결하고 보유기술은 있는 값만 쓴다', () => {
  const technologies = [tech('pub-1', ['gap-0']), tech('pub-2', ['gap-5']), tech('pub-3', ['gap-0'])];
  const result = gapTechnologies(gap(0, { technology_ids: ['pub-1', 'pub-2', 'pub-3', 'pub-9', 'pub-1'] }), technologies);
  assert.deepEqual(result.linked.map(t => t.id), ['pub-1', 'pub-3']);
  assert.equal(result.unresolved, 2);
  assert.deepEqual(gapTechnologies(gap(0), technologies), { linked: [], unresolved: 0 });
  assert.match(gapView, /gap\.owned_technologies\.length \?/);
  assert.match(gapView, /연결된 보유기술 정보 없음/);
  assert.match(gapView, /기술이전·기술 확보를 뜻하지 않습니다/);
  assert.match(gapView, /onClick=\{\(\) => onOpenTechnology\(technology\.id\)\}/); // 확인된 후보에만 이동 버튼
});

test('Gap 근거는 선택 항목의 evidence_ids만 공통 EvidenceExplorer로 표시하고 미분석 RFP에 판정을 만들지 않는다', () => {
  assert.match(gapView, /evidenceItems\.filter\(item => gap\.evidence_ids\.includes\(item\.id\)\)/);
  assert.match(gapView, /<EvidenceExplorer key=\{gap\.id\} items=\{evidence\} report=\{report\} \/>/);
  assert.match(gapView, /연결된 검증 근거가 없습니다\./);
  assert.match(gapView, /rfps\.filter\(rfp => rfp\.gap_analysis_status === 'analyzed'\)/);
  assert.match(gapView, /해당 RFP는 추천 대상이지만 기술요소별 Gap 분석을 수행하지 않았습니다\./);
  assert.match(gapView, /해당 RFP의 Gap 분석 수행 여부를 확인할 수 없습니다\./);
  assert.match(gapView, /Gap 분석이 확인된 RFP가 없습니다\. 추천 RFP와 최종 보고서를 확인하세요\./);
  assert.match(gapView, /<SplitExplorer name="gap"/);
});

test('RFP → Gap → 기술 이동은 상태만 바꾸고 API를 호출하지 않는다', () => {
  assert.match(rfpView, /onClick=\{\(\) => onOpenGap\(selected\.id, gap\.id\)\}/);
  assert.match(wizard, /const openGap = \(rfpId: string, gapItemId: string\) => \{ setExplore\(current => \(\{ \.\.\.current, gap: \{ rfpId, selectedId: gapItemId, mobileDetailOpen: true \} \}\)\); setTab\('gap'\); setFocusRequest\(\{ id: 'gap-detail-title' \}\); \};/);
  assert.match(wizard, /const openTechnology = \(technologyId: string\) => \{ setExplore\(current => \(\{ \.\.\.current, technology: \{ selectedId: technologyId, mobileDetailOpen: true \} \}\)\); setTab\('technology'\); setFocusRequest\(\{ id: 'technology-detail-title' \}\); \};/);
  // 같은 대상으로 다시 이동해도 포커스 요청은 새 객체라 매번 실행된다.
  assert.match(wizard, /useEffect\(\(\) => \{ if \(focusRequest\) document\.getElementById\(focusRequest\.id\)\?\.focus\(\); \}, \[focusRequest\]\);/);
  assert.match(wizard, /구조화 Gap 정보를 이용할 수 없습니다\{viewCode\}\. 보고서는 정상 생성되었으며/);
  for (const source of [gapView, rfpView]) assert.doesNotMatch(source, /api|fetch\(|onRun/);
});
