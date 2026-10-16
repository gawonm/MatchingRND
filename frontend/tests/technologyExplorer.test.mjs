import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { MATCH_LEVEL_LABELS, matchLevelLabel, rankedSelection, technologyRequirements } from '../src/lib/analysisView.ts';

const techView = readFileSync(new URL('../src/components/analysis/TechnologyExplorer.tsx', import.meta.url), 'utf8');
const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');

const tech = (id, rank, extra = {}) => ({ id, rank, title: `기술 ${id}`, provider: null, transfer_condition: null, match_level: 'same', rationale: null, gap_item_ids: [], evidence_ids: [], ...extra });
const gap = (id, name, technology_ids) => ({ id, gap_index: Number(id.slice(4)), requirement_id: `req-${id}`, requirement_name: name, requirement_clear: true, label: '외부기술보완', decision_path: '', rfp_ids: ['r1'], technology_ids, owned_technologies: [], evidence_ids: [], claim_indices: [] });

test('기술 0·1·5건을 rank 순으로 보여주고 사라진 선택은 첫 후보로 대체한다', () => {
  assert.deepEqual(rankedSelection([], 't1'), { ordered: [], selected: null, duplicates: 0 });
  assert.equal(rankedSelection([tech('t1', 1)], null).selected.id, 't1');
  const five = [tech('t4', 4), tech('t2', 2), tech('t5', 5), tech('t1', 1), tech('t3', 3)];
  assert.deepEqual(rankedSelection(five, null).ordered.map(t => t.rank), [1, 2, 3, 4, 5]);
  assert.equal(rankedSelection(five, 't3').selected.title, '기술 t3');
  assert.equal(rankedSelection(five, 'previous-run').selected.id, 't1');
  assert.match(techView, /추천된 나눔기술이 없습니다/);
});

test('match_level은 same·similar만 일치·유사로 표시하고 그 밖의 값은 변환하지 않는다', () => {
  assert.deepEqual(MATCH_LEVEL_LABELS, { same: '기술요소 일치', similar: '기술요소 유사' });
  assert.equal(matchLevelLabel('same'), '기술요소 일치');
  assert.equal(matchLevelLabel('similar'), '기술요소 유사');
  assert.equal(matchLevelLabel(null), '판정 정보 미제공');
  assert.equal(matchLevelLabel('partial'), '확인되지 않은 판정값 (partial)');
  assert.equal(matchLevelLabel('constructor'), '확인되지 않은 판정값 (constructor)'); // 프로토타입 키를 판정으로 오인하지 않는다
  // 목록에는 확인된 판정값만 붙인다.
  assert.match(techView, /Object\.hasOwn\(MATCH_LEVEL_LABELS, technology\.match_level\)/);
});

test('제공기관·이전조건·추천 이유는 있는 값만 쓰고 없으면 추측하지 않으며 검증 수준을 구분한다', () => {
  assert.match(techView, /selected\.provider \?\? <span className="text-secondary">제공기관 정보 없음<\/span>/);
  assert.match(techView, /selected\.transfer_condition \?\? <span className="text-secondary">기술이전 조건 정보 없음<\/span>/);
  assert.match(techView, /실제 기술이전 가능 여부와 세부 조건은 제공기관 확인이 필요합니다\./);
  assert.match(techView, /추천 이유 — AI 생성 설명/);
  assert.match(techView, /관련 인용은 확인되었으나, 설명 자체의 기술적 타당성을 최종 검증한 결과는 아닙니다\./);
  // 근거가 없으면 없는 근거를 확인하라고 안내하지 않는다.
  assert.match(techView, /evidence\.length \? '제공된 추천 설명이 없습니다\. 연결된 원문 근거를 확인하세요\.' : '제공된 추천 설명이 없습니다\.'/);
  assert.doesNotMatch(techView, /기술적 적합성 검증 완료|추천 타당성 최종 검증|의미 검토 통과|요구조건 충족(?!을 뜻하지)|%|score|markdown/);
});

test('요구 기술요소는 GapItem.id와 GapItem.technology_ids 양쪽이 확인된 경우만 연결한다', () => {
  const gaps = [gap('gap-0', '진동 신호 분석', ['t1']), gap('gap-1', '다른 기술의 요구기술', ['t2']), gap('gap-2', '공유 요구기술', ['t1', 't2'])];
  const result = technologyRequirements(tech('t1', 1, { gap_item_ids: ['gap-0', 'gap-1', 'gap-2', 'req-gap-0', 'gap-0'] }), gaps);
  assert.deepEqual(result.linked.map(g => g.requirement_name), ['진동 신호 분석', '공유 요구기술']);
  assert.equal(result.unresolved, 2); // 역방향 관계가 없는 gap-1, requirement_id 형태의 값은 연결하지 않는다
  assert.deepEqual(technologyRequirements(tech('t1', 1), gaps), { linked: [], unresolved: 0 });
  assert.match(techView, /연결된 요구 기술요소 없음/);
});

test('기술 근거는 선택 후보의 evidence_ids만 공통 EvidenceExplorer로 표시한다', () => {
  assert.match(techView, /evidenceItems\.filter\(item => selected\.evidence_ids\.includes\(item\.id\)\)/);
  assert.match(techView, /<EvidenceExplorer key=\{selected\.id\} items=\{evidence\} report=\{report\} \/>/);
  assert.match(techView, /연결된 검증 근거가 없습니다\./);
  assert.match(techView, /<SplitExplorer name="technology"/);
  assert.doesNotMatch(techView, /api|fetch\(|onRun|href=/);
});

test('Workspace 기술 탭은 구조화 view가 있을 때만 열리고 실패 시 Report를 유지하며 선택은 탭별로 보존된다', () => {
  assert.match(wizard, /<Tab eventKey="technology" title="기술">/);
  assert.match(wizard, /구조화 기술 정보를 이용할 수 없습니다\{viewCode\}\. 보고서는 정상 생성되었으며/);
  assert.match(wizard, /const structured = report\.result\?\.view && \(availability === 'ok' \|\| availability === 'empty'\) \? report\.result\.view : null;/);
  assert.match(wizard, /setExplore\(current => \(\{ \.\.\.current, technology: next \}\)\)/);
  assert.match(wizard, /<AnalysisReportView report=\{report\.result\.report\} mode="real" \/>/);
});

test('RFP·기술 후보는 같은 응답의 GapItem.id를 gap_item_ids로 참조하고 옛 필드명은 남지 않는다', () => {
  const types = readFileSync(new URL('../src/types/analysisReport.ts', import.meta.url), 'utf8');
  const lib = readFileSync(new URL('../src/lib/analysisView.ts', import.meta.url), 'utf8');
  assert.equal(types.match(/gap_item_ids: string\[\];/g).length, 2);
  for (const source of [types, lib, techView]) assert.doesNotMatch(source, /matched_requirement_ids/);
  assert.match(lib, /new Set\(rfp\.gap_item_ids\)/);
  assert.match(lib, /new Set\(technology\.gap_item_ids\)/);
});
