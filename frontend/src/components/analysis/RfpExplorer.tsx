import { useEffect, useRef } from 'react';
import { Button } from 'react-bootstrap';
import type { AnalysisReport, EvidenceItem, GapItem, RFPCandidate } from '../../types/analysisReport';
import { GAP_STATUS_LABELS, httpLinks, rfpRequirements, rfpSelection } from '../../lib/analysisView';
import EvidenceExplorer from './EvidenceExplorer';

// 분석 요청 상태와 분리된 화면 상태. 새 분석 결과가 오면 Workspace가 초기화한다.
export type RfpViewState = { selectedRfpId: string | null; mobileDetailOpen: boolean };

type Props = {
  rfps: RFPCandidate[];
  gapItems: GapItem[];
  evidenceItems: EvidenceItem[];
  report: AnalysisReport;
  state: RfpViewState;
  onChange: (state: RfpViewState) => void;
};

const isMobile = () => window.matchMedia('(max-width: 767.98px)').matches;

export default function RfpExplorer({ rfps, gapItems, evidenceItems, report, state, onChange }: Props) {
  const { ordered, selected } = rfpSelection(rfps, state.selectedRfpId);
  const heading = useRef<HTMLHeadingElement>(null);
  const rows = useRef(new Map<string, HTMLButtonElement>());
  const listScroll = useRef(0);
  const returnTo = useRef<string | null>(null);
  // 모바일: 상세가 열리면 제목으로, 목록으로 돌아오면 스크롤 위치와 선택 항목으로 포커스를 되돌린다.
  useEffect(() => {
    if (state.mobileDetailOpen) {
      heading.current?.focus({ preventScroll: true });
      heading.current?.closest('section')?.scrollIntoView({ block: 'start', behavior: 'instant' }); // 상단 '목록으로'까지 보이게
      return;
    }
    if (!returnTo.current) return;
    window.scrollTo({ top: listScroll.current, behavior: 'instant' }); // Bootstrap의 smooth scroll을 피한다
    rows.current.get(returnTo.current)?.focus({ preventScroll: true });
    returnTo.current = null;
  }, [state.mobileDetailOpen, selected?.id]);

  if (!selected) return <div className="mock-banner mt-0">이번 분석에서 추천된 RFP가 없습니다. 보고서는 Report 탭에서 확인할 수 있습니다.</div>;

  const select = (id: string) => { listScroll.current = window.scrollY; onChange({ selectedRfpId: id, mobileDetailOpen: isMobile() }); };
  const back = () => { returnTo.current = selected.id; onChange({ selectedRfpId: selected.id, mobileDetailOpen: false }); };
  const { linked, unresolved } = rfpRequirements(selected, gapItems);
  const links = httpLinks(selected.notice_urls);
  const evidence = evidenceItems.filter(item => selected.evidence_ids.includes(item.id));
  const status = GAP_STATUS_LABELS[selected.gap_analysis_status];

  return <div className={`rfp-split${state.mobileDetailOpen ? ' detail-open' : ''}`}>
    <ul className="rfp-list list-unstyled mb-0" aria-label="추천 RFP 목록">
      {ordered.map(rfp => <li key={rfp.id}>
        <button type="button" className="evidence-row" aria-pressed={rfp.id === selected.id} aria-controls="rfp-detail"
          ref={element => { if (element) rows.current.set(rfp.id, element); else rows.current.delete(rfp.id); }}
          onClick={() => select(rfp.id)}>
          <span className="small text-secondary">추천 {rfp.rank}순위 · {GAP_STATUS_LABELS[rfp.gap_analysis_status]}</span>
          <strong className="small d-block">{rfp.title}</strong>
        </button>
      </li>)}
    </ul>
    <section id="rfp-detail" className="rfp-detail app-card" aria-labelledby="rfp-detail-title">
      <Button className="rfp-back" size="sm" variant="outline-secondary" onClick={back}>← 목록으로</Button>
      <div className="eyebrow">추천 {selected.rank}순위 · {status}</div>
      <h3 id="rfp-detail-title" className="h6 mt-2" tabIndex={-1} ref={heading}>{selected.title}</h3>
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
        ? <ul className="small mb-0">{linked.map(gap => <li key={gap.id}>{gap.requirement_name}</li>)}</ul>
        : <p className="small text-secondary mb-0">분석된 항목의 연결 정보 없음</p>)}
      {unresolved > 0 && <p className="small text-secondary mt-1 mb-0">연결 정보를 찾을 수 없는 항목 {unresolved}개는 표시하지 않았습니다.</p>}

      <h4 className="evidence-label">검증된 근거</h4>
      {evidence.length ? <EvidenceExplorer key={selected.id} items={evidence} report={report} />
        : <p className="small text-secondary mb-0">연결된 검증 근거 없음</p>}
    </section>
  </div>;
}
