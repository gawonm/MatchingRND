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
  source: '보유 기술' | '기술 문제' | '사용자 추가';
};
