import type { AnalysisReport } from '../types/analysisReport';

export type ReportEntry = {
  requestId: number;
  status: 'loading' | 'idle' | 'error';
  result: AnalysisReport | null;
};

export type ReportEntries = Record<string, ReportEntry>;

export function startReport(entries: ReportEntries, key: string, requestId: number): ReportEntries {
  return { ...entries, [key]: { requestId, status: 'loading', result: entries[key]?.result ?? null } };
}

export function finishReport(
  entries: ReportEntries,
  key: string,
  requestId: number,
  result: AnalysisReport | null,
): ReportEntries {
  if (entries[key]?.requestId !== requestId) return entries;
  return { ...entries, [key]: { requestId, status: result ? 'idle' : 'error', result: result ?? entries[key].result } };
}
