import { useEffect, useState } from 'react';
import { Button, Form, Tab, Tabs } from 'react-bootstrap';
import TechnologyForm from './TechnologyForm';
import TechnologyReview from './TechnologyReview';
import AnalysisReportView, { ReportOverview } from './AnalysisReportView';
import { extractTechnologyElements } from '../api';
import type { ReportEntry } from '../state/analysisReports';
import { approvalBlocker } from '../state/analysisSession';
import EvidenceExplorer from './analysis/EvidenceExplorer';
import RfpExplorer from './analysis/RfpExplorer';
import TechnologyExplorer from './analysis/TechnologyExplorer';
import GapExplorer, { type GapViewState } from './analysis/GapExplorer';
import PrimaryPicks from './analysis/PrimaryPicks';
import type { SplitViewState } from './analysis/SplitExplorer';
import { COMMON_RND_INTRO, COMMON_RND_NOTICE_TITLE, COMMON_RND_NOTICES, viewAvailability } from '../lib/analysisView';
import type { TechnologyElement } from '../types/technologyElement';
import type { TechnologyInput } from '../types/technologyInput';
import type { AnalysisRun, ConfirmedProfile, DiscoverItem } from '../types/analysisSession';
import type { ReportViewResponse } from '../types/analysisReport';

type Props = {
  input: TechnologyInput;
  elements: TechnologyElement[];
  references: DiscoverItem[];
  profiles: ConfirmedProfile[];
  runs: AnalysisRun[];
  onInputChange: (input: TechnologyInput) => void;
  onElementsChange: (elements: TechnologyElement[]) => void;
  approvedVersion: number | null;
  onApprove: () => void;
  report: Pick<ReportEntry, 'status' | 'result'>;
  onRun: () => void;
};

const initialSplitView: SplitViewState = { selectedId: null, mobileDetailOpen: false };
const initialExplore = { technology: initialSplitView, rfp: initialSplitView, gap: { ...initialSplitView, rfpId: null } as GapViewState };
const steps = ['기술 및 문제 입력', '기술요소 검토·승인', '통합 RAG 분석'];
const roleLabels: Record<TechnologyElement['role'], string> = { owned: '보유 기술 A', goal: '필요 기술 B', uncertain: '구분 확인 필요' };

function ReferenceMaterials({ items }: { items: DiscoverItem[] }) {
  if (!items.length) return null;
  const sourceLabel = { technology: '나눔기술', rfp: 'RFP', ntis: 'NTIS' };
  return <section className="app-card p-4 mb-3" aria-labelledby="workspace-reference-title">
    <h2 id="workspace-reference-title" className="h6">Discover 선택 자료 · 참고 {items.length}건</h2>
    <p className="small text-secondary">선택 검토에서 Workspace로 이동할 때의 참고 목록입니다. 선택 자료는 보유기술 A로 자동 분류하거나 분석 검색 결과에 강제 반영하지 않습니다. 아래 입력은 직접 작성·수정해 주세요.</p>
    {items.map(item => <details className="mb-2" key={item.key}>
      <summary>{sourceLabel[item.source]} · {item.title}</summary>
      <div className="small text-secondary mt-2">문서 ID: {item.originalId || '미제공'}{item.source === 'rfp' && <> · task_id: {item.taskId || '미제공'}</>}</div>
      {item.evidence.map(evidence => <blockquote className="evidence-block small mt-2" key={evidence.id}>{evidence.quote}
        <div className="text-secondary mt-2">{evidence.documentTitle}{evidence.section && ` · 섹션: ${evidence.section}`}{evidence.page != null && ` · 저장된 페이지 값: ${evidence.page}${evidence.pageEnd != null && evidence.pageEnd !== evidence.page ? `–${evidence.pageEnd}` : ''}`}</div>
      </blockquote>)}
    </details>)}
  </section>;
}

function ApprovalHistory({ profiles, runs }: { profiles: ConfirmedProfile[]; runs: AnalysisRun[] }) {
  const latestProfileId = profiles.at(-1)?.id ?? '';
  const [selectedProfileId, setSelectedProfileId] = useState(latestProfileId);
  if (!profiles.length) return null;
  const selected = profiles.find(profile => profile.id === selectedProfileId) ?? profiles.at(-1)!;
  const connectedRun = [...runs].reverse().find(run => run.profileId === selected.id && run.profileVersion === selected.version);
  const runNumber = connectedRun ? runs.findIndex(run => run.id === connectedRun.id) + 1 : null;

  return <section className="app-card p-4 mb-3" aria-labelledby="approval-history-title">
    <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
      <div><h2 id="approval-history-title" className="h6 mb-1">승인 이력</h2><p className="small text-secondary mb-0">승인 당시 입력과 기술요소를 읽기 전용으로 조회합니다. 선택해도 현재 편집본·승인 상태·분석 실행은 바뀌지 않습니다.</p></div>
      <Form.Group controlId="approval-history-version">
        <Form.Label className="small text-secondary">승인 버전</Form.Label>
        <Form.Select aria-label="승인 버전 선택" value={selected.id} onChange={event => setSelectedProfileId(event.target.value)}>
          {profiles.map(profile => <option key={profile.id} value={profile.id}>v{profile.version}{profile.id === latestProfileId ? ' · 최신 승인본' : ''}</option>)}
        </Form.Select>
      </Form.Group>
    </div>
    <div className="small text-secondary mt-3">v{selected.version} 승인 스냅샷 · {runNumber ? `연결된 실행 ${runNumber}` : '연결된 실행 없음'}</div>
    <dl className="approval-snapshot-input mt-3 mb-0">
      <div><dt>보유 기술</dt><dd>{selected.input.technology_description}</dd></div>
      <div><dt>필요 기술</dt><dd>{selected.input.required_technology || '입력 없음'}</dd></div>
      <div><dt>해결하려는 기술 문제</dt><dd>{selected.input.target_problem}</dd></div>
      <div><dt>특허번호</dt><dd>{selected.input.patent_numbers?.join(', ') || '없음'}</dd></div>
    </dl>
    <div className="approval-snapshot-elements mt-3">
      <h3 className="h6">기술요소 · {selected.elements.length}개</h3>
      {selected.elements.length === 0 && <p className="small text-secondary mb-0">승인된 기술요소가 없습니다.</p>}
      {selected.elements.map(element => <article className="review-row" key={element.id}>
        <div className="review-row-main"><span className="review-name">{element.name}</span><span className="small text-secondary">{roleLabels[element.role]} · {element.category} · {element.source}</span></div>
        {element.evidence && <details className="small text-secondary mt-2"><summary>원문 근거 보기 · {element.source}</summary><p className="mt-2 mb-0">{element.evidence}</p></details>}
      </article>)}
    </div>
  </section>;
}

export default function WorkspaceWizard({ input, elements, references, profiles, runs, onInputChange, onElementsChange, approvedVersion, onApprove, report, onRun }: Props) {
  const approved = approvedVersion !== null;
  const [step, setStep] = useState<'input' | 'review' | 'result'>(() => report.result && approved ? 'result' : elements.length ? 'review' : 'input');
  const [extraction, setExtraction] = useState<{ status: 'idle' | 'loading' | 'error'; message?: string; warnings: string[] }>({ status: 'idle', warnings: [] });
  const [tab, setTab] = useState('overview');
  // 기술·RFP 선택은 탭 이동에는 유지되고, 새 분석 결과(다른 Run)가 오면 초기화된다.
  const [explore, setExplore] = useState<{ source: ReportViewResponse | null } & typeof initialExplore>({ source: report.result, ...initialExplore });
  if (explore.source !== report.result) setExplore({ source: report.result, ...initialExplore });
  // 탭 간 이동: 대상 ID만 바꾸고(모바일은 상세를 연다) 대상 상세 제목으로 포커스를 옮긴다. API는 호출하지 않는다.
  const [focusRequest, setFocusRequest] = useState<{ id: string } | null>(null);
  useEffect(() => { if (focusRequest) document.getElementById(focusRequest.id)?.focus(); }, [focusRequest]);
  const openGap = (rfpId: string, gapItemId: string) => { setExplore(current => ({ ...current, gap: { rfpId, selectedId: gapItemId, mobileDetailOpen: true } })); setTab('gap'); setFocusRequest({ id: 'gap-detail-title' }); };
  const openTechnology = (technologyId: string) => { setExplore(current => ({ ...current, technology: { selectedId: technologyId, mobileDetailOpen: true } })); setTab('technology'); setFocusRequest({ id: 'technology-detail-title' }); };
  const openRfp = (rfpId: string) => { setExplore(current => ({ ...current, rfp: { selectedId: rfpId, mobileDetailOpen: true } })); setTab('rfp'); setFocusRequest({ id: 'rfp-detail-title' }); };

  const submitInput = async (next: TechnologyInput, mode: 'extract' | 'manual') => {
    onInputChange(next);
    if (mode === 'manual') { setStep('review'); return; }
    setExtraction({ status: 'loading', warnings: [] });
    try {
      const result = await extractTechnologyElements(next);
      onElementsChange(result.elements);
      setExtraction({ status: 'idle', warnings: result.warnings });
      setStep('review');
    } catch (error) {
      // EXTRACTION_FAILED: 입력은 그대로 두고 재시도 또는 직접 정리를 선택하게 한다.
      setExtraction({ status: 'error', message: error instanceof Error ? error.message : '기술요소 추출에 실패했습니다.', warnings: [] });
    }
  };
  const run = () => { setStep('result'); onRun(); };

  const view = report.status === 'loading' ? 'running'
    : step === 'result' && report.status === 'error' ? 'failed'
      : step === 'result' && report.result && approved ? 'dashboard'
        : step === 'input' || !elements.length && step !== 'review' ? 'input' : 'review';
  const activeStep = view === 'input' ? 0 : view === 'review' ? 1 : 2;
  const availability = report.result ? viewAvailability(report.result) : null;
  const structured = report.result?.view && (availability === 'ok' || availability === 'empty') ? report.result.view : null;
  const viewCode = /^[a-z_]{1,40}$/.test(report.result?.view_error ?? '') ? ` (코드: ${report.result?.view_error})` : availability === 'mismatch' ? ' (코드: client_mismatch)' : '';

  if (view === 'dashboard' && report.result) return <><ApprovalHistory key={profiles.at(-1)?.id} profiles={profiles} runs={runs} /><section aria-labelledby="dashboard-title">
    <div className="section-toolbar">
      <div><h2 id="dashboard-title" className="h5 mb-1">분석 결과 · 기술요소 v{approvedVersion}</h2><div className="small text-secondary">실제 RAG 결과입니다. 새로고침하면 이 브라우저의 결과가 사라집니다.</div></div>
      <Button variant="outline-secondary" onClick={() => setStep('input')}>입력 수정 · 재분석</Button>
    </div>
    <Tabs activeKey={tab} onSelect={key => setTab(key ?? 'overview')} className="mb-3" id="workspace-result-tabs">
      <Tab eventKey="overview" title="Overview">
        {/* 구조화 view가 있으면 우선 추천 카드, 없으면(Projection 실패) 기존 Markdown 요약을 그대로 쓴다. */}
        <ReportOverview report={report.result.report} onOpenReport={() => setTab('report')}>
          {structured && <PrimaryPicks view={structured} onOpenTechnology={openTechnology} onOpenRfp={openRfp} />}
        </ReportOverview>
        {/* Overview는 보고서 섹션 6을 렌더링하지 않으므로 항상 표시한다. Report 탭은 섹션 6으로 같은 안내를 보여준다. */}
        <section className="app-card p-3 mt-3" aria-labelledby="common-rnd-notice">
          <h3 id="common-rnd-notice" className="h6">{COMMON_RND_NOTICE_TITLE}</h3>
          <p className="small text-secondary">{COMMON_RND_INTRO.join(' ')}</p>
          <ol className="small mb-0">{COMMON_RND_NOTICES.map(notice => <li key={notice}>{notice}</li>)}</ol>
        </section>
      </Tab>
      {/* Report와 독립된 상태: Projection 실패는 보고서 실패가 아니다. */}
      <Tab eventKey="technology" title="기술">
        {structured
          ? <TechnologyExplorer technologies={structured.technologies} gapItems={structured.gap_items} evidenceItems={structured.evidence_items}
            report={report.result.report} state={explore.technology} onChange={next => setExplore(current => ({ ...current, technology: next }))} />
          : <div className="mock-banner mt-0" role="status">구조화 기술 정보를 이용할 수 없습니다{viewCode}. 보고서는 정상 생성되었으며 Report 탭에서 확인할 수 있습니다.</div>}
      </Tab>
      <Tab eventKey="rfp" title="RFP">
        {structured
          ? <RfpExplorer rfps={structured.rfps} gapItems={structured.gap_items} evidenceItems={structured.evidence_items}
            report={report.result.report} state={explore.rfp} onChange={next => setExplore(current => ({ ...current, rfp: next }))} onOpenGap={openGap} />
          : <div className="mock-banner mt-0" role="status">구조화 RFP 정보를 이용할 수 없습니다{viewCode}. 보고서는 정상 생성되었으며 Report 탭에서 확인할 수 있습니다.</div>}
      </Tab>
      <Tab eventKey="gap" title="Gap">
        {structured
          ? <GapExplorer rfps={structured.rfps} gapItems={structured.gap_items} technologies={structured.technologies} evidenceItems={structured.evidence_items}
            report={report.result.report} state={explore.gap} onChange={next => setExplore(current => ({ ...current, gap: next }))} onOpenTechnology={openTechnology} />
          : <div className="mock-banner mt-0" role="status">구조화 Gap 정보를 이용할 수 없습니다{viewCode}. 보고서는 정상 생성되었으며 Report 탭에서 확인할 수 있습니다.</div>}
      </Tab>
      <Tab eventKey="evidence" title="Evidence">
        {availability === 'ok' && report.result.view && <EvidenceExplorer items={report.result.view.evidence_items} report={report.result.report} />}
        {availability === 'empty' && <div className="mock-banner mt-0">이번 분석에서 검증된 근거가 없습니다. 보고서는 Report 탭에서 확인할 수 있습니다.</div>}
        {(availability === 'failed' || availability === 'mismatch') && <div className="mock-banner mt-0" role="status">구조화 근거 탐색을 이용할 수 없습니다{viewCode}. 보고서는 정상 생성되었으며 Report 탭에서 확인할 수 있습니다.</div>}
      </Tab>
      <Tab eventKey="report" title="Report"><AnalysisReportView report={report.result.report} mode="real" /></Tab>
    </Tabs>
  </section></>;

  return <section aria-label="분석 Wizard">
    <ol className="wizard-steps">{steps.map((label, index) => <li key={label} className={index === activeStep ? 'active' : index < activeStep ? 'done' : undefined} aria-current={index === activeStep ? 'step' : undefined}><span>{index + 1}</span>{label}</li>)}</ol>
    <ApprovalHistory key={profiles.at(-1)?.id} profiles={profiles} runs={runs} />
    {(view === 'input' || view === 'review') && <ReferenceMaterials items={references.filter(item => item.mode === 'real')} />}
    {view === 'input' && <div className="app-card p-4">
      <h2 className="h6">보유 기술과 해결하려는 문제를 입력하세요</h2>
      <p className="small text-secondary">AI 추출은 버튼을 누를 때만 실행되며, 결과는 승인 전까지 후보입니다.</p>
      {elements.length > 0 && <div className="mock-banner mt-0">기존 기술요소 {elements.length}개가 있습니다. AI 추출을 실행하면 대체됩니다. <Button size="sm" variant="outline-secondary" onClick={() => setStep('review')}>기존 요소로 검토 계속</Button></div>}
      {extraction.status === 'error' && <div className="mock-banner mt-0" role="alert">{extraction.message} 입력은 보존되었습니다. 다시 시도하거나 직접 정리할 수 있습니다.</div>}
      {extraction.status === 'loading' && <div className="report-progress app-card" role="status" aria-live="polite"><span className="spinner-border spinner-border-sm" aria-hidden="true" /><strong>기술요소를 추출하고 있습니다.</strong></div>}
      <TechnologyForm value={input} onChange={onInputChange} onReview={submitInput} disabled={extraction.status === 'loading'}
        submitLabel={extraction.status === 'error' ? 'AI 추출 다시 시도' : 'AI로 기술요소 추출'} manualLabel="추출 없이 직접 정리" />
    </div>}
    {view === 'review' && <>
      {extraction.warnings.length > 0 && <div className="mock-banner mt-0">{extraction.warnings.join(' ')}</div>}
      <TechnologyReview input={input} elements={elements} onElementsChange={onElementsChange} onDone={onApprove}
        doneLabel={approved ? `승인됨 · v${approvedVersion}` : '이 기술요소로 승인'} doneBlocked={approved ? null : approvalBlocker(elements)} />
      <div className="app-card p-4 mt-3 d-flex justify-content-between align-items-center gap-3 flex-wrap">
        <div><strong className="small">{approved ? `승인된 기술요소 v${approvedVersion}로 분석할 수 있습니다.` : '승인 후 분석을 실행할 수 있습니다.'}</strong>
          <div className="small text-secondary">요소를 수정하면 승인이 해제됩니다. 승인은 이 브라우저에만 기록되며 서버에 저장되지 않습니다.</div></div>
        <div className="d-flex gap-2"><Button variant="outline-secondary" onClick={() => setStep('input')}>입력 수정</Button>
          <Button className="btn-accent" disabled={!approved} onClick={run}>통합 RAG 분석 실행</Button></div>
      </div>
    </>}
    {view === 'running' && <div className="report-progress app-card" role="status" aria-live="polite"><span className="spinner-border spinner-border-sm" aria-hidden="true" /><div><strong>근거를 수집하고 보고서를 작성하고 있습니다.</strong><p>나눔기술 → NTIS → RFP → Gap 순으로 분석하며 몇 분 걸릴 수 있습니다. 실제 진행률은 제공되지 않으며, 취소할 수 없습니다. 이 화면을 유지해 주세요.</p></div></div>}
    {view === 'failed' && <div className="mock-banner" role="alert">보고서를 생성하지 못했습니다. 승인된 기술요소는 유지됩니다. <Button size="sm" variant="outline-secondary" onClick={run} disabled={!approved}>다시 시도</Button> <Button size="sm" variant="outline-secondary" onClick={() => setStep('review')}>기술요소 검토로 돌아가기</Button></div>}
  </section>;
}
