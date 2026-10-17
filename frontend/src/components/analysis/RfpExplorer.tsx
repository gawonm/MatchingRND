import type { AnalysisReport, EvidenceItem, GapItem, RFPCandidate } from '../../types/analysisReport';
import { GAP_STATUS_LABELS, httpLinks, rankedSelection, rfpRequirements } from '../../lib/analysisView';
import EvidenceExplorer from './EvidenceExplorer';
import SplitExplorer, { type SplitViewState } from './SplitExplorer';

type Props = {
  rfps: RFPCandidate[];
  gapItems: GapItem[];
  evidenceItems: EvidenceItem[];
  report: AnalysisReport;
  state: SplitViewState;
  onChange: (state: SplitViewState) => void;
  onOpenGap: (rfpId: string, gapItemId: string) => void;
};

export default function RfpExplorer({ rfps, gapItems, evidenceItems, report, state, onChange, onOpenGap }: Props) {
  const { ordered, selected, duplicates } = rankedSelection(rfps, state.selectedId);
  if (!selected) return <div className="mock-banner mt-0">이번 분석에서 추천된 RFP가 없습니다. 보고서는 Report 탭에서 확인할 수 있습니다.</div>;

  const { linked, unresolved } = rfpRequirements(selected, gapItems);
  const links = httpLinks(selected.notice_urls);
  const evidence = evidenceItems.filter(item => selected.evidence_ids.includes(item.id));
  const status = GAP_STATUS_LABELS[selected.gap_analysis_status];

  return <SplitExplorer name="rfp" label="추천 RFP 목록" ordered={ordered} selected={selected} duplicates={duplicates} state={state} onChange={onChange}
    row={rfp => <>
      <span className="small text-secondary">추천 {rfp.rank}순위 · {GAP_STATUS_LABELS[rfp.gap_analysis_status]}</span>
      <strong className="small d-block">{rfp.title}</strong>
    </>}
    eyebrow={<>추천 {selected.rank}순위 · {status}</>} title={selected.title}>
      <p className="small text-secondary mb-0">문서 ID {selected.document_id}</p>
      <p className="small text-secondary">추천 순서는 보고서의 정렬 순서이며 적합도나 지원 가능성을 뜻하지 않습니다. Gap 분석 여부는 기술요소별 판정을 수행했는지만 나타냅니다.</p>

      <h4 className="evidence-label">모공고</h4>
      {selected.notice_titles.length ? <ul className="small mb-0">{selected.notice_titles.map(title => <li key={title}>{title}</li>)}</ul>
        : <p className="small text-secondary mb-0">모공고 정보가 제공되지 않았습니다.</p>}
      {/* 제목과 URL은 따로 수집·중복 제거되므로 인덱스로 짝짓지 않는다. */}
      {/* ponytail: notice_titles/notice_urls는 위치별 대응이 없어 제목과 링크를 따로 표시, 백엔드가 {title, url} 공고 객체를 내보내면 제목에 링크를 붙인다 */}
      {links.length > 0 && <><h4 className="evidence-label">공고 링크 <span className="text-secondary fw-normal">공고 페이지이며 RFP 원문 PDF가 아닙니다</span></h4>
        <ul className="list-unstyled small mb-0">{links.map((url, i) => <li key={url}><a href={url} target="_blank" rel="noopener noreferrer">공고 페이지 {i + 1}</a></li>)}</ul></>}

      <h4 className="evidence-label">연결된 RFP 요구 기술요소</h4>
      {selected.gap_analysis_status === 'not_analyzed' && <p className="small text-secondary mb-0">Gap 미분석 — 기술요소별 판정이 수행되지 않았습니다.</p>}
      {selected.gap_analysis_status === 'unknown' && <p className="small text-secondary mb-0">Gap 분석 여부를 확인할 수 없습니다.</p>}
      {selected.gap_analysis_status === 'analyzed' && (linked.length
        ? <ul className="list-unstyled small mb-0">{linked.map(gap => <li key={gap.id}>
          <button type="button" className="btn btn-link btn-sm p-0 text-start" onClick={() => onOpenGap(selected.id, gap.id)}>{gap.requirement_name}</button>
        </li>)}</ul>
        : <p className="small text-secondary mb-0">분석된 항목의 연결 정보 없음</p>)}
      {unresolved > 0 && <p className="small text-secondary mt-1 mb-0">연결 정보를 찾을 수 없는 항목 {unresolved}개는 표시하지 않았습니다.</p>}

      <h4 className="evidence-label">검증된 근거</h4>
      {evidence.length ? <EvidenceExplorer key={selected.id} items={evidence} report={report} />
        : <p className="small text-secondary mb-0">연결된 검증 근거 없음</p>}
  </SplitExplorer>;
}
