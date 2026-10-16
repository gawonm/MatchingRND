
import type {
  DiscoverItem,
  DiscoverSource,
} from './types/analysisSession';
import { API_BASE_URL } from './api';

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
    `${API_BASE_URL}/api/discovery/search?${params}`
  );

  if (!response.ok) {
    throw new Error(
      `Discovery API 요청 실패: HTTP ${response.status}`
    );
  }

  return (await response.json()) as DiscoveryResponse;
}
