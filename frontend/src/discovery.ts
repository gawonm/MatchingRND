
import type {
  DiscoverItem,
  DiscoverSource,
} from './types/analysisSession';
import { API_BASE_URL } from './api.ts';

export type DiscoveryResponse = {
  items: DiscoverItem[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
  status: 'success' | 'empty';
};

export class DiscoveryRequestTracker {
  private sequence: Record<DiscoverSource, number> = { technology: 0, ntis: 0, rfp: 0 };
  private pending = new Set<string>();

  start(source: DiscoverSource, query: string, page: number): number | null {
    const key = `${source}:${query}:${page}`;
    if (this.pending.has(key)) return null;
    this.pending.add(key);
    return ++this.sequence[source];
  }

  finish(source: DiscoverSource, query: string, page: number, requestId: number): boolean {
    this.pending.delete(`${source}:${query}:${page}`);
    return this.sequence[source] === requestId;
  }
}

export function mergeDiscoveryItems(current: DiscoverItem[], incoming: DiscoverItem[]): DiscoverItem[] {
  const byKey = new Map(current.map(item => [item.key, item]));
  incoming.forEach(item => byKey.set(item.key, item));
  return [...byKey.values()];
}

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
