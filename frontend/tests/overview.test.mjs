import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { COMMON_RND_NOTICES, primaryCandidate } from '../src/lib/analysisView.ts';

const picks = readFileSync(new URL('../src/components/analysis/PrimaryPicks.tsx', import.meta.url), 'utf8');
const overview = readFileSync(new URL('../src/components/AnalysisReportView.tsx', import.meta.url), 'utf8');
const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');

const item = (id, rank) => ({ id, rank, title: `후보 ${id}` });

test('우선 추천은 primary ID와 일치하는 후보만 쓰고 없거나 불일치하면 다른 후보로 대체하지 않는다', () => {
  const items = [item('b', 2), item('a', 1), item('c', 3)];
  assert.deepEqual(primaryCandidate(items, 'a'), item('a', 1));
  assert.equal(primaryCandidate(items, 'c').rank, 3); // 실제 rank를 그대로 쓴다
  assert.equal(primaryCandidate(items, null), 'missing');
  assert.equal(primaryCandidate(items, 'zzz'), 'missing');
  assert.equal(primaryCandidate([], 'a'), 'empty');
  assert.equal(primaryCandidate([], null), 'empty');
  assert.deepEqual(primaryCandidate([item('a', 1), { ...item('a', 4), title: '중복' }], 'a'), item('a', 1)); // 중복 id는 순위가 앞선 첫 후보
});

test('Overview 카드는 구조화 view만 쓰고 Markdown 재추출·Gap 숫자·점수를 만들지 않는다', () => {
  assert.match(picks, /primaryCandidate\(view\.technologies, view\.overview\.primary_technology_id\)/);
  assert.match(picks, /primaryCandidate\(view\.rfps, view\.overview\.primary_rfp_id\)/);
  assert.match(picks, /추천된 나눔기술이 없습니다\./);
  assert.match(picks, /추천된 RFP가 없습니다\./);
  assert.match(picks, /우선 추천 나눔기술을 구조화 결과에서 확인할 수 없습니다/);
  assert.match(picks, /우선 추천 RFP를 구조화 결과에서 확인할 수 없습니다/);
  assert.match(picks, /Gap 분석은 추천 RFP의 요구 기술요소를 기준으로 수행합니다\. 분석된 RFP의 상세 판정은 Gap 탭에서 확인할 수 있습니다\./);
  assert.doesNotMatch(picks, /markdown|gap_label_counts|gap_items|\.label\b|%|score|적합도 \d/);
  // 이동 버튼은 확인된 후보에만 있다.
  assert.match(picks, /onClick=\{\(\) => onOpenTechnology\(technology\.id\)\}>기술 상세 보기 →/);
  assert.match(picks, /onClick=\{\(\) => onOpenRfp\(rfp\.id\)\}>RFP 상세 보기 →/);
});

test('view가 있으면 구조화 카드, Projection 실패면 기존 Markdown 요약을 유지하고 공통 유의사항은 그대로다', () => {
  assert.match(wizard, /<ReportOverview report=\{report\.result\.report\} onOpenReport=\{\(\) => setTab\('report'\)\}>\r?\n\s*\{structured && <PrimaryPicks view=\{structured\} onOpenTechnology=\{openTechnology\} onOpenRfp=\{openRfp\} \/>\}/);
  assert.match(overview, /\{children \?\? overviewSections\.map/);
  assert.match(overview, /전체 보고서 · 원문 근거 보기/);
  assert.match(wizard, /!reportHasCommonNotice\(report\.result\.report\.markdown\)/);
  assert.equal(COMMON_RND_NOTICES.length, 4);
});

test('Overview → 기술·RFP 이동은 대상만 선택하고 반복 이동에도 포커스를 요청하며 API를 호출하지 않는다', () => {
  assert.match(wizard, /const openRfp = \(rfpId: string\) => \{ setExplore\(current => \(\{ \.\.\.current, rfp: \{ selectedId: rfpId, mobileDetailOpen: true \} \}\)\); setTab\('rfp'\); setFocusRequest\(\{ id: 'rfp-detail-title' \}\); \};/);
  assert.match(wizard, /setFocusRequest\(\{ id: 'technology-detail-title' \}\)/);
  assert.doesNotMatch(picks, /api|fetch\(|onRun/);
});
