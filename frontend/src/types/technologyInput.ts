export type TechnologyInput = {
  technology_domains: string[];
  technology_tags: string[];
  technology_description: string;
  target_problem: string;
  original_query?: string;
  policy_question?: string | null;
  required_technology?: string;
  patent_numbers?: string[];
};
