import { useState } from 'react';
import { Badge, Button, Form } from 'react-bootstrap';
import Sidebar from './components/Sidebar';
import TechnologyForm from './components/TechnologyForm';
import TechnologyReview from './components/TechnologyReview';
import ApiHealthStatus from './components/ApiHealthStatus';
import GapComparison, { type GapFilter } from './components/GapComparison';
import EvidencePanel from './components/EvidencePanel';
import { Simulation } from './components/FlowViews';
import DiscoverExplorer from './components/DiscoverExplorer';
import { SessionWorkspace, SessionSimulation } from './components/SessionViews';
import AnalysisReportView from './components/AnalysisReportView';
import { activeRun, cloneInput, confirmProfile, createSession, ensureMockRun, hasUnconfirmedChanges, isHistoricalRun, runProfile, updateRun } from './state/analysisSession';
import { pageFromHash, useNavigation } from './state/useNavigation';
import type { AnalysisRun, AnalysisSession } from './types/analysisSession';
import { mockAnalysis } from './data/mockAnalysis';
import { mockAnalysisReport } from './data/mockAnalysisReport';
import './App.css';

export default function App() {
  const [sessions, setSessions] = useState<AnalysisSession[]>(() => {
    const initial = createSession(mockAnalysis.projects[0].id);
    return [pageFromHash(window.location.hash) === 'home' ? initial : ensureMockRun(initial)];
  });
  const { route, navigate } = useNavigation(sessions[0].id, sessions[0].activeRunId);
  const { page, mode: viewMode } = route;
  const [reviewing, setReviewing] = useState(false);
  const [gapId, setGapId] = useState<string | null>(null);
  const [filter, setFilter] = useState<GapFilter>('all');
  const session = sessions.find(item => item.id === route.sessionId) ?? sessions[0];
  const activeSessionId = session.id;
  const run = session.runs.find(item => item.id === route.runId) ?? activeRun(session);
  const profile = runProfile(session, run);
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
    const next = nextPage === 'home' ? session : ensureMockRun(session);
    if (next !== session) updateSession(() => next);
    setReviewing(false);
    navigate({ ...route, page: nextPage, sessionId: next.id, runId: run?.id ?? next.activeRunId, mode: nextPage === 'home' || nextPage === 'discover' ? 'review' : viewMode });
  };
  const setViewMode = (mode: 'review' | 'demo') => navigate({ ...route, mode });
  const confirmInput = (nextInput: typeof input) => {
    const next = confirmProfile({ ...session, draftInput: cloneInput(nextInput), reviewSource: cloneInput(nextInput) });
    updateSession(() => next);
    setReviewing(false);
    navigate({ page: 'discover', sessionId: next.id, runId: next.activeRunId, mode: 'review' });
  };
  const selectProject = (id: string) => { updateDemo({ projectId: id }); setGapId(null); setFilter('all'); };
  const newSession = () => { const next = createSession(mockAnalysis.projects[0].id); setSessions(current => [...current, next]); setReviewing(false); navigate({ page: 'home', sessionId: next.id, runId: null, mode: 'review' }); };
  const titles: Record<string, [string, string]> = {
    home: ['기술에서 시작하는 새로운 가능성', '보유 기술을 정리하고, 다음 R&D 기회를 검토하세요.'],
    discover: ['R&D 자료 탐색', '외부 기술, 선행 R&D, 공고를 각각 살펴보고 검토할 자료를 선택하세요.'],
    workspace: viewMode === 'demo' ? ['고정 데모 Gap 분석', '현재 사용자 프로필과 무관한 고정 예시 분석입니다.'] : ['선택 자료와 근거 검토', 'Discover에서 선택한 자료의 출처와 인용을 확인하세요.'],
    simulation: viewMode === 'demo' ? ['고정 데모 도입 가정 비교', '사용자 선택 자료와 무관한 별도 고정 사례입니다.'] : ['외부 기술 도입 가정 기록', '선택한 외부 기술의 도입을 가정해 기록합니다. 비교·효과 판정은 제공하지 않습니다.'],
    report: viewMode === 'demo' ? ['고정 데모 보고서', '별도 예시 사례에서 보고서에 포함할 항목을 선택합니다.'] : ['프로필·선택 자료·가정 요약', '현재 실행에 기록된 프로필, 검토 자료와 도입 가정을 모아 봅니다.'],
  };
  return <div className="app-layout">
    <Sidebar activePage={page} onNavigate={setPage} />
    <main className="main-content">
      <header className="topbar"><span>내 워크스페이스 <span className="text-secondary"> / R&D 기회 검토</span></span><div className="d-flex gap-2 align-items-center flex-wrap"><Form.Select size="sm" aria-label="분석 세션 선택" value={activeSessionId} onChange={event => { const next = sessions.find(item => item.id === event.target.value)!; setReviewing(false); navigate({ page: 'home', sessionId: next.id, runId: next.activeRunId, mode: 'review' }); }}>{sessions.map((item, index) => <option key={item.id} value={item.id}>분석 세션 {index + 1}</option>)}</Form.Select><Button size="sm" variant="outline-secondary" onClick={newSession}>새 분석</Button><Badge className="badge-accent">MOCK 데이터</Badge><ApiHealthStatus /></div></header>
      <div className="page-heading"><div className="eyebrow">R&D MATCH / {page.toUpperCase()}</div><h1>{titles[page][0]}</h1><p className="text-secondary">{titles[page][1]}</p></div>
      {page !== 'home' && <div className="mock-banner"><i className="bi bi-info-circle me-2" />현재 브라우저에서만 유지되는 Mock 검토입니다. 실제 분석 API는 연결되지 않았습니다.</div>}
      {page !== 'home' && historical && viewMode === 'review' && <div className="mock-banner">이전 실행의 확정 프로필과 자료를 보고 있습니다. 현재 Home 편집본과 별도로 보존된 이력입니다.</div>}
      {page !== 'home' && profile && !historical && hasUnconfirmedChanges(session) && viewMode === 'review' && <div className="mock-banner" role="alert">현재 Home 편집본이 저장된 프로필과 다릅니다. 기존 실행은 유지됩니다. <Button size="sm" variant="outline-secondary" onClick={() => setPage('home')}>편집본 저장하러 가기</Button></div>}
      {page !== 'home' && (page === 'workspace' || page === 'simulation' || page === 'report') && <div className="d-flex gap-2 mb-3"><Button size="sm" className={viewMode === 'review' ? 'btn-accent' : 'btn-accent-outline'} onClick={() => setViewMode('review')}>현재 검토</Button><Button size="sm" className={viewMode === 'demo' ? 'btn-accent' : 'btn-accent-outline'} onClick={() => setViewMode('demo')}>고정 데모</Button></div>}
      {page === 'home' && <>
        <section className="hero-section home-step"><div className="eyebrow">기술 프로필 · 현재 편집본</div><h2 className="h4 fw-bold mb-2">보유 기술과 해결하려는 문제를 알려주세요</h2>
          <p className="small text-secondary mb-3">원문만으로 프로필을 저장할 수 있습니다. 기술요소 정리는 선택입니다. 아래 탐색은 입력과 무관한 고정 Mock 자료를 보여줍니다.</p>
          <Button variant="outline-secondary" className="mb-3" onClick={() => setPage('discover')}>{profile ? 'Mock 자료 바로 둘러보기' : '프로필 없이 Mock 자료 둘러보기'}</Button>
          <p className="small text-secondary">새로고침하면 이 브라우저의 입력·선택·가정 기록이 초기화됩니다.</p>
          {historical && <p className="mock-banner">Home은 최신 편집본입니다. 이전 실행의 원문은 Discover 실행 이력에서 확인할 수 있습니다.</p>}
          <div className="hero-form"><TechnologyForm key={session.id} value={input} onChange={setInput} onReview={confirmInput} disabled={reviewing} /></div>
          {!reviewing ? <Button variant="outline-secondary" className="mt-3" onClick={() => setReviewing(true)}>기술요소 직접 정리 · 선택 ({elements.length}개)</Button> : <TechnologyReview key={session.id} input={input} elements={elements} onElementsChange={setElements} onDone={() => setReviewing(false)} />}
        </section>
        <div className="workflow-grid">{[['search', '자료를 탐색하세요', '외부 기술·선행 R&D·공고 예시를 살펴봅니다.'], ['intersect', '근거를 검토하세요', '선택한 자료의 출처와 인용을 확인합니다.'], ['file-earmark-text', '검토 내용을 모으세요', '프로필·선택 자료·도입 가정을 요약합니다.']].map(([icon, title, description], i) => <div className="feature-card" key={title}><span className="step-number">0{i + 2}</span><i className={`bi bi-${icon} fs-4`} /><h3 className="h6 mt-3">{title}</h3><p className="small text-secondary mb-0">{description}</p></div>)}</div>
      </>}
      {page === 'discover' && run && <><div className="d-flex gap-2 align-items-center mb-3"><Form.Select aria-label="분석 실행 선택" value={run.id} onChange={event => { updateSession(current => ({ ...current, activeRunId: event.target.value })); navigate({ ...route, runId: event.target.value }); }}>{session.runs.map((item, index) => <option key={item.id} value={item.id}>실행 {index + 1} · {item.profileVersion === null ? '프로필 없는 Mock 탐색' : `프로필 v${item.profileVersion}`}</option>)}</Form.Select></div><DiscoverExplorer key={run.id} profile={profile} historical={historical} run={run} onRunChange={updateCurrentRun} onHome={() => setPage('home')} onWorkspace={() => setPage('workspace')} /></>}
      {page === 'workspace' && viewMode === 'review' && run && <SessionWorkspace profile={profile} run={run} onFocus={key => updateCurrentRun(current => ({ ...current, reviewFocusKey: key }))} onDiscover={() => setPage('discover')} onSimulation={() => setPage('simulation')} onReport={() => setPage('report')} />}
      {page === 'workspace' && viewMode === 'demo' && <>
        <div className="section-toolbar"><Form.Group controlId="workspace-project"><Form.Label className="small text-secondary">고정 데모 분석 대상 과제</Form.Label><Form.Select value={projectId} onChange={e => selectProject(e.target.value)}>{mockAnalysis.projects.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</Form.Select></Form.Group><Button className="btn-accent" onClick={() => setPage('simulation')}>보완 시나리오 구성 <i className="bi bi-arrow-right ms-2" /></Button></div>
        <div className="app-card p-3 mb-3"><strong className="small">보고서용 데모 과제 비교 · {compared.length}/3</strong><div className="d-flex flex-wrap gap-3 mt-2">{mockAnalysis.projects.map(item => <Form.Check key={item.id} id={`compare-${item.id}`} label={item.title} checked={compared.includes(item.id)} disabled={!compared.includes(item.id) && compared.length >= 3} onChange={() => updateDemo({ compared: compared.includes(item.id) ? compared.filter(id => id !== item.id) : [...compared, item.id] })} />)}</div></div>
        <div className="summary-strip">{(['covered', 'partial', 'gap', 'unknown'] as const).map((s, i) => <div key={s}><span>{['충족', '부분 충족', '미충족', '판단 보류'][i]}</span><strong>{project.gaps.filter(g => g.status === s).length}<small> 항목</small></strong></div>)}</div>
        <div className="analysis-columns"><div><h2 className="h6 mb-3">기술 Gap · 데모 보유 역량 기준</h2><GapComparison gaps={project.gaps} selectedId={gapId} filter={filter} onFilterChange={setFilter} onSelect={setGapId} /></div><div aria-live="polite"><h2 className="h6 mb-3">Evidence · 연결된 근거</h2><EvidencePanel gap={gap} evidences={gap ? mockAnalysis.evidences.filter(e => gap.evidenceIds.includes(e.id)) : []} /></div></div>
      </>}
      {page === 'simulation' && viewMode === 'review' && run && <SessionSimulation profile={profile} run={run} onAssumedChange={keys => updateCurrentRun(current => ({ ...current, assumedKeys: keys }))} onReport={() => setPage('report')} onDiscover={() => setPage('discover')} />}
      {page === 'simulation' && viewMode === 'demo' && <Simulation project={project} projects={mockAnalysis.projects} assumed={assumed} onAssume={keys => updateDemo({ assumed: keys })} onProject={selectProject} onReport={() => setPage('report')} />}
      {page === 'report' && <AnalysisReportView report={mockAnalysisReport} />}
      <footer className="app-footer">R&D Match <span>근거를 확인하고, 가능성을 검토하세요.</span></footer>
    </main>
  </div>;
}

