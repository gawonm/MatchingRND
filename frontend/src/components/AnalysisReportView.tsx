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
  if (block.type === 'quote') return <blockquote><Inline text={block.text} /></blockquote>;
  if (block.type === 'list') {
    const List = block.ordered ? 'ol' : 'ul';
    return <List>{block.items.map((item, index) => <li key={index}><Inline text={item} /></li>)}</List>;
  }
  if (block.type === 'table') return <div className="analysis-table-wrap"><table className="table"><thead><tr>{block.rows[0].map((cell, index) => <th key={index}><Inline text={cell} /></th>)}</tr></thead><tbody>{block.rows.slice(1).map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, index) => <td key={index}><Inline text={cell} /></td>)}</tr>)}</tbody></table></div>;
  return <p><Inline text={block.text} /></p>;
}

export default function AnalysisReportView({ report }: { report: AnalysisReport }) {
  return <article className="report-paper" data-testid="analysis-report">
    <div className="eyebrow">최종 답변 형식 / MOCK PREVIEW</div>
    <div className="mock-banner">실제 분석 결과가 아니며 실제 API는 연결되지 않았습니다.</div>
    {parseReportMarkdown(report.markdown).map(section => <section key={section.heading}>
      <h2>{section.heading}</h2>
      <div className="analysis-markdown">{section.blocks.map((block, index) => <Block key={index} block={block} />)}</div>
    </section>)}
  </article>;
}
