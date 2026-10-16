import type { AnalysisReport, EvidenceItem, ReportViewResponse, SourceType } from '../types/analysisReport';

export const SOURCE_LABELS: Record<SourceType, string> = {
  pub: '공공 나눔기술', pos: '포스코 나눔기술', ntis: 'NTIS 선행 과제', rfp: 'RFP 원문',
  policy: '법령 문서 (참고 · 적합성 판단 아님)', company: '사용자 입력 보유기술',
};

// 팀 정책: 모든 분석에 적용되는 일반 확인사항. 법령 검색·법적 판단 결과가 아니다.
export const COMMON_RND_NOTICE_TITLE = '공통 R&D 유의사항';
export const COMMON_RND_NOTICES = [
  '국가 R&D 과제 참여 시 국가연구개발혁신법 적용 여부 확인',
  '연구개발비 사용 및 정산 기준 확인',
  '연구개발성과의 소유·활용 조건 확인',
  '나눔기술 도입 시 기술이전 조건 및 지식재산권 확인',
] as const;

// 보고서가 이미 같은 안내를 출력하면 UI는 중복 삽입하지 않는다.
export function reportHasCommonNotice(markdown: string): boolean {
  return markdown.includes(COMMON_RND_NOTICE_TITLE);
}

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
