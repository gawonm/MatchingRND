import type { AnalysisReport } from '../types/analysisReport';
import { parseReportMarkdown, safeLink, type MarkdownBlock } from '../lib/reportMarkdown';

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
