import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { GAP_STATUS_LABELS, httpLinks, rankedSelection, rfpRequirements } from '../src/lib/analysisView.ts';

const rfpView = readFileSync(new URL('../src/components/analysis/RfpExplorer.tsx', import.meta.url), 'utf8');
const split = readFileSync(new URL('../src/components/analysis/SplitExplorer.tsx', import.meta.url), 'utf8');
const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');

const rfp = (id, rank, extra = {}) => ({ id, document_id: `doc-${id}`, rank, title: `과제 ${id}`, notice_titles: [], notice_urls: [], gap_analysis_status: 'analyzed', gap_item_ids: [], evidence_ids: [], ...extra });
const gap = (id, name, rfp_ids) => ({ id, gap_index: Number(id.slice(4)), requirement_id: `req-${id}`, requirement_name: name, requirement_clear: true, label: '부분충족', decision_path: '', rfp_ids, technology_ids: [], owned_technologies: [], evidence_ids: [], claim_indices: [] });

test('RFP 0·1·5건을 추천 순서로 정렬하고, 사라진 선택은 첫 후보로 전환한다', () => {
  assert.deepEqual(rankedSelection([], 'r1'), { ordered: [], selected: null, duplicates: 0 });
  assert.equal(rankedSelection([rfp('r1', 1)], null).selected.id, 'r1');
  const five = [rfp('r3', 3), rfp('r1', 1), rfp('r5', 5), rfp('r2', 2), rfp('r4', 4)];
  assert.deepEqual(rankedSelection(five, null).ordered.map(r => [r.rank, r.title]), [[1, '과제 r1'], [2, '과제 r2'], [3, '과제 r3'], [4, '과제 r4'], [5, '과제 r5']]);
  assert.equal(rankedSelection(five, 'r4').selected.id, 'r4');
  assert.equal(rankedSelection(five, 'old-run-id').selected.id, 'r1');
  assert.equal(five[0].id, 'r3'); // 원본 배열은 정렬하지 않는다
  // 같은 ID가 반복되면 순위가 앞선 후보만 남겨 다른 후보의 상세가 섞이지 않게 한다.
  const dup = rankedSelection([rfp('r2', 2, { evidence_ids: ['E2'] }), rfp('r1', 1, { evidence_ids: ['E1'] }), rfp('r1', 3, { evidence_ids: ['E9'] })], 'r1');
  assert.deepEqual(dup.ordered.map(r => [r.id, r.rank]), [['r1', 1], ['r2', 2]]);
  assert.deepEqual(dup.selected.evidence_ids, ['E1']);
  assert.equal(dup.duplicates, 1);
});

test('Gap 상태는 분석 수행 여부만 표시하고 요구기술은 이 RFP 범위의 GapItem만 연결한다', () => {
  assert.deepEqual(GAP_STATUS_LABELS, { analyzed: 'Gap 분석 완료', not_analyzed: 'Gap 미분석', unknown: '분석 여부 확인 불가' });
  const gaps = [gap('gap-0', '진동 신호 분석', ['r1']), gap('gap-1', '다른 RFP 요구기술', ['r2']), gap('gap-2', '공유 요구기술', ['r1', 'r2'])];
  const linked = rfpRequirements(rfp('r1', 1, { gap_item_ids: ['gap-0', 'gap-2', 'gap-1', 'gap-9', 'gap-0'] }), gaps);
  assert.deepEqual(linked.linked.map(g => g.requirement_name), ['진동 신호 분석', '공유 요구기술']);
  assert.equal(linked.unresolved, 2); // 다른 RFP 항목과 없는 ID는 이름을 만들지 않는다
  assert.deepEqual(rfpRequirements(rfp('r1', 1), gaps), { linked: [], unresolved: 0 }); // analyzed + 연결 0건
  for (const status of ['not_analyzed', 'unknown']) {
    assert.deepEqual(rfpRequirements(rfp('r1', 1, { gap_analysis_status: status, gap_item_ids: ['gap-0'] }), gaps), { linked: [], unresolved: 0 });
  }
  assert.match(rfpView, /Gap 미분석 — 기술요소별 판정이 수행되지 않았습니다/);
  assert.match(rfpView, /Gap 분석 여부를 확인할 수 없습니다/);
  assert.match(rfpView, /분석된 항목의 연결 정보 없음/);
  assert.doesNotMatch(rfpView, /근거부족|기술요건 없음/);
});

test('RFP 상세는 점수·적합도를 만들지 않고 공고 링크를 원문 PDF로 표시하지 않는다', () => {
  assert.deepEqual(httpLinks(['https://a.go.kr/n?id=1', 'javascript:alert(1)', '#e1', 'ftp://x', 'not a url']), ['https://a.go.kr/n?id=1']);
  assert.match(rfpView, /httpLinks\(selected\.notice_urls\)/);
  assert.match(rfpView, /RFP 원문 PDF가 아닙니다/);
  assert.match(rfpView, /추천 \{selected\.rank\}순위/);
  assert.doesNotMatch(rfpView, /%|적합도 \d|score|similarity|pdf_url|markdown|notice_titles\[[^\]]*\].*notice_urls\[/);
  assert.match(rfpView, /noopener noreferrer/);
});

test('RFP 근거는 선택 후보의 evidence_ids만 공통 EvidenceExplorer로 표시한다', () => {
  assert.match(rfpView, /evidenceItems\.filter\(item => selected\.evidence_ids\.includes\(item\.id\)\)/);
  assert.match(rfpView, /<EvidenceExplorer key=\{selected\.id\} items=\{evidence\} report=\{report\} \/>/);
  assert.match(rfpView, /연결된 검증 근거 없음/);
});

test('목록은 선택 상태가 있는 버튼이고 모바일 상세는 목록으로 복귀하며 포커스·스크롤을 되돌린다', () => {
  assert.match(rfpView, /<SplitExplorer name="rfp"/);
  assert.match(split, /<button type="button"[^>]*aria-pressed=\{item\.id === selected\.id\}/);
  assert.match(split, /목록으로/);
  assert.match(split, /window\.scrollTo\(\{ top: listScroll\.current, behavior: 'instant' \}\)/);
  assert.match(split, /returnTo\.current = selected\.id/);
  assert.match(split, /rows\.current\.get\(returnTo\.current\)\?\.focus/);
  assert.match(split, /heading\.current\?\.focus\(\{ preventScroll: true \}\);\r?\n\s*heading\.current\?\.closest\('section'\)\?\.scrollIntoView/);
});

test('Workspace는 Overview·기술·RFP·Gap·Evidence·Report 순서이고 선택은 새 결과에서만 초기화된다', () => {
  const tabs = [...wizard.matchAll(/<Tab eventKey="(\w+)"/g)].map(m => m[1]);
  assert.deepEqual(tabs, ['overview', 'technology', 'rfp', 'gap', 'evidence', 'report']);
  assert.match(wizard, /const initialExplore = \{ technology: initialSplitView, rfp: initialSplitView, gap: \{ \.\.\.initialSplitView, rfpId: null \} as GapViewState \};/);
  assert.match(wizard, /if \(explore\.source !== report\.result\) setExplore\(\{ source: report\.result, \.\.\.initialExplore \}\)/);
  assert.match(wizard, /setExplore\(current => \(\{ \.\.\.current, rfp: next \}\)\)/);
  assert.match(wizard, /구조화 RFP 정보를 이용할 수 없습니다\{viewCode\}\. 보고서는 정상 생성되었으며/);
  // RFP 선택은 분석 API를 호출하지 않는다.
  assert.doesNotMatch(rfpView, /api|fetch\(|onRun/);
  assert.doesNotMatch(split, /api|fetch\(|onRun/);
});

test('같은 GapItem.id가 반복돼도 연결은 id당 하나이고 미연결 개수가 줄어들지 않는다', () => {
  const dup = [gap('gap-0', '첫 항목', ['r1']), gap('gap-0', '중복 항목', ['r1'])];
  const result = rfpRequirements(rfp('r1', 1, { gap_item_ids: ['gap-0', 'gap-9'] }), dup);
  assert.deepEqual(result.linked.map(g => g.requirement_name), ['첫 항목']);
  assert.equal(result.unresolved, 1);
});
