import type { AnalysisReport } from '../types/analysisReport';

const sectionPattern = /^## (1\. 우선 추천 나눔기술|2\. 우선 추천 공고|3\. 기술요소 Gap|4\. 관련 RFP|5\. 관련 나눔기술|6\. 관련 법령|7\. 확인이 필요한 사항)$/;

function sections(markdown: string) {
  const result: { heading: string; body: string[] }[] = [];
  let current = { heading: '기술기획 분석 결과', body: [] as string[] };
  for (const line of markdown.trim().split('\n')) {
    if (sectionPattern.test(line)) {
      result.push(current);
      current = { heading: line.slice(3), body: [] };
    } else if (!line.startsWith('# ')) current.body.push(line);
  }
  result.push(current);
  return result;
}

export default function AnalysisReportView({ report }: { report: AnalysisReport }) {
  return <article className="report-paper" data-testid="analysis-report">
    <div className="eyebrow">최종 답변 형식 / MOCK PREVIEW</div>
    <div className="mock-banner">실제 분석 결과가 아니며 실제 API는 연결되지 않았습니다.</div>
    {sections(report.markdown).map(section => <section key={section.heading}>
      <h2>{section.heading}</h2>
      <pre className="analysis-markdown">{section.body.join('\n').trim()}</pre>
    </section>)}
  </article>;
}
