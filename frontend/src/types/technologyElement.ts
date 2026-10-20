export type TechnologyElementCategory =
  | '기술 대상'
  | '입력 데이터'
  | '기술 방법'
  | '보유 기능'
  | '목표 기능'
  | '기대 효과'
  | '미분류';

export type TechnologyElement = {
  id: string;
  name: string;
  category: TechnologyElementCategory;
  role: 'owned' | 'goal' | 'uncertain';
  evidence: string;
  source: '보유 기술' | '기술 문제' | '사용자 추가' | 'AI 추출';
  // AI 추출 시점 입력의 서명(extractionSignature). 현재 입력과 다르면 현재 입력에서 검증되지 않은 요소다.
  extracted_from?: string;
};
