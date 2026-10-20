import type { AnalysisReportRequest } from '../api';
import type { TechnologyElement } from '../types/technologyElement';
import type { TechnologyInput } from '../types/technologyInput';

// AI 추출에 쓰인 입력의 서명. 입력이 바뀌면 이전 추출 요소는 현재 입력에서 검증되지 않은 것으로 본다.
export function extractionSignature(input: TechnologyInput): string {
  return JSON.stringify([input.technology_description, input.required_technology ?? '', input.target_problem, input.original_query ?? '']
    .map(value => value.trim()));
}

export function isStaleExtraction(element: TechnologyElement, input: TechnologyInput): boolean {
  return element.extracted_from !== undefined && element.extracted_from !== extractionSignature(input);
}

// Keep the full question used at extraction time. The approved A/B names remain user editable.
export function analysisRequestFromInput(input: TechnologyInput, elements: TechnologyElement[]): AnalysisReportRequest {
  const original = input.original_query?.trim();
  const context = [
    `현재 보유한 기술: ${input.technology_description.trim()}`,
    ...(input.required_technology?.trim() ? [`보완·확보하고 싶은 기술: ${input.required_technology.trim()}`] : []),
    `해결하려는 문제: ${input.target_problem.trim()}`,
  ].join('\n');
  return {
    problem: original || context,
    owned_technologies: elements.filter(element => element.role === 'owned').map(element => element.name),
    unmet_elements: elements.filter(element => element.role === 'goal').map(element => element.name),
    policy_question: input.policy_question ?? null,
  };
}
