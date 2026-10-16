import { useState } from 'react';
import { Button, Tab, Tabs } from 'react-bootstrap';
import TechnologyForm from './TechnologyForm';
import TechnologyReview from './TechnologyReview';
import AnalysisReportView, { ReportOverview } from './AnalysisReportView';
import { extractTechnologyElements } from '../api';
import type { ReportEntry } from '../state/analysisReports';
import { approvalBlocker } from '../state/analysisSession';
import type { TechnologyElement } from '../types/technologyElement';
import type { TechnologyInput } from '../types/technologyInput';

type Props = {
  input: TechnologyInput;
  elements: TechnologyElement[];
  onInputChange: (input: TechnologyInput) => void;
  onElementsChange: (elements: TechnologyElement[]) => void;
  approvedVersion: number | null;
  onApprove: () => void;
  report: Pick<ReportEntry, 'status' | 'result'>;
  onRun: () => void;
};

const steps = ['기술 및 문제 입력', '기술요소 검토·승인', '통합 RAG 분석'];

export default function WorkspaceWizard({ input, elements, onInputChange, onElementsChange, approvedVersion, onApprove, report, onRun }: Props) {
  const approved = approvedVersion !== null;
  const [step, setStep] = useState<'input' | 'review' | 'result'>(() => report.result && approved ? 'result' : elements.length ? 'review' : 'input');
  const [extraction, setExtraction] = useState<{ status: 'idle' | 'loading' | 'error'; message?: string; warnings: string[] }>({ status: 'idle', warnings: [] });
  const [tab, setTab] = useState('overview');

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

  if (view === 'dashboard' && report.result) return <section aria-labelledby="dashboard-title">
    <div className="section-toolbar">
      <div><h2 id="dashboard-title" className="h5 mb-1">분석 결과 · 기술요소 v{approvedVersion}</h2><div className="small text-secondary">실제 RAG 결과입니다. 새로고침하면 이 브라우저의 결과가 사라집니다.</div></div>
      <Button variant="outline-secondary" onClick={() => setStep('input')}>입력 수정 · 재분석</Button>
    </div>
    <Tabs activeKey={tab} onSelect={key => setTab(key ?? 'overview')} className="mb-3" id="workspace-result-tabs">
      <Tab eventKey="overview" title="Overview"><ReportOverview report={report.result} onOpenReport={() => setTab('report')} /></Tab>
      <Tab eventKey="report" title="Report"><AnalysisReportView report={report.result} mode="real" /></Tab>
    </Tabs>
  </section>;

  return <section aria-label="분석 Wizard">
    <ol className="wizard-steps">{steps.map((label, index) => <li key={label} className={index === activeStep ? 'active' : index < activeStep ? 'done' : undefined} aria-current={index === activeStep ? 'step' : undefined}><span>{index + 1}</span>{label}</li>)}</ol>
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
