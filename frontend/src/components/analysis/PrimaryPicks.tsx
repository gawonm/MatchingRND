import type { AnalysisView } from '../../types/analysisReport';
import { primaryCandidate } from '../../lib/analysisView';

type Props = {
  view: AnalysisView;
  onOpenTechnology: (technologyId: string) => void;
  onOpenRfp: (rfpId: string) => void;
};

// Overview 진입점: 구조화 결과의 우선 추천 후보만 보여주고 상세 탭으로 보낸다. Gap 요약·점수는 만들지 않는다.
export default function PrimaryPicks({ view, onOpenTechnology, onOpenRfp }: Props) {
  const technology = primaryCandidate(view.technologies, view.overview.primary_technology_id);
  const rfp = primaryCandidate(view.rfps, view.overview.primary_rfp_id);
  return <>
    <div className="overview-picks overview-wide">
      <section className="app-card p-3 primary-pick" aria-labelledby="primary-technology-title">
        <h3 id="primary-technology-title" className="h6">우선 추천 나눔기술</h3>
        {technology === 'empty' ? <p className="small text-secondary mb-0">추천된 나눔기술이 없습니다.</p>
          : technology === 'missing' ? <p className="small text-secondary mb-0">우선 추천 나눔기술을 구조화 결과에서 확인할 수 없습니다. 기술 탭과 Report 탭에서 확인하세요.</p>
            : <>
              <div className="eyebrow">추천 {technology.rank}순위</div>
              <strong className="d-block my-2">{technology.title}</strong>
              <button type="button" className="btn btn-accent-outline btn-sm" onClick={() => onOpenTechnology(technology.id)}>기술 상세 보기 →</button>
            </>}
      </section>
      <section className="app-card p-3 primary-pick" aria-labelledby="primary-rfp-title">
        <h3 id="primary-rfp-title" className="h6">우선 추천 RFP</h3>
        {rfp === 'empty' ? <p className="small text-secondary mb-0">추천된 RFP가 없습니다.</p>
          : rfp === 'missing' ? <p className="small text-secondary mb-0">우선 추천 RFP를 구조화 결과에서 확인할 수 없습니다. RFP 탭과 Report 탭에서 확인하세요.</p>
            : <>
              <div className="eyebrow">추천 {rfp.rank}순위</div>
              <strong className="d-block my-2">{rfp.title}</strong>
              <button type="button" className="btn btn-accent-outline btn-sm" onClick={() => onOpenRfp(rfp.id)}>RFP 상세 보기 →</button>
            </>}
      </section>
    </div>
    <section className="app-card p-3 overview-wide" aria-labelledby="analysis-scope-title">
      <h3 id="analysis-scope-title" className="h6">분석 범위 안내</h3>
      <p className="small mb-1">Gap 분석은 추천 RFP의 요구 기술요소를 기준으로 수행합니다. 분석된 RFP의 상세 판정은 Gap 탭에서 확인할 수 있습니다.</p>
      <p className="small text-secondary mb-0">Gap 분석 수행 여부는 RFP마다 다르며 RFP 탭과 Gap 탭에 표시됩니다. 추천 순위는 검증된 후보의 정렬 순서이며 적합도나 과제 선정 가능성을 뜻하지 않습니다.</p>
    </section>
  </>;
}
