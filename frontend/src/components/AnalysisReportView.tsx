import type { ReactNode } from 'react';
import type { AnalysisReport } from '../types/analysisReport';
import { parseReportMarkdown, REPORT_HEADINGS, safeLink, type MarkdownBlock } from '../lib/reportMarkdown';

const inlinePattern = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;

function Inline({ text }: { text: string }) {
  return <>{text.split(inlinePattern).filter(Boolean).map((part, index) => {
    if (part.startsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      const href = safeLink(link[2]);
      return href ? <a key={index} href={href} {...(href.startsWith('#') ? {} : { target: '_blank', rel: 'noopener noreferrer' })}>{link[1]}</a> : <span key={index}>{link[1]}</span>;
    }
    return part;
  })}</>;
}

function Block({ block }: { block: MarkdownBlock }) {
  if (block.type === 'subheading') return <h3>{block.text}</h3>;
  if (block.type === 'quote') return <details className="report-citation"><summary>원문 인용 보기</summary><blockquote><Inline text={block.text} /></blockquote></details>;
  if (block.type === 'list') {
    const List = block.ordered ? 'ol' : 'ul';
    return <List>{block.items.map((item, index) => <li key={index}><Inline text={item} /></li>)}</List>;
  }
  if (block.type === 'table') return <div className="analysis-table-wrap"><table className="table"><thead><tr>{block.rows[0].map((cell, index) => <th key={index}><Inline text={cell} /></th>)}</tr></thead><tbody>{block.rows.slice(1).map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, index) => <td key={index}><Inline text={cell} /></td>)}</tr>)}</tbody></table></div>;
  return <p><Inline text={block.text} /></p>;
}

const statusLabels: Record<AnalysisReport['status'], string> = { ok: '보고서 생성 완료', partial: '보고서 일부 항목 제한', insufficient: '근거 부족 보고서', template: '템플릿 보고서' };

// Overview는 answer_format.py 정규 섹션의 첫 하위 제목 이전 블록만 그대로 보여준다(요약 생성·추정 없음).
const overviewSections = [
  ['핵심 분석 요약', '기술기획 분석 결과'], ['1순위 나눔기술', REPORT_HEADINGS[0]], ['1순위 RFP', REPORT_HEADINGS[1]],
  ['Gap 요약', REPORT_HEADINGS[2]], ['후속 확인사항', REPORT_HEADINGS[6]],
] as const;

// children(구조화 추천)이 있으면 Markdown 섹션 요약 대신 표시한다. 없으면(view 실패) 기존 Markdown 요약을 유지한다.
export function ReportOverview({ report, onOpenReport, children }: { report: AnalysisReport; onOpenReport: () => void; children?: ReactNode }) {
  const sections = parseReportMarkdown(report.markdown);
  return <div className="overview-grid" data-testid="analysis-overview">
    <div className="app-card p-3 overview-status"><strong>{statusLabels[report.status]}</strong><span className="small text-secondary"> · status: {report.status} · 근거 {report.evidence.length}건</span>
      {report.warnings.length > 0 && <ul className="small mb-0 mt-2">{report.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>}</div>
    {children ?? overviewSections.map(([title, heading]) => {
      const section = sections.find(item => item.heading === heading);
      const end = section?.blocks.findIndex(block => block.type === 'subheading') ?? -1;
      const blocks = section ? section.blocks.slice(0, end === -1 ? undefined : end) : [];
      return <section className={`app-card p-3 analysis-markdown${heading === REPORT_HEADINGS[2] ? ' overview-wide' : ''}`} key={title}><h3 className="h6">{title}</h3>
        {blocks.length ? blocks.map((block, index) => <Block key={index} block={block} />) : <p className="small text-secondary mb-0">보고서에 해당 섹션이 없습니다.</p>}</section>;
    })}
    <button type="button" className="btn btn-accent-outline" onClick={onOpenReport}>전체 보고서 · 원문 근거 보기</button>
  </div>;
}

export default function AnalysisReportView({ report, mode = 'mock' }: { report: AnalysisReport; mode?: 'mock' | 'real' }) {
  const sections = parseReportMarkdown(report.markdown);
  return <article className="report-paper" data-testid="analysis-report">
    <div className="eyebrow">최종 답변 형식 / {mode === 'real' ? '실제 RAG 결과' : 'MOCK PREVIEW'}</div>
    {mode === 'mock' && <div className="mock-banner">실제 분석 결과가 아닌 Mock 미리보기입니다.</div>}
    <nav className="report-nav" aria-label="보고서 섹션 바로가기">
      {sections.slice(1).map((section, index) => <button key={section.heading} type="button" onClick={() => document.getElementById(`report-section-${index + 1}`)?.scrollIntoView()}>{section.heading}</button>)}
    </nav>
    {sections.map((section, index) => <section className={index === 1 || index === 2 ? 'report-priority' : undefined} id={index ? `report-section-${index}` : undefined} key={section.heading}>
      <h2>{section.heading}</h2>
      <div className="analysis-markdown">{section.blocks.map((block, index) => <Block key={index} block={block} />)}</div>
    </section>)}
  </article>;
}
