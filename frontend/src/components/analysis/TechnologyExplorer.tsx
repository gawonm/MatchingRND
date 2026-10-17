import type { AnalysisReport, EvidenceItem, GapItem, TechnologyCandidate } from '../../types/analysisReport';
import { MATCH_LEVEL_LABELS, matchLevelLabel, rankedSelection, technologyRequirements } from '../../lib/analysisView';
import EvidenceExplorer from './EvidenceExplorer';
import SplitExplorer, { type SplitViewState } from './SplitExplorer';

type Props = {
  technologies: TechnologyCandidate[];
  gapItems: GapItem[];
  evidenceItems: EvidenceItem[];
  report: AnalysisReport;
  state: SplitViewState;
  onChange: (state: SplitViewState) => void;
};

export default function TechnologyExplorer({ technologies, gapItems, evidenceItems, report, state, onChange }: Props) {
  const { ordered, selected, duplicates } = rankedSelection(technologies, state.selectedId);
  if (!selected) return <div className="mock-banner mt-0">추천된 나눔기술이 없습니다. 보고서는 Report 탭에서 확인할 수 있습니다.</div>;

  const { linked, unresolved } = technologyRequirements(selected, gapItems);
  const evidence = evidenceItems.filter(item => selected.evidence_ids.includes(item.id));

  return <SplitExplorer name="technology" label="추천 나눔기술 목록" ordered={ordered} selected={selected} duplicates={duplicates} state={state} onChange={onChange}
    row={technology => <>
      {/* 목록에는 확인된 판정값(same·similar)만 표시한다. */}
      <span className="small text-secondary">추천 {technology.rank}순위{technology.match_level && Object.hasOwn(MATCH_LEVEL_LABELS, technology.match_level) ? ` · ${MATCH_LEVEL_LABELS[technology.match_level]}` : ''}</span>
      <strong className="small d-block">{technology.title}</strong>
    </>}
    eyebrow={<>추천 {selected.rank}순위 · {matchLevelLabel(selected.match_level)}</>} title={selected.title}>
    <p className="small text-secondary mb-0">문서 ID {selected.id}</p>
    <p className="small text-secondary">추천 순서는 보고서의 정렬 순서이며 적합도 점수가 아닙니다. 일치 수준은 기술 RAG의 매칭 판정이며 요구조건 충족을 뜻하지 않습니다.</p>

    <h4 className="evidence-label">제공기관</h4>
    <p className="small mb-0">{selected.provider ?? <span className="text-secondary">제공기관 정보 없음</span>}</p>

    <h4 className="evidence-label">기술이전 조건</h4>
    <p className="small mb-1">{selected.transfer_condition ?? <span className="text-secondary">기술이전 조건 정보 없음</span>}</p>
    <p className="small text-secondary mb-0">실제 기술이전 가능 여부와 세부 조건은 제공기관 확인이 필요합니다.</p>

    <h4 className="evidence-label">추천 이유 — AI 생성 설명</h4>
    {selected.rationale ? <>
      <p className="small mb-1">{selected.rationale}</p>
      <p className="small text-secondary mb-0">관련 인용은 확인되었으나, 설명 자체의 기술적 타당성을 최종 검증한 결과는 아닙니다.</p>
    </> : <p className="small text-secondary mb-0">{evidence.length ? '제공된 추천 설명이 없습니다. 연결된 원문 근거를 확인하세요.' : '제공된 추천 설명이 없습니다.'}</p>}

    <h4 className="evidence-label">연결된 RFP 요구 기술요소 <span className="text-secondary fw-normal">Gap 분석의 검증된 외부기술 매칭</span></h4>
    {linked.length ? <ul className="small mb-0">{linked.map(gap => <li key={gap.id}>{gap.requirement_name}</li>)}</ul>
      : <p className="small text-secondary mb-0">연결된 요구 기술요소 없음</p>}
    {unresolved > 0 && <p className="small text-secondary mt-1 mb-0">연결 정보를 찾을 수 없는 항목 {unresolved}개는 표시하지 않았습니다.</p>}

    <h4 className="evidence-label">검증된 근거</h4>
    {evidence.length ? <EvidenceExplorer key={selected.id} items={evidence} report={report} />
      : <p className="small text-secondary mb-0">연결된 검증 근거가 없습니다.</p>}
  </SplitExplorer>;
}
