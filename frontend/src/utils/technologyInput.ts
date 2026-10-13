import { TECHNOLOGY_DOMAINS } from '../data/technologyOptions.ts';
import type { TechnologyInput } from '../types/technologyInput.ts';

export function toggleTechnologyTag(input: TechnologyInput, tag: string): TechnologyInput {
  if (!TECHNOLOGY_DOMAINS.some(domain => domain.technologies.some(item => item === tag))) return input;
  const technology_tags = input.technology_tags.includes(tag)
    ? input.technology_tags.filter(item => item !== tag)
    : [...input.technology_tags, tag];
  return {
    ...input,
    technology_tags,
    technology_domains: TECHNOLOGY_DOMAINS
      .filter(domain => domain.technologies.some(item => technology_tags.includes(item)))
      .map(domain => domain.name),
  };
}
