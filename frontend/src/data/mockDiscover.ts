import { mockAnalysis } from './mockAnalysis';
import { selectionKey } from '../state/analysisSession';
import type { DiscoverItem, DiscoverSource } from '../types/analysisSession';
import type { Evidence } from '../types/analysis';

export const mockDiscoverItems: DiscoverItem[] = (['technology', 'ntis', 'rfp'] as DiscoverSource[]).flatMap(source => {
  const grouped = new Map<string, Evidence[]>();
  mockAnalysis.evidences.filter(evidence => evidence.source === source).forEach(evidence => {
    grouped.set(evidence.documentTitle, [...(grouped.get(evidence.documentTitle) ?? []), evidence]);
  });
  return [...grouped].map(([title, evidence]) => ({
    key: selectionKey('mock', source, evidence[0].id), mode: 'mock', source, title,
    summary: evidence[0].quote, evidence,
  }));
});
