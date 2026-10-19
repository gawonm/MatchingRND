import type { AnalysisReport, ReportViewResponse } from './types/analysisReport';
import type { TechnologyElement } from './types/technologyElement';
import type { TechnologyInput } from './types/technologyInput';

const configuredBase = import.meta.env?.VITE_API_BASE_URL?.trim();

export const API_BASE_URL = (configuredBase || 'http://127.0.0.1:8000').replace(/\/$/, '');

export type HealthResponse = {
  status: 'ok';
  message: string;
};

export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/health`);
  if (!response.ok) throw new Error(`API 연결 실패: HTTP ${response.status}`);
  const health = await response.json() as HealthResponse;
  if (health.status !== 'ok') throw new Error('API 상태 응답이 올바르지 않습니다.');
  return health;
}

export type AnalysisReportRequest = {
  problem: string;
  owned_technologies: string[];
  unmet_elements: string[];
  policy_question?: string | null;
};

export async function createAnalysisReport(request: AnalysisReportRequest): Promise<AnalysisReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(`보고서 생성 실패: HTTP ${response.status}`);
  return response.json() as Promise<AnalysisReport>;
}

// POST /api/analysis/report-view: 한 번의 실행으로 FinalAnswer와 구조화 view를 함께 받는다.
export async function createAnalysisReportView(request: AnalysisReportRequest): Promise<ReportViewResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/report-view`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(`보고서 생성 실패: HTTP ${response.status}`);
  return response.json() as Promise<ReportViewResponse>;
}

type ExtractedTechnology ={ name: string; quote: string };
export type ExtractionResult = { elements: TechnologyElement[]; warnings: string[]; policy_question: string | null };

// POST /api/analysis/extract: LLM 후보 추출만 수행하며 서버에 승인 상태를 저장하지 않는다.
export async function extractTechnologyElements(input: TechnologyInput): Promise<ExtractionResult> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      owned_description: input.technology_description,
      required_description: input.required_technology?.trim() || null,
      problem: input.target_problem,
      ...(input.original_query?.trim() ? { original_query: input.original_query.trim() } : {}),
    }),
  });
  if (!response.ok) {
    const detail = await response.json().then(body => body?.detail?.message, () => null);
    throw new Error(typeof detail === 'string' ? detail : `기술요소 추출 실패: HTTP ${response.status}`);
  }
  const body = await response.json() as { owned: ExtractedTechnology[]; requested: ExtractedTechnology[]; warnings: string[]; policy_question?: string | null };
  const toElement = (role: 'owned' | 'goal') => (item: ExtractedTechnology, index: number): TechnologyElement =>
    ({ id: `ai-${role}-${index + 1}`, name: item.name, category: '미분류', role, evidence: item.quote, source: 'AI 추출' });
  return { elements: [...body.owned.map(toElement('owned')), ...body.requested.map(toElement('goal'))], warnings: body.warnings, policy_question: body.policy_question ?? null };
}
