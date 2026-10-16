import type { AnalysisReport, EvidenceItem, GapItem, RFPCandidate, TechnologyCandidate } from '../../types/analysisReport';
import { gapClaims, gapLabelText, gapSelection, gapTechnologies, rankedSelection } from '../../lib/analysisView';
import EvidenceExplorer from './EvidenceExplorer';
import SplitExplorer, { type SplitViewState } from './SplitExplorer';

// selectedId는 GapItem.id. rfpId는 Gap 분석이 수행된 RFP 중 선택한 것.
export type GapViewState = SplitViewState & { rfpId: string | null };

type Props = {
  rfps: RFPCandidate[];
  gapItems: GapItem[];
  technologies: TechnologyCandidate[];
  evidenceItems: EvidenceItem[];
  report: AnalysisReport;
  state: GapViewState;
  onChange: (state: GapViewState) => void;
  onOpenTechnology: (technologyId: string) => void;
};

const STATUS_NOTES: Record<RFPCandidate['gap_analysis_status'], string> = {
  analyzed: '',
  not_analyzed: '해당 RFP는 추천 대상이지만 기술요소별 Gap 분석을 수행하지 않았습니다.',
  unknown: '해당 RFP의 Gap 분석 수행 여부를 확인할 수 없습니다.',
};

export default function GapExplorer({ rfps, gapItems, technologies, evidenceItems, report, state, onChange, onOpenTechnology }: Props) {
  const analyzed = rankedSelection(rfps.filter(rfp => rfp.gap_analysis_status === 'analyzed'), state.rfpId);
  const others = rankedSelection(rfps.filter(rfp => rfp.gap_analysis_status !== 'analyzed'), null).ordered;
  const rfp = analyzed.selected;
  const gaps = rfp ? gapSelection(rfp, gapItems, state.selectedId) : null;
  const gap = gaps?.selected ?? null;

  const picker = <section className="app-card p-3 mb-3" aria-labelledby="gap-rfp-title">
    <h3 id="gap-rfp-title" className="h6">분석 대상 RFP</h3>
    {analyzed.ordered.length ? <div className="gap-rfp-picker" role="group" aria-label="Gap 분석 RFP 선택">
      {analyzed.ordered.map(item => <button key={item.id} type="button" className="evidence-row" aria-pressed={item.id === rfp?.id}
        onClick={() => onChange({ rfpId: item.id, selectedId: null, mobileDetailOpen: false })}>
        <span className="small text-secondary">추천 {item.rank}순위 · Gap 분석 완료</span>
        <strong className="small d-block">{item.title}</strong>
      </button>)}
    </div> : <p className="small mb-0">Gap 분석이 확인된 RFP가 없습니다. 추천 RFP와 최종 보고서를 확인하세요.</p>}
    {others.length > 0 && <ul className="small text-secondary mt-2 mb-0">
      {others.map(item => <li key={item.id}>추천 {item.rank}순위 {item.title} — {STATUS_NOTES[item.gap_analysis_status]}</li>)}
    </ul>}
  </section>;

  if (!rfp || !gaps) return picker;
  const unresolvedNote = gaps.unresolved > 0 && <p className="small text-secondary mb-2">연결 정보를 찾을 수 없는 Gap 항목 {gaps.unresolved}개는 표시하지 않았습니다.</p>;
  if (!gap) return <>{picker}{unresolvedNote}<div className="mock-banner mt-0">이 RFP에 연결된 Gap 항목이 없습니다.</div></>;

  const claims = gapClaims(report, gap);
  const external = gapTechnologies(gap, technologies);
  const evidence = evidenceItems.filter(item => gap.evidence_ids.includes(item.id));
  const hasLinks = gap.owned_technologies.length > 0 || external.linked.length > 0 || evidence.length > 0;

  return <>
    {picker}
    {unresolvedNote}
    <SplitExplorer name="gap" label={`${rfp.title} 요구 기술요소 목록`} ordered={gaps.ordered} selected={gap} duplicates={gaps.duplicates}
      state={state} onChange={next => onChange({ ...next, rfpId: rfp.id })}
      row={item => <>
        <span className="small text-secondary">{gapLabelText(item.label)}</span>
        <strong className="small d-block">{item.requirement_name}</strong>
      </>}
      eyebrow={<>판정 · {gapLabelText(gap.label)}</>} title={gap.requirement_name}>
      <p className="small text-secondary mb-0">요구기술 ID {gap.requirement_id} · RFP {rfp.title}</p>
      {!gap.requirement_clear && <p className="small mb-0">요구기술 표현의 명확성 확인 필요</p>}
      {gap.label === '근거부족' && <p className="small text-secondary mb-0">근거부족은 기술이 없다는 판정이 아니라, 충족 여부를 판단할 검증 근거가 부족하다는 뜻입니다.</p>}

      <h4 className="evidence-label">판정 설명</h4>
      {claims.length ? <>
        <p className="small text-secondary mb-1">검증된 분석 설명 · AI 작성 · 인용·의미 검토 통과</p>
        <ul className="evidence-claims">{claims.map((text, i) => <li key={i}>{text}</li>)}</ul>
      </> : <p className="small text-secondary mb-0">{hasLinks ? '별도의 검증된 설명이 제공되지 않았습니다. 아래 연결 기술과 근거를 확인하세요.' : '별도의 검증된 설명과 연결된 기술·근거가 제공되지 않았습니다.'}</p>}

      <h4 className="evidence-label">기존 보유기술 <span className="text-secondary fw-normal">사용자 입력 기술과의 검증된 매칭</span></h4>
      {gap.owned_technologies.length ? <ul className="small mb-0">{gap.owned_technologies.map(name => <li key={name}>{name}</li>)}</ul>
        : <p className="small text-secondary mb-0">연결된 보유기술 정보 없음</p>}

      <h4 className="evidence-label">외부 나눔기술 <span className="text-secondary fw-normal">추천 결과 간 연결이며 기술이전·기술 확보를 뜻하지 않습니다</span></h4>
      {external.linked.length ? <ul className="list-unstyled small mb-0">{external.linked.map(technology => <li key={technology.id}>
        <button type="button" className="btn btn-link btn-sm p-0 text-start" onClick={() => onOpenTechnology(technology.id)}>추천 {technology.rank}순위 · {technology.title}</button>
      </li>)}</ul> : <p className="small text-secondary mb-0">연결된 외부 나눔기술 없음</p>}
      {external.unresolved > 0 && <p className="small text-secondary mt-1 mb-0">추천 목록에서 확인할 수 없는 외부기술 {external.unresolved}개는 표시하지 않았습니다.</p>}

      <h4 className="evidence-label">검증된 근거</h4>
      {evidence.length ? <EvidenceExplorer key={gap.id} items={evidence} report={report} />
        : <p className="small text-secondary mb-0">연결된 검증 근거가 없습니다.</p>}
    </SplitExplorer>
  </>;
}
