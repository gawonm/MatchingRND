import type { TechnologyInput } from '../types/technologyInput';
import type { TechnologyElement } from '../types/technologyElement';

// No extraction API is connected; sentences are source references, not extracted technology names.
export function mockExtractTechnologyElements(input: TechnologyInput): TechnologyElement[] {
  return [
    ...sentences(input.technology_description, 'owned', '보유 기술'),
    ...sentences(input.target_problem, 'goal', '기술 문제'),
  ];
}

function sentences(text: string, role: TechnologyElement['role'], source: TechnologyElement['source']): TechnologyElement[] {
  return (text.match(/[^.!?。！？\n]+[.!?。！？]?/gu) ?? [])
    .map(sentence => sentence.trim())
    .filter(Boolean)
    .filter((sentence, index, all) => all.indexOf(sentence) === index)
    .map((sentence, index) => ({
      id: `${role}-${index + 1}`,
      name: '',
      category: '미분류',
      role,
      evidence: sentence,
      source,
    }));
}
