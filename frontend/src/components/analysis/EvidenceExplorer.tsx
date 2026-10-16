import { useEffect, useRef, useState } from 'react';
import { Button } from 'react-bootstrap';
import type { AnalysisReport, EvidenceItem } from '../../types/analysisReport';
import { claimsForEvidence, httpLinks, SOURCE_LABELS } from '../../lib/analysisView';

const sectionLabels: Record<string, string> = { external: '나눔기술', ntis: '선행 과제', rfp: 'RFP', gap: 'Gap', policy: '법령 참고', next_steps: '후속 확인' };

export function EvidenceDetail({ item, report, onClose }: { item: EvidenceItem; report: AnalysisReport; onClose: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [item.id]);
  const claims = claimsForEvidence(report, item);
  const links = item.source_type === 'rfp' ? httpLinks(item.notice_urls) : [];
  const location = [item.document_id, item.page !== null && `${item.page + 1}쪽`, item.section].filter(Boolean).join(' · ');
  return <aside className="evidence-detail app-card" aria-labelledby={`evidence-detail-${item.id}`} onKeyDown={event => { if (event.key === 'Escape') onClose(); }}>
    <div className="d-flex justify-content-between align-items-start gap-2">
      <div className="eyebrow">[{item.id}] {SOURCE_LABELS[item.source_type]}</div>
      <Button size="sm" variant="outline-secondary" onClick={onClose} aria-label="근거 상세 닫기">닫기</Button>
    </div>
    <h3 id={`evidence-detail-${item.id}`} className="h6 mt-2" tabIndex={-1} ref={heading}>{item.source_title ?? '문서 제목 미제공'}</h3>
    <p className="small text-secondary">{location || '위치 정보 미제공'}</p>
    <h4 className="evidence-label">원문 인용</h4>
    <blockquote className="evidence-quote">{item.quote}</blockquote>
    <h4 className="evidence-label">이 근거를 사용한 주장 <span className="text-secondary fw-normal">AI 작성 · 인용·의미 검토 통과</span></h4>
    {claims.length ? <ul className="evidence-claims">{claims.map(claim => <li key={claim.index}><span className="text-secondary">{sectionLabels[claim.section] ?? claim.section}</span> {claim.text}</li>)}</ul>
      : <p className="small text-secondary">이 근거를 인용한 검증된 주장이 없습니다.</p>}
    {links.length > 0 && <><h4 className="evidence-label">공고 링크</h4><ul className="list-unstyled small mb-0">{links.map((url, i) => <li key={url}><a href={url} target="_blank" rel="noopener noreferrer">공고 페이지 {i + 1}</a></li>)}</ul></>}
  </aside>;
}

// 공통 근거 탐색기. ids를 주면 해당 근거만 보여준다(이후 기술·RFP·Gap 탭에서 재사용).
export default function EvidenceExplorer({ items, report, ids }: { items: EvidenceItem[]; report: AnalysisReport; ids?: string[] }) {
  const shown = ids ? items.filter(item => ids.includes(item.id)) : items;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const selected = shown.find(item => item.id === selectedId) ?? null;
  const close = () => { setSelectedId(null); opener.current?.focus(); };
  if (!shown.length) return <p className="small text-secondary mb-0">검증된 근거가 없습니다.</p>;
  return <div className={`evidence-explorer${selected ? ' has-detail' : ''}`}>
    <ul className="evidence-list list-unstyled mb-0" aria-label="근거 목록">
      {shown.map(item => <li key={item.id}>
        <button type="button" className="evidence-row" aria-pressed={item.id === selectedId}
          onClick={event => { opener.current = event.currentTarget; setSelectedId(item.id); }}>
          <span className="small text-secondary">[{item.id}] {SOURCE_LABELS[item.source_type]}{claimsForEvidence(report, item).length ? ` · 주장 ${claimsForEvidence(report, item).length}` : ''}</span>
          <strong className="small d-block">{item.source_title ?? item.document_id}</strong>
          <span className="evidence-snippet">{item.quote}</span>
        </button>
      </li>)}
    </ul>
    {selected ? <EvidenceDetail item={selected} report={report} onClose={close} />
      : <p className="evidence-placeholder small text-secondary">목록에서 근거를 선택하면 원문과 연결된 주장을 확인할 수 있습니다.</p>}
  </div>;
}
