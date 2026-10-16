
import type {
  DiscoverItem,
  DiscoverSource,
} from '../types/analysisSession';

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ??
  'http://127.0.0.1:8000';

export type DiscoveryResponse = {
  items: DiscoverItem[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
};

export async function searchDiscovery(
  source: DiscoverSource,
  query: string,
  page = 1,
  pageSize = 20,
): Promise<DiscoveryResponse> {
  const params = new URLSearchParams({
    source,
    q: query,
    page: String(page),
    page_size: String(pageSize),
  });

  const response = await fetch(
    `${API_BASE}/api/discovery/search?${params}`
  );

  if (!response.ok) {
    throw new Error(
      `Discovery API 요청 실패: HTTP ${response.status}`
    );
  }

  return (await response.json()) as DiscoveryResponse;
}
