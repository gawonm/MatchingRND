import { useState } from 'react';
import { Badge, Button, Form } from 'react-bootstrap';
import Sidebar from './components/Sidebar';
import TechnologyForm from './components/TechnologyForm';
import TechnologyReview from './components/TechnologyReview';
import GapComparison, { type GapFilter } from './components/GapComparison';
import EvidencePanel from './components/EvidencePanel';
import { Simulation, Report } from './components/FlowViews';
import DiscoverExplorer from './components/DiscoverExplorer';
import { SessionWorkspace, SessionSimulation, SessionReport } from './components/SessionViews';
import { activeRun, cloneInput, confirmProfile, createSession, draftDiffers, runProfile, updateRun } from './state/analysisSession';
import type { AnalysisRun, AnalysisSession } from './types/analysisSession';
import { mockAnalysis } from './data/mockAnalysis';
import './App.css';

const demoInput = {
  technology_domains: [], technology_tags: [],
  technology_description: mockAnalysis.evidences.find(item => item.id === 'e-user-owned')!.quote,
  target_problem: mockAnalysis.evidences.find(item => item.id === 'e-user-problem')!.quote,
};

export default function App() {
  const [page, setPage] = useState('home');
  const [sessions, setSessions] = useState<AnalysisSession[]>(() => [createSession(mockAnalysis.projects[0].id)]);
  const [activeSessionId, setActiveSessionId] = useState(() => sessions[0].id);
  const [reviewing, setReviewing] = useState(false);
  const [viewMode, setViewMode] = useState<'review' | 'demo'>('review');
  const [gapId, setGapId] = useState<string | null>(null);
  const [filter, setFilter] = useState<GapFilter>('all');
  const session = sessions.find(item => item.id === activeSessionId)!;
  const run = activeRun(session);
  const profile = runProfile(session, run);
  const { draftInput: input, draftElements: elements, reviewSource } = session;
  const { projectId, compared, assumed, included } = session.demo;
  const project = mockAnalysis.projects.find(p => p.id === projectId)!;
  const gap = project.gaps.find(g => g.id === gapId) ?? null;
  const reviewIsStale = !!reviewSource && JSON.stringify(input) !== JSON.stringify(reviewSource);
  const updateSession = (change: (current: AnalysisSession) => AnalysisSession) => setSessions(current => current.map(item => item.id === activeSessionId ? change(item) : item));
  const updateCurrentRun = (change: (current: AnalysisRun) => AnalysisRun) => {
    if (run) updateSession(current => updateRun(current, run.id, change));
  };
  const setInput = (value: typeof input) => updateSession(current => ({ ...current, draftInput: cloneInput(value) }));
  const setElements = (value: typeof elements) => updateSession(current => ({ ...current, draftElements: value }));
  const updateDemo = (change: Partial<AnalysisSession['demo']>) => updateSession(current => ({ ...current, demo: { ...current.demo, ...change } }));
  const reviewInput = (nextInput: typeof input) => {
    const capturedInput = cloneInput(nextInput);
    updateSession(current => ({ ...current, draftInput: capturedInput, reviewSource: current.reviewSource ?? cloneInput(capturedInput) }));
    setReviewing(true);
  };
  const confirmElements = () => {
    if (!reviewIsStale && elements.every(element => element.name.trim())) {
      updateSession(current => confirmProfile(current));
      setViewMode('review');
      setPage('discover');
    }
  };
  const selectProject = (id: string) => { updateDemo({ projectId: id }); setGapId(null); setFilter('all'); };
  const newSession = () => { const next = createSession(mockAnalysis.projects[0].id); setSessions(current => [...current, next]); setActiveSessionId(next.id); setPage('home'); setReviewing(false); setViewMode('review'); };
  const titles: Record<string, [string, string]> = {
    home: ['기술에서 시작하는 새로운 가능성', '보유 기술을 정리하고, 다음 R&D 기회를 검토하세요.'],
    discover: ['R&D 자료 탐색', '외부 기술, 선행 R&D, 공고를 각각 살펴보고 검토할 자료를 선택하세요.'],
    workspace: ['요구 기술과 보유 역량 사이', '기술요소를 선택해 판정 이유와 관련 근거를 확인하세요.'],
    simulation: ['부족한 기술, 다른 가능성으로', '기술 도입을 가정하고 보완 범위와 확인할 조건을 검토하세요.'],
    report: ['검토 내용을 하나의 보고서로', '포함할 항목을 선택하면 미리보기에 즉시 반영됩니다.'],
  };
  return <div className="app-layout">
    <Sidebar activePage={page} onNavigate={setPage} />
    <main className="main-content">
      <header className="topbar"><span>내 워크스페이스 <span className="text-secondary"> / R&D 기회 검토</span></span><div className="d-flex gap-2 align-items-center flex-wrap"><Form.Select size="sm" aria-label="분석 세션 선택" value={activeSessionId} onChange={event => { setActiveSessionId(event.target.value); setPage('home'); setReviewing(false); setViewMode('review'); }}>{sessions.map((item, index) => <option key={item.id} value={item.id}>분석 세션 {index + 1}</option>)}</Form.Select><Button size="sm" variant="outline-secondary" onClick={newSession}>새 분석</Button><Badge className="badge-accent">MOCK</Badge></div></header>
      <div className="page-heading"><div className="eyebrow">R&D MATCH / {page.toUpperCase()}</div><h1>{titles[page][0]}</h1><p className="text-secondary">{titles[page][1]}</p></div>
      {page !== 'home' && <div className="mock-banner"><i className="bi bi-info-circle me-2" />현재 브라우저에서만 유지되는 Mock 검토입니다. 실제 분석 API는 연결되지 않았습니다.</div>}
      {page !== 'home' && run && draftDiffers(session) && viewMode === 'review' && <div className="mock-banner" role="alert">Home의 수정 내용은 현재 분석 실행에 반영되지 않았습니다. 수정한 프로필로 새 실행을 시작하려면 Home에서 다시 확정하세요.</div>}
      {page !== 'home' && (page === 'workspace' || page === 'simulation' || page === 'report') && <div className="d-flex gap-2 mb-3"><Button size="sm" className={viewMode === 'review' ? 'btn-accent' : 'btn-accent-outline'} onClick={() => setViewMode('review')}>현재 검토</Button><Button size="sm" className={viewMode === 'demo' ? 'btn-accent' : 'btn-accent-outline'} onClick={() => setViewMode('demo')}>고정 데모</Button></div>}
      {page === 'home' && <>
        <section className="hero-section home-step"><div className="eyebrow">{reviewing ? 'STEP 02 / 기술정보 검토' : 'STEP 01 / 기술정보 입력'}</div><h2 className="h4 fw-bold mb-2">{reviewing ? '기술정보를 확인해 주세요' : '보유 기술과 해결하려는 문제를 알려주세요'}</h2>
          <p className="small text-secondary mb-4">{reviewing ? '보유 기술과 확보하려는 기술을 확인하고 필요한 내용을 수정해 주세요.' : '현재 보유한 기술과 앞으로 해결하고 싶은 문제를 자유롭게 작성해 주세요.'}</p>
          {!reviewing ? <div className="hero-form"><TechnologyForm value={input} onChange={setInput} onReview={reviewInput} /></div> :
            <TechnologyReview input={input} elements={elements} stale={reviewIsStale}
              onElementsChange={setElements} onBack={() => setReviewing(false)}
              onRestoreInput={() => reviewSource && setInput(cloneInput(reviewSource))}
              onUseCurrentInput={() => updateSession(current => ({ ...current, reviewSource: cloneInput(current.draftInput) }))} onConfirm={confirmElements} />}
        </section>
        <div className="workflow-grid">{[['search', '과제를 발견하세요', '요구 기술을 살펴보고 관심 과제를 비교합니다.'], ['intersect', 'Gap을 이해하세요', '충족·부분 충족·미충족·판단 보류를 구분합니다.'], ['file-earmark-text', '검토를 이어가세요', '도입 가정과 근거를 보고서에 담습니다.']].map(([icon, title, description], i) => <div className="feature-card" key={title}><span className="step-number">0{i + 2}</span><i className={`bi bi-${icon} fs-4`} /><h3 className="h6 mt-3">{title}</h3><p className="small text-secondary mb-0">{description}</p></div>)}</div>
      </>}
      {page === 'discover' && (!run || !profile ? <div className="app-card p-4">Home에서 기술 프로필을 확정해 주세요. <Button variant="outline-secondary" onClick={() => setPage('home')}>Home으로</Button></div> : <><div className="d-flex gap-2 align-items-center mb-3"><Form.Select aria-label="분석 실행 선택" value={run.id} onChange={event => updateSession(current => ({ ...current, activeRunId: event.target.value }))}>{session.runs.map((item, index) => <option key={item.id} value={item.id}>실행 {index + 1} · 프로필 v{item.profileVersion}</option>)}</Form.Select></div><DiscoverExplorer profile={profile} run={run} onRunChange={updateCurrentRun} onHome={() => { setPage('home'); setReviewing(true); }} onWorkspace={() => setPage('workspace')} /></>)}
      {page === 'workspace' && viewMode === 'review' && (run && profile ? <SessionWorkspace profile={profile} run={run} onFocus={key => updateCurrentRun(current => ({ ...current, reviewFocusKey: key }))} onDiscover={() => setPage('discover')} onSimulation={() => setPage('simulation')} /> : <div className="app-card p-4">확정된 프로필이 없습니다. Home에서 확정해 주세요.</div>)}
      {page === 'workspace' && viewMode === 'demo' && <>
        <div className="section-toolbar"><Form.Group controlId="workspace-project"><Form.Label className="small text-secondary">고정 데모 분석 대상 과제</Form.Label><Form.Select value={projectId} onChange={e => selectProject(e.target.value)}>{mockAnalysis.projects.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}</Form.Select></Form.Group><Button className="btn-accent" onClick={() => setPage('simulation')}>보완 시나리오 구성 <i className="bi bi-arrow-right ms-2" /></Button></div>
        <div className="app-card p-3 mb-3"><strong className="small">보고서용 데모 과제 비교 · {compared.length}/3</strong><div className="d-flex flex-wrap gap-3 mt-2">{mockAnalysis.projects.map(item => <Form.Check key={item.id} id={`compare-${item.id}`} label={item.title} checked={compared.includes(item.id)} disabled={!compared.includes(item.id) && compared.length >= 3} onChange={() => updateDemo({ compared: compared.includes(item.id) ? compared.filter(id => id !== item.id) : [...compared, item.id] })} />)}</div></div>
        <div className="summary-strip">{(['covered', 'partial', 'gap', 'unknown'] as const).map((s, i) => <div key={s}><span>{['충족', '부분 충족', '미충족', '판단 보류'][i]}</span><strong>{project.gaps.filter(g => g.status === s).length}<small> 항목</small></strong></div>)}</div>
        <div className="analysis-columns"><div><h2 className="h6 mb-3">기술 Gap · 데모 보유 역량 기준</h2><GapComparison gaps={project.gaps} selectedId={gapId} filter={filter} onFilterChange={setFilter} onSelect={setGapId} /></div><div aria-live="polite"><h2 className="h6 mb-3">Evidence · 연결된 근거</h2><EvidencePanel gap={gap} evidences={gap ? mockAnalysis.evidences.filter(e => gap.evidenceIds.includes(e.id)) : []} /></div></div>
      </>}
      {page === 'simulation' && viewMode === 'review' && (run && profile ? <SessionSimulation profile={profile} run={run} onAssumedChange={keys => updateCurrentRun(current => ({ ...current, assumedKeys: keys }))} onReport={() => setPage('report')} /> : <div className="app-card p-4">확정된 프로필이 없습니다.</div>)}
      {page === 'simulation' && viewMode === 'demo' && <Simulation project={project} projects={mockAnalysis.projects} assumed={assumed} onAssume={keys => updateDemo({ assumed: keys })} onProject={selectProject} onReport={() => setPage('report')} />}
      {page === 'report' && viewMode === 'review' && (run && profile ? <SessionReport profile={profile} run={run} /> : <div className="app-card p-4">확정된 프로필이 없습니다.</div>)}
      {page === 'report' && viewMode === 'demo' && <Report input={demoInput} project={project} compared={mockAnalysis.projects.filter(p => compared.includes(p.id))} assumed={assumed} included={included} onInclude={keys => updateDemo({ included: keys })} />}
      <footer className="app-footer">R&D Match <span>근거를 확인하고, 가능성을 검토하세요.</span></footer>
    </main>
  </div>;
}

