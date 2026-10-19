import type { AnalysisReportRequest } from '../api';
import type { TechnologyElement } from '../types/technologyElement';
import type { TechnologyInput } from '../types/technologyInput';

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
