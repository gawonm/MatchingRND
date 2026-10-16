export const REPORT_HEADINGS = [
  '1. 우선 추천 나눔기술', '2. 우선 추천 공고', '3. 기술요소 Gap',
  '4. 관련 RFP', '5. 관련 나눔기술', '6. 관련 법령', '7. 확인이 필요한 사항',
] as const;

export type MarkdownBlock =
  | { type: 'subheading' | 'paragraph' | 'quote'; text: string }
  | { type: 'list'; ordered: boolean; items: string[] }
  | { type: 'table'; rows: string[][] };

export type ReportSection = { heading: string; blocks: MarkdownBlock[] };

const sectionPattern = new RegExp(`^## (${REPORT_HEADINGS.join('|')})$`);
const tableRow = (line: string) => line.slice(1, -1).split('|').map(cell => cell.trim().replaceAll('\\|', '|'));

export function safeLink(href: string) {
  if (href.startsWith('#')) return href;
  try {
    const url = new URL(href);
    return url.protocol === 'http:' || url.protocol === 'https:' ? href : null;
  } catch {
    return null;
  }
}

export function parseReportMarkdown(markdown: string): ReportSection[] {
  const sections: ReportSection[] = [{ heading: '기술기획 분석 결과', blocks: [] }];
  let lines: string[] = [];
  const flush = () => {
    if (!lines.length) return;
    const section = sections.at(-1)!;
    const first = lines[0];
    if (first.startsWith('### ')) section.blocks.push({ type: 'subheading', text: first.slice(4) });
    else if (first.startsWith('> ')) section.blocks.push({ type: 'quote', text: lines.map(line => line.slice(2)).join(' ') });
    else if (/^\|.*\|$/.test(first) && lines.length > 1 && /^\|(?:\s*:?-+:?\s*\|)+$/.test(lines[1])) {
      section.blocks.push({ type: 'table', rows: [tableRow(first), ...lines.slice(2).map(tableRow)] });
    } else if (lines.every(line => /^- /.test(line))) section.blocks.push({ type: 'list', ordered: false, items: lines.map(line => line.slice(2)) });
    else if (lines.every(line => /^\d+\. /.test(line))) section.blocks.push({ type: 'list', ordered: true, items: lines.map(line => line.replace(/^\d+\. /, '')) });
    else section.blocks.push({ type: 'paragraph', text: lines.join(' ') });
    lines = [];
  };

  for (const line of markdown.trim().split(/\r?\n/)) {
    const section = line.match(sectionPattern);
    if (section) {
      flush();
      sections.push({ heading: section[1], blocks: [] });
    } else if (!line.trim()) flush();
    else if (!line.startsWith('# ')) {
      if (line.startsWith('### ')) flush();
      lines.push(line);
      if (line.startsWith('### ')) flush();
    }
  }
  flush();
  return sections;
}
