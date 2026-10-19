import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { activeRun, approvalBlocker, approvedProfile, confirmProfile, createSession, ensureDiscoverRun, ensureMockRun, hasUnconfirmedChanges, isHistoricalRun, runProfile, selectedItems, stageWorkspaceReferences, switchDiscoverMode, toggleSelection, updateRun } from '../src/state/analysisSession.ts';
import { isNavigation, pageFromHash } from '../src/state/useNavigation.ts';

const input = { technology_domains: [], technology_tags: [], technology_description: '진동 센서 분석', target_problem: '모터 고장 예측' };
const item = { key: 'mock:technology:candidate', mode: 'mock', source: 'technology', title: '예시 후보', evidence: [] };

test('프로필 없는 탐색은 가짜 프로필 없이 독립된 Mock 실행을 만들고 재진입 시 유지한다', () => {
  const session = ensureMockRun(createSession('p1', 's1'), 'browse');
  const run = activeRun(session);
  assert.equal(run.mode, 'mock');
  assert.equal(run.id, 'browse');
  assert.equal(run.profileId, null);
  assert.equal(run.profileVersion, null);
  assert.equal(runProfile(session, run), null);
  assert.deepEqual(session.profiles, []);
  assert.equal(ensureMockRun(session, 'unused'), session);
  const confirmed = confirmProfile({ ...session, draftInput: input }, 'profile-run', 'profile');
  assert.equal(confirmed.runs.length, 2);
  assert.equal(confirmed.runs[0].profileId, null);
  assert.equal(confirmed.profiles[0].elements.length, 0);
  assert.equal(activeRun(confirmed).profileVersion, 1);
  assert.equal(activeRun(confirmed).mode, 'real');
});

test('프로필 없는 Discover는 Real 검색으로 시작하고 Demo는 명시적으로 전환한다', () => {
  const real = ensureDiscoverRun(createSession('p1', 's1'), 'real-run');
  assert.equal(activeRun(real).mode, 'real');
  const demo = switchDiscoverMode(real, 'mock', 'demo-run');
  assert.equal(activeRun(demo).mode, 'mock');
  assert.equal(switchDiscoverMode(demo, 'real').activeRunId, 'real-run');
  assert.equal(real.draftInput.technology_description, '');
});

test('Discover 선택 검토 후 Workspace에는 Real 참고 스냅샷만 전달한다', () => {
  const rfp = {
    key: 'real:rfp:pdf-1:task-1', mode: 'real', source: 'rfp', title: '제설 과제',
    originalId: 'pdf-1', taskId: 'task-1',
    evidence: [{ id: 'chunk-1', source: 'rfp', documentTitle: '제설 과제', quote: '원문 요구',
      section: '개발내용', page: 0, sourcePath: 'C:\\private\\rfp.pdf' }],
  };
  const technology = {
    key: 'real:technology:tech-1', mode: 'real', source: 'technology', title: '외부 제설 기술',
    originalId: 'tech-1', evidence: [{ id: 'chunk-2', source: 'technology', documentTitle: '외부 제설 기술', quote: '기술 원문' }],
  };
  const base = ensureDiscoverRun(createSession('p1', 's1'), 'real-run');
  const chosen = updateRun(base, 'real-run', run => ({ ...run, items: [rfp, technology], selectedKeys: [rfp.key, technology.key] }));
  const transferred = stageWorkspaceReferences(chosen, activeRun(chosen));
  assert.deepEqual(transferred.workspaceReferences.map(item => [item.source, item.originalId, item.taskId, item.evidence[0].quote]), [
    ['rfp', 'pdf-1', 'task-1', '원문 요구'], ['technology', 'tech-1', undefined, '기술 원문'],
  ]);
  assert.deepEqual(transferred.draftInput, base.draftInput);
  assert.deepEqual(transferred.draftElements, []);
  const deselected = updateRun(transferred, 'real-run', run => toggleSelection(run, rfp.key));
  assert.equal(deselected.workspaceReferences.length, 2);
  assert.equal(selectedItems(activeRun(deselected)).length, 1);
  assert.deepEqual(stageWorkspaceReferences(deselected, activeRun(deselected)).workspaceReferences.map(item => item.key), [technology.key]);

  const demo = switchDiscoverMode(chosen, 'mock', 'demo-run');
  const demoItem = { ...item, key: 'mock:technology:sample' };
  const demoSelected = updateRun(demo, 'demo-run', run => ({ ...run, items: [demoItem], selectedKeys: [demoItem.key] }));
  assert.deepEqual(stageWorkspaceReferences(demoSelected, activeRun(demoSelected)).workspaceReferences, []);
});

test('참고 자료 전달은 입력과 기존 보고서를 바꾸지 않고, 사용자가 A/B/문제를 직접 고친 뒤 승인한다', () => {
  const item = { key: 'real:rfp:pdf-1:task-1', mode: 'real', source: 'rfp', title: '제설 RFP', originalId: 'pdf-1', taskId: 'task-1', evidence: [] };
  const initial = ensureDiscoverRun(createSession('p1', 's1'), 'real-run');
  const selected = updateRun(initial, 'real-run', run => ({ ...run, items: [item], selectedKeys: [item.key] }));
  const report = { report: { markdown: '이미 완료된 분석' } };
  const staged = stageWorkspaceReferences(selected, activeRun(selected));
  assert.equal(staged.draftInput.technology_description, '');
  assert.equal(approvedProfile(staged), null);
  assert.equal(report.report.markdown, '이미 완료된 분석');
  const edited = { ...staged, draftInput: { ...staged.draftInput, technology_description: '내 센서 기술', required_technology: '제설 제어 기술', target_problem: '결빙 구간 감지' } };
  const owned = { id: 'owned', name: '센서 기술', role: 'owned', category: '미분류', evidence: '내 센서 기술', source: '사용자 입력' };
  assert.equal(approvalBlocker([]), null);
  const approved = confirmProfile({ ...edited, draftElements: [owned] }, 'next-run', 'profile');
  assert.equal(approvedProfile(approved).input.required_technology, '제설 제어 기술');
  assert.equal(approvedProfile(approved).input.target_problem, '결빙 구간 감지');
  assert.equal(approved.workspaceReferences[0].taskId, 'task-1');
  assert.equal(report.report.markdown, '이미 완료된 분석');
});

test('선택 검토에서만 참고 자료를 전달하고 Wizard는 로컬 경로를 출력하지 않는다', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');
  const review = readFileSync(new URL('../src/components/SessionViews.tsx', import.meta.url), 'utf8');
  assert.match(app, /onReport=\{openWorkspaceWithSelection\}/);
  assert.match(app, /references=\{session\.workspaceReferences/);
  assert.match(review, /선택 자료를 참고해 Workspace 입력/);
  assert.match(wizard, /ReferenceMaterials items=\{references\.filter\(item => item\.mode === 'real'\)\}/);
  assert.match(wizard, /<TechnologyForm value=\{input\}/);
  assert.doesNotMatch(wizard, /sourcePath/);
});

test('최신 편집본 변경과 과거 실행 조회를 독립적으로 판정한다', () => {
  const first = confirmProfile({ ...createSession('p1', 's1'), draftInput: input }, 'r1', 'p1');
  const pending = { ...first, draftInput: { ...input, target_problem: '펌프 고장 예측' } };
  assert.equal(hasUnconfirmedChanges(pending), true);
  const second = confirmProfile(pending, 'r2', 'p2');
  const history = { ...second, activeRunId: 'r1' };
  assert.equal(isHistoricalRun(history, activeRun(history)), true);
  assert.equal(hasUnconfirmedChanges(history), false);
  assert.equal(runProfile(history, activeRun(history)).input.target_problem, input.target_problem);
  assert.equal(confirmProfile(history, 'unused', 'unused').activeRunId, 'r2');
  assert.equal(second.runs.length, 2);
});

test('검색 출처와 선택은 실행에 저장되어 화면 이동 후 같은 상태로 읽힌다', () => {
  let session = ensureMockRun(createSession('p1', 's1'), 'browse');
  session = updateRun(session, 'browse', run => ({ ...run, activeSource: 'ntis', items: [item] }));
  session = updateRun(session, 'browse', run => toggleSelection(run, item.key));
  assert.equal(activeRun(session).activeSource, 'ntis');
  assert.deepEqual(selectedItems(activeRun(session)), [item]);
  const confirmed = confirmProfile({ ...session, draftInput: input }, 'r2', 'p2');
  assert.equal(confirmed.runs[0].activeSource, 'ntis');
  assert.deepEqual(selectedItems(confirmed.runs[0]), [item]);
  assert.deepEqual(selectedItems(activeRun(confirmed)), []);
});

test('존재하지 않거나 다른 모드의 자료는 선택에 추가되지 않는다', () => {
  const run = activeRun(ensureMockRun(createSession('p1', 's1'), 'browse'));
  assert.equal(toggleSelection(run, 'missing'), run);
  const mixed = { ...run, items: [{ ...item, mode: 'real' }] };
  assert.equal(toggleSelection(mixed, item.key), mixed);
  assert.deepEqual(selectedItems(run), []);
});

test('선택 해제는 가정·근거 초점도 제거하고 재선택은 가정을 되살리지 않는다', () => {
  const run = { ...activeRun(ensureMockRun(createSession('p1', 's1'), 'browse')), items: [item], selectedKeys: [item.key], assumedKeys: [item.key], reviewFocusKey: item.key };
  const removed = toggleSelection(run, item.key);
  assert.deepEqual(removed.selectedKeys, []);
  assert.deepEqual(removed.assumedKeys, []);
  assert.equal(removed.reviewFocusKey, null);
  const reselected = toggleSelection(removed, item.key);
  assert.deepEqual(reselected.selectedKeys, [item.key]);
  assert.deepEqual(reselected.assumedKeys, []);
  assert.deepEqual(run.assumedKeys, [item.key]);
});

test('브라우저 이동 이력은 페이지·세션·실행·데모 모드를 함께 식별한다', () => {
  assert.equal(pageFromHash('#discover'), 'discover');
  assert.equal(pageFromHash('#unknown'), 'home');
  assert.equal(isNavigation({ page: 'workspace', sessionId: 's1', runId: 'r1', mode: 'demo' }), true);
  assert.equal(isNavigation({ page: 'discover', sessionId: 's1', runId: null, mode: 'review' }), true);
  assert.equal(isNavigation({ page: 'workspace', sessionId: 's1', runId: 'r1', mode: 'real' }), false);
  assert.equal(isNavigation({ page: 'unknown', sessionId: 's1', runId: 'r1', mode: 'review' }), false);
  assert.equal(pageFromHash('#report'), 'home');
  assert.equal(pageFromHash('#selection'), 'selection');
});

test('Workspace 승인 게이트: 빈 A를 보존하고 역할 미정은 막으며 수정하면 승인이 해제된다', () => {
  const owned = { id: 'a', name: '진동 분석', category: '미분류', role: 'owned', evidence: '진동 분석', source: 'AI 추출' };
  const goal = { id: 'b', name: '잔존수명 예측', category: '미분류', role: 'goal', evidence: '잔존수명 예측', source: 'AI 추출' };
  assert.equal(approvalBlocker([goal]), null);
  assert.match(approvalBlocker([owned, { ...goal, role: 'uncertain' }]), /구분 확인/);
  assert.equal(approvalBlocker([owned, goal]), null);

  const draft = { ...createSession('p1', 's1'), draftInput: input, draftElements: [owned, goal] };
  assert.equal(approvedProfile(draft), null);
  const approved = confirmProfile(draft, 'r1', 'v1');
  assert.equal(approvedProfile(approved).version, 1);
  const edited = { ...approved, draftElements: [owned, { ...goal, name: '파단 예측' }] };
  assert.equal(approvedProfile(edited), null);
  const reapproved = confirmProfile(edited, 'r2', 'v2');
  assert.equal(approvedProfile(reapproved).version, 2);
  assert.equal(approvedProfile({ ...reapproved, draftInput: { ...input, required_technology: '변경' } }), null);
});

test('Workspace 승인 이력은 profiles와 runs를 읽기 전용 스냅샷 조회에 사용한다', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');
  const history = wizard.slice(wizard.indexOf('function ApprovalHistory'), wizard.indexOf('export default function WorkspaceWizard'));
  assert.match(app, /profiles=\{session\.profiles\} runs=\{session\.runs\}/);
  assert.match(history, /aria-label="승인 버전 선택"/);
  assert.match(history, /<details className="app-card approval-history/);
  assert.match(history, /현재 편집본에는 영향 없음/);
  assert.match(history, /selected\.input\.technology_description/);
  assert.match(history, /selected\.elements\.map/);
  assert.match(history, /run\.profileId === selected\.id && run\.profileVersion === selected\.version/);
  assert.match(history, /현재 편집본·승인 상태·분석 실행은 바뀌지 않습니다/);
  assert.doesNotMatch(history, /onInputChange|onElementsChange|onApprove|onRun/);
});

test('Workspace는 기술 입력, 분석 준비, 결과 확인 흐름과 분리된 실행 게이트를 안내한다', () => {
  const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');
  const review = readFileSync(new URL('../src/components/TechnologyReview.tsx', import.meta.url), 'utf8');
  assert.match(wizard, /const steps = \['기술 입력', '분석 준비', '결과 확인'\]/);
  assert.match(review, /내가 가진 기술/);
  assert.match(review, /추가로 필요한 기술/);
  assert.match(review, /<summary>세부 정보<\/summary>/);
  assert.doesNotMatch(review, /\{element\.category\} · \{element\.source\}<\/span>/);
  assert.match(wizard, /이 내용으로 분석 준비 완료/);
  assert.match(wizard, /내용을 확정하는 것만으로는 분석 API를 호출하지 않습니다/);
  assert.match(wizard, /disabled=\{!approved\} onClick=\{run\}>실제 RAG 분석 시작/);
});

test('Workspace MVP는 특허번호를 새로 입력받지 않지만 기존 승인 스냅샷은 보존한다', () => {
  const form = readFileSync(new URL('../src/components/TechnologyForm.tsx', import.meta.url), 'utf8');
  const wizard = readFileSync(new URL('../src/components/WorkspaceWizard.tsx', import.meta.url), 'utf8');
  const session = readFileSync(new URL('../src/state/analysisSession.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(form, /보유 특허정보|특허번호 입력|patentDraft|patent-number|patent_numbers/);
  assert.match(wizard, /selected\.input\.patent_numbers/);
  assert.match(session, /patent_numbers: \[\.\.\.\(value\.patent_numbers \?\? \[\]\)\]/);
});
