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
