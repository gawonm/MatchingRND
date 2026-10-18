import { useRef, useState } from 'react';
import { Badge, Button, Form } from 'react-bootstrap';
import Sidebar from './components/Sidebar';
import WorkspaceWizard from './components/WorkspaceWizard';
import ApiHealthStatus from './components/ApiHealthStatus';
import GapComparison, { type GapFilter } from './components/GapComparison';
import EvidencePanel from './components/EvidencePanel';
import { Simulation } from './components/FlowViews';
import DiscoverExplorer from './components/DiscoverExplorer';
import { SessionWorkspace, SessionSimulation } from './components/SessionViews';
import { activeRun, approvalBlocker, approvedProfile, cloneInput, confirmProfile, createSession, ensureDiscoverRun, hasUnconfirmedChanges, isHistoricalRun, runProfile, stageWorkspaceReferences, switchDiscoverMode, updateRun } from './state/analysisSession';
import { pageFromHash, useNavigation } from './state/useNavigation';
import { finishReport, startReport, type ReportEntries } from './state/analysisReports';
import type { AnalysisRun, AnalysisSession } from './types/analysisSession';
import { mockAnalysis } from './data/mockAnalysis';
import { createAnalysisReportView } from './api';
import './App.css';

export default function App() {
  const [sessions, setSessions] = useState<AnalysisSession[]>(() => {
    const initial = createSession(mockAnalysis.projects[0].id);
    return [['home', 'workspace'].includes(pageFromHash(window.location.hash)) ? initial : ensureDiscoverRun(initial)];
  });
  const { route, navigate } = useNavigation(sessions[0].id, sessions[0].activeRunId);
  const { page, mode: viewMode } = route;
  const [gapId, setGapId] = useState<string | null>(null);
  const [filter, setFilter] = useState<GapFilter>('all');
  const [reports, setReports] = useState<ReportEntries>({});
  const reportRequestId = useRef(0);
  const reportsInFlight = useRef(new Set<string>());
  const session = sessions.find(item => item.id === route.sessionId) ?? sessions[0];
  const activeSessionId = session.id;
  const run = session.runs.find(item => item.id === route.runId) ?? activeRun(session);
  const profile = runProfile(session, run);
  // 실제 RAG 실행은 현재 편집본과 일치하는 승인 프로필에만 연결된다.
  const approved = approvedProfile(session);
  const reportKey = approved ? `${approved.id}:${approved.version}` : null;
  const workspaceReport = { status: reportKey ? reports[reportKey]?.status ?? 'idle' : 'idle', result: reportKey ? reports[reportKey]?.result ?? null : null } as const;
  const historical = isHistoricalRun(session, run);
  const { draftInput: input, draftElements: elements } = session;
  const { projectId, compared, assumed } = session.demo;
  const project = mockAnalysis.projects.find(p => p.id === projectId)!;
  const gap = project.gaps.find(g => g.id === gapId) ?? null;
  const updateSession = (change: (current: AnalysisSession) => AnalysisSession) => setSessions(current => current.map(item => item.id === activeSessionId ? change(item) : item));
  const updateCurrentRun = (change: (current: AnalysisRun) => AnalysisRun) => {
    if (run) updateSession(current => updateRun(current, run.id, change));
  };
  const setInput = (value: typeof input) => updateSession(current => ({ ...current, draftInput: cloneInput(value) }));
  const setElements = (value: typeof elements) => updateSession(current => ({ ...current, draftElements: value }));
  const updateDemo = (change: Partial<AnalysisSession['demo']>) => updateSession(current => ({ ...current, demo: { ...current.demo, ...change } }));
  const setPage = (nextPage: string) => {
    const next = nextPage === 'home' || nextPage === 'workspace' ? session : ensureDiscoverRun(session);
    if (next !== session) updateSession(() => next);
    navigate({ ...route, page: nextPage, sessionId: next.id, runId: run?.id ?? next.activeRunId, mode: nextPage === 'selection' || nextPage === 'simulation' ? viewMode : 'review' });
  };
  const openWorkspaceWithSelection = () => {
    updateSession(current => stageWorkspaceReferences(current, run));
    setPage('workspace');
  };
  const changeDiscoverMode = (mode: 'mock' | 'real') => {
    const next = switchDiscoverMode(session, mode);
    updateSession(() => next);
    navigate({ ...route, runId: next.activeRunId });
  };
  const setViewMode = (mode: 'review' | 'demo') => navigate({ ...route, mode });
  const approve = () => {
    if (approvalBlocker(elements)) return;
    updateSession(current => confirmProfile({ ...current, reviewSource: cloneInput(current.draftInput) }));
  };
  const selectProject = (id: string) => { updateDemo({ projectId: id }); setGapId(null); setFilter('all'); };
  const newSession = () => { const next = createSession(mockAnalysis.projects[0].id); setSessions(current => [...current, next]); navigate({ page: 'workspace', sessionId: next.id, runId: null, mode: 'review' }); };
  const requestReport = async () => {
    if (!approved || !reportKey || reportsInFlight.current.has(reportKey)) return;
    const requestId = ++reportRequestId.current;
    reportsInFlight.current.add(reportKey);
    setReports(current => startReport(current, reportKey, requestId));
    try {
      const result = await createAnalysisReportView({
        problem: approved.input.target_problem,
        owned_technologies: approved.elements.filter(element => element.role === 'owned').map(element => element.name),
        unmet_elements: approved.elements.filter(element => element.role === 'goal').map(element => element.name),
      });
      setReports(current => finishReport(current, reportKey, requestId, result));
    } catch {
      setReports(current => finishReport(current, reportKey, requestId, null));
    } finally {
      reportsInFlight.current.delete(reportKey);
    }
  };
  const titles: Record<string, [string, string]> = {
    home: ['기술에서 시작하는 새로운 가능성', '보유 기술을 기준으로 나눔기술·국가 R&D 기회를 근거와 함께 분석합니다.'],
    discover: ['R&D 자료 탐색', '외부 기술, 선행 R&D, 공고를 각각 살펴보고 검토할 자료를 선택하세요.'],
    workspace: ['기술 분석 Workspace', '기술 입력 → 기술요소 검토·승인 → 통합 RAG 분석 → 결과 검토'],
    selection: viewMode === 'demo' ? ['고정 데모 Gap 분석', '현재 사용자 프로필과 무관한 고정 예시 분석입니다.'] : ['Discover 선택 자료 검토', 'Discover에서 선택한 자료의 출처와 인용을 확인하세요.'],
    simulation: viewMode === 'demo' ? ['고정 데모 도입 가정 비교', '사용자 선택 자료와 무관한 별도 고정 사례입니다.'] : ['외부 기술 도입 가정 기록', '선택한 외부 기술의 도입을 가정해 기록합니다. 비교·효과 판정은 제공하지 않습니다.'],
  };
  const reviewPage = page === 'discover' || page === 'selection' || page === 'simulation';
  const demoPage = reviewPage && (viewMode === 'demo' || run?.mode === 'mock');
  return <div className="app-layout">
    <Sidebar activePage={page} onNavigate={setPage} />
    <main className="main-content">
      <header className="topbar"><span>내 워크스페이스 <span className="text-secondary"> / R&D 기회 검토</span></span><div className="d-flex gap-2 align-items-center flex-wrap"><Form.Select size="sm" aria-label="분석 세션 선택" value={activeSessionId} onChange={event => { const next = sessions.find(item => item.id === event.target.value)!; navigate({ page: 'workspace', sessionId: next.id, runId: next.activeRunId, mode: 'review' }); }}>{sessions.map((item, index) => <option key={item.id} value={item.id}>분석 세션 {index + 1}</option>)}</Form.Select><Button size="sm" variant="outline-secondary" onClick={newSession}>새 분석</Button><Badge className="badge-accent">{page === 'workspace' ? '실제 RAG' : demoPage ? 'DEMO 데이터' : '실제 검색'}</Badge><ApiHealthStatus /></div></header>
      <div className="page-heading"><div className="eyebrow">R&D MATCH / {page.toUpperCase()}</div><h1>{titles[page][0]}</h1><p className="text-secondary">{titles[page][1]}</p></div>
      {demoPage && <div className="mock-banner"><i className="bi bi-info-circle me-2" />명시적인 Demo 모드의 고정 자료입니다. 실제 검색 결과와 혼합되지 않습니다.</div>}
      {reviewPage && historical && viewMode === 'review' && <div className="mock-banner">이전 실행의 확정 프로필과 자료를 보고 있습니다. 현재 Workspace 편집본과 별도로 보존된 이력입니다.</div>}
      {reviewPage && profile && !historical && hasUnconfirmedChanges(session) && viewMode === 'review' && <div className="mock-banner" role="alert">현재 Workspace 편집본이 승인된 프로필과 다릅니다. 기존 실행은 유지됩니다. <Button size="sm" variant="outline-secondary" onClick={() => setPage('workspace')}>Workspace에서 승인하기</Button></div>}
      {(page === 'selection' || page === 'simulation') && <div className="d-flex gap-2 mb-3"><Button size="sm" className={viewMode === 'review' ? 'btn-accent' : 'btn-accent-outline'} onClick={() => setViewMode('review')}>현재 검토</Button><Button size="sm" className={viewMode === 'demo' ? 'btn-accent' : 'btn-accent-outline'} onClick={() => setViewMode('demo')}>고정 데모</Button></div>}
      {page === 'home' && <>
        <section className="hero-section home-step"><div className="eyebrow">새 기술 분석</div><h2 className="h4 fw-bold mb-2">보유 기술에서 다음 R&D 기회를 찾으세요</h2>
          <p className="small text-secondary mb-3">Workspace에서 기술을 입력하고 AI가 추출한 기술요소를 검토·승인하면, 나눔기술·NTIS·RFP 근거 기반 보고서를 생성합니다.</p>
          <div className="d-flex gap-2 flex-wrap"><Button className="btn-accent" onClick={() => setPage('workspace')}>{approved && workspaceReport.result ? '분석 결과 이어보기' : input.technology_description || elements.length ? '작업 이어하기' : '새 기술 분석 시작'}</Button>
            <Button variant="outline-secondary" onClick={() => setPage('discover')}>자료 검색하기</Button></div>
          <p className="small text-secondary mt-3 mb-0">새로고침하면 이 브라우저의 입력·승인·결과가 초기화됩니다.</p>
        </section>
        <div className="workflow-grid">{[['pencil-square', '기술 입력', '보유 기술 A, 필요 기술 B, 해결 문제를 입력합니다.'], ['check2-square', '기술요소 검토·승인', 'AI 추출 후보를 수정하고 직접 승인합니다.'], ['file-earmark-text', '근거 기반 결과', '추천 기술·RFP·Gap과 원문 근거를 확인합니다.']].map(([icon, title, description], i) => <div className="feature-card" key={title}><span className="step-number">0{i + 1}</span><i className={`bi bi-${icon} fs-4`} /><h3 className="h6 mt-3">{title}</h3><p className="small text-secondary mb-0">{description}</p></div>)}</div>
      </>}
      {page === 'workspace' && <WorkspaceWizard key={session.id} input={input} elements={elements} onInputChange={setInput} onElementsChange={setElements}
        references={session.workspaceReferences ?? []} profiles={session.profiles} runs={session.runs}
        approvedVersion={approved?.version ?? null} onApprove={approve} report={workspaceReport} onRun={requestReport} />}
      {page === 'discover' && run && <><div className="d-flex gap-2 align-items-center mb-3"><Form.Select aria-label="분석 실행 선택" value={run.id} onChange={event => { updateSession(current => ({ ...current, activeRunId: event.target.value })); navigate({ ...route, runId: event.target.value }); }}>{session.runs.map((item, index) => <option key={item.id} value={item.id}>실행 {index + 1} · {item.mode === 'mock' ? 'Demo 탐색' : item.profileVersion === null ? '실제 자료 탐색' : `프로필 v${item.profileVersion}`}</option>)}</Form.Select><Button size="sm" variant="outline-secondary" onClick={() => changeDiscoverMode(run.mode === 'real' ? 'mock' : 'real')}>{run.mode === 'real' ? 'Demo 보기' : '실제 자료 검색'}</Button></div><DiscoverExplorer key={run.id} profile={profile} historical={historical} run={run} onRunChange={updateCurrentRun} onHome={() => setPage('workspace')} onWorkspace={() => setPage('selection')} /></>}
      {page === 'selection' && viewMode === 'review' && run && <SessionWorkspace profile={profile} run={run} onFocus={key => updateCurrentRun(current => ({ ...current, reviewFocusKey: key }))} onDiscover={() => setPage('discover')} onSimulation={() => setPage('simulation')} onReport={openWorkspaceWithSelection} />}
      {page === 'selection' && viewMode === 'demo' && <>
        <div className="section-toolbar"><Form.Group controlId="workspace-project"><Form.Label className="small text-secondary">고정 데모 분석 대상 과제</Form.Label><Form.Select value={projectId} onChange={e => selectProject(e.target.value)}>{mockAnalysis.projects.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</Form.Select></Form.Group><Button className="btn-accent" onClick={() => setPage('simulation')}>보완 시나리오 구성 <i className="bi bi-arrow-right ms-2" /></Button></div>
        <div className="app-card p-3 mb-3"><strong className="small">보고서용 데모 과제 비교 · {compared.length}/3</strong><div className="d-flex flex-wrap gap-3 mt-2">{mockAnalysis.projects.map(item => <Form.Check key={item.id} id={`compare-${item.id}`} label={item.title} checked={compared.includes(item.id)} disabled={!compared.includes(item.id) && compared.length >= 3} onChange={() => updateDemo({ compared: compared.includes(item.id) ? compared.filter(id => id !== item.id) : [...compared, item.id] })} />)}</div></div>
        <div className="summary-strip">{(['covered', 'partial', 'gap', 'unknown'] as const).map((s, i) => <div key={s}><span>{['충족', '부분 충족', '미충족', '판단 보류'][i]}</span><strong>{project.gaps.filter(g => g.status === s).length}<small> 항목</small></strong></div>)}</div>
        <div className="analysis-columns"><div><h2 className="h6 mb-3">기술 Gap · 데모 보유 역량 기준</h2><GapComparison gaps={project.gaps} selectedId={gapId} filter={filter} onFilterChange={setFilter} onSelect={setGapId} /></div><div aria-live="polite"><h2 className="h6 mb-3">Evidence · 연결된 근거</h2><EvidencePanel gap={gap} evidences={gap ? mockAnalysis.evidences.filter(e => gap.evidenceIds.includes(e.id)) : []} /></div></div>
      </>}
      {page === 'simulation' && viewMode === 'review' && run && <SessionSimulation profile={profile} run={run} onAssumedChange={keys => updateCurrentRun(current => ({ ...current, assumedKeys: keys }))} onReport={openWorkspaceWithSelection} onDiscover={() => setPage('discover')} />}
      {page === 'simulation' && viewMode === 'demo' && <Simulation project={project} projects={mockAnalysis.projects} assumed={assumed} onAssume={keys => updateDemo({ assumed: keys })} onProject={selectProject} onReport={() => setPage('workspace')} />}
      <footer className="app-footer">R&D Match <span>근거를 확인하고, 가능성을 검토하세요.</span></footer>
    </main>
  </div>;
}

