import type { AnalysisReport, EvidenceItem, GapItem, GapLabel, ReportViewResponse, RFPCandidate, SourceType, TechnologyCandidate } from '../types/analysisReport';
import { safeLink } from './reportMarkdown.ts';

export const SOURCE_LABELS: Record<SourceType, string> = {
  pub: '공공 나눔기술', pos: '포스코 나눔기술', ntis: 'NTIS 선행 과제', rfp: 'RFP 원문',
  policy: '법령 문서 (참고 · 적합성 판단 아님)', company: '사용자 입력 보유기술',
};

// 팀 정책: 모든 분석에 적용되는 일반 확인사항. 법령 검색·법적 판단 결과가 아니다.
// 문구는 app/answer_format.py의 COMMON_RND_INTRO·COMMON_RND_NOTICES(보고서 섹션 6)와 같아야 한다.
export const COMMON_RND_NOTICE_TITLE = '공통 R&D 유의사항';
export const COMMON_RND_INTRO = [
  '국가 R&D 과제 참여와 나눔기술 도입 시 일반적으로 확인할 사항입니다.',
  '이번 검색 결과나 원문 근거에 기반한 판단이 아니므로, 공고문과 관련 법령 원문으로 확인하세요.',
] as const;
export const COMMON_RND_NOTICES = [
  '국가 R&D 과제 참여 시 국가연구개발혁신법 적용 여부 확인',
  '연구개발비 사용 및 정산 기준 확인',
  '연구개발성과의 소유·활용 조건 확인',
  '나눔기술 도입 시 기술이전 조건 및 지식재산권 확인',
] as const;

export type ViewAvailability = 'ok' | 'empty' | 'failed' | 'mismatch';

// 같은 응답의 FinalAnswer.evidence에 없는 근거가 있으면(다른 실행 혼입) 구조화 탐색을 닫는다.
// 개별 claim 연결 오류는 claimsForEvidence가 해당 연결만 버린다.
export function viewAvailability(response: ReportViewResponse): ViewAvailability {
  if (response.view_status !== 'ok' || !response.view) return 'failed';
  const known = new Set(response.report.evidence.map(record => record.evidence_id));
  const items = response.view.evidence_items;
  if (items.some(item => !known.has(item.id))) return 'mismatch';
  return items.length ? 'ok' : 'empty';
}

function validClaim(report: AnalysisReport, index: number, evidenceId: string): boolean {
  const claim = report.claims[index];
  return Number.isInteger(index) && !!claim?.accepted && claim.citations.some(citation => citation.ok && citation.evidence_id === evidenceId);
}

// accepted claim 중 이 근거를 유효하게 인용한 문장만 반환한다. 연결이 맞지 않으면 아무것도 만들지 않는다.
export function claimsForEvidence(report: AnalysisReport, item: EvidenceItem): { index: number; text: string; section: string }[] {
  return item.claim_indices.filter(index => validClaim(report, index, item.id))
    .map(index => ({ index, text: report.claims[index].draft.text, section: report.claims[index].draft.section }));
}

// 실제 http(s) 링크만 남긴다. 앵커·javascript: 등은 버린다.
export function httpLinks(urls: string[]): string[] {
  return urls.flatMap(url => { const href = safeLink(url); return href && !href.startsWith('#') ? [href] : []; });
}

// 분석 수행 여부만 뜻한다. 기술 충족이나 지원 가능을 뜻하지 않는다.
export const GAP_STATUS_LABELS: Record<RFPCandidate['gap_analysis_status'], string> = {
  analyzed: 'Gap 분석 완료', not_analyzed: 'Gap 미분석', unknown: '분석 여부 확인 불가',
};

// gap_item_ids는 GapItem.id(gap-N)다. 이 RFP를 범위로 가진 GapItem만 연결하고, 못 찾은 ID는 개수만 센다.
export function rfpRequirements(rfp: RFPCandidate, gapItems: GapItem[]): { linked: GapItem[]; unresolved: number } {
  if (rfp.gap_analysis_status !== 'analyzed') return { linked: [], unresolved: 0 };
  const ids = [...new Set(rfp.gap_item_ids)];
  const linked = ids.flatMap(id => gapItems.find(gap => gap.id === id && gap.rfp_ids.includes(rfp.id)) ?? []);
  return { linked, unresolved: ids.length - linked.length };
}

// 추천 순서대로 정렬하고, 선택 ID가 이 결과에 없으면 첫 후보(후보가 없으면 null)로 전환한다.
// 같은 ID가 반복되는 비정상 입력은 첫 후보만 남겨 다른 후보의 상세·근거가 섞이지 않게 한다.
export function rankedSelection<T extends { id: string; rank: number }>(items: T[], selectedId: string | null): { ordered: T[]; selected: T | null; duplicates: number } {
  const sorted = [...items].sort((a, b) => a.rank - b.rank);
  const ordered = sorted.filter((item, i) => sorted.findIndex(other => other.id === item.id) === i);
  return { ordered, selected: ordered.find(item => item.id === selectedId) ?? ordered[0] ?? null, duplicates: sorted.length - ordered.length };
}

// 기술 RAG 매칭 판정(app/technology_rag: same | similar). 그 밖의 값은 일치·유사로 바꾸지 않는다.
export const MATCH_LEVEL_LABELS: Record<string, string> = { same: '기술요소 일치', similar: '기술요소 유사' };
export function matchLevelLabel(level: string | null): string {
  if (level === null) return '판정 정보 미제공';
  return Object.hasOwn(MATCH_LEVEL_LABELS, level) ? MATCH_LEVEL_LABELS[level] : `확인되지 않은 판정값 (${level})`;
}

// 기술의 gap_item_ids도 GapItem.id다. 그 GapItem이 이 기술을 검증된 외부 매칭(technology_ids)으로 가진 경우만 연결한다.
export function technologyRequirements(technology: TechnologyCandidate, gapItems: GapItem[]): { linked: GapItem[]; unresolved: number } {
  const ids = [...new Set(technology.gap_item_ids)];
  const linked = ids.flatMap(id => gapItems.find(gap => gap.id === id && gap.technology_ids.includes(technology.id)) ?? []);
  return { linked, unresolved: ids.length - linked.length };
}

// Gap 5분류(app/gap_analysis GapLabel). 알 수 없는 값은 5분류로 바꾸지 않는다.
export const GAP_LABELS: Record<GapLabel, string> = {
  기존보유: '기존보유', 외부기술보완: '외부기술보완', 부분충족: '부분충족', '추가R&D검토후보': '추가 R&D 검토 후보', 근거부족: '근거부족',
};
export function gapLabelText(label: string): string {
  return Object.hasOwn(GAP_LABELS, label) ? GAP_LABELS[label as GapLabel] : `판정 확인 불가 (${label})`;
}

// 선택한 RFP와 양방향으로 연결된 Gap 항목을 gap_index 순으로 정렬하고 선택을 정한다. 같은 id가 반복되면 첫 항목만 쓴다(rfpRequirements).
export function gapSelection(rfp: RFPCandidate, gapItems: GapItem[], selectedId: string | null): { ordered: GapItem[]; selected: GapItem | null; duplicates: number; unresolved: number } {
  const { linked, unresolved } = rfpRequirements(rfp, gapItems);
  const ordered = [...linked].sort((a, b) => a.gap_index - b.gap_index);
  const duplicates = ordered.reduce((count, gap) => count + gapItems.filter(other => other.id === gap.id).length - 1, 0);
  return { ordered, selected: ordered.find(gap => gap.id === selectedId) ?? ordered[0] ?? null, duplicates, unresolved };
}

// 이 Gap 행(section=gap, 같은 gap_index)에 대한 accepted claim 중 이 응답의 근거를 유효하게 인용한 것만 검증된 설명으로 쓴다.
export function gapClaims(report: AnalysisReport, gap: GapItem): string[] {
  const known = new Set(report.evidence.map(record => record.evidence_id));
  return [...new Set(gap.claim_indices)].flatMap(index => {
    const claim = report.claims[index];
    const valid = Number.isInteger(index) && !!claim?.accepted && claim.draft.section === 'gap' && claim.draft.gap_index === gap.gap_index
      && claim.citations.some(citation => citation.ok && known.has(citation.evidence_id));
    return valid ? [claim.draft.text] : [];
  });
}

// 같은 Gap 행의 생성된 설명이 최종 검토에서 반려됐는지 표시한다. 라벨 자체는 바꾸지 않는다.
export function rejectedGapClaimReasons(report: AnalysisReport, gap: GapItem): string[] {
  return [...new Set(report.claims.flatMap(claim => !claim.accepted && claim.draft.section === 'gap'
    && claim.draft.gap_index === gap.gap_index ? [claim.reason] : []))];
}

// GapItem.technology_ids ↔ TechnologyCandidate.gap_item_ids 양쪽이 확인된 후보만 연결한다.
export function gapTechnologies(gap: GapItem, technologies: TechnologyCandidate[]): { linked: TechnologyCandidate[]; unresolved: number } {
  const ids = [...new Set(gap.technology_ids)];
  const linked = ids.flatMap(id => technologies.find(t => t.id === id && t.gap_item_ids.includes(gap.id)) ?? []);
  return { linked, unresolved: ids.length - linked.length };
}

// overview.primary_*_id가 가리키는 후보만 쓴다. 없거나 일치하지 않으면 다른 후보로 대체하지 않는다.
export function primaryCandidate<T extends { id: string; rank: number }>(items: T[], id: string | null): T | 'empty' | 'missing' {
  if (!items.length) return 'empty';
  return rankedSelection(items, null).ordered.find(item => item.id === id) ?? 'missing';
}
