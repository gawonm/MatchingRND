import type { AnalysisRun, AnalysisSession, ConfirmedProfile, DiscoverItem, DiscoverSource, ModuleSearch } from '../types/analysisSession';
import type { TechnologyInput } from '../types/technologyInput';

export const cloneInput = (value: TechnologyInput): TechnologyInput => ({ ...value, technology_domains: [...value.technology_domains], technology_tags: [...value.technology_tags], patent_numbers: [...(value.patent_numbers ?? [])] });

const emptySearch = (): ModuleSearch => ({ query: '', status: 'idle', resultKeys: [] });

export function createSession(projectId: string, id = crypto.randomUUID()): AnalysisSession {
  return {
    id, draftInput: { technology_domains: [], technology_tags: [], technology_description: '', target_problem: '' },
    draftElements: [], reviewSource: null, profiles: [], runs: [], activeRunId: null,
    demo: { projectId, compared: [], assumed: [], included: ['input', 'comparison', 'gaps', 'simulation', 'evidence'] },
  };
}

export function activeRun(session: AnalysisSession): AnalysisRun | null {
  return session.runs.find(run => run.id === session.activeRunId) ?? null;
}

export function runProfile(session: AnalysisSession, run: AnalysisRun | null): ConfirmedProfile | null {
  return run ? session.profiles.find(profile => profile.id === run.profileId && profile.version === run.profileVersion) ?? null : null;
}

function createMockRun(profile: ConfirmedProfile | null, id: string): AnalysisRun {
  return {
    id, profileId: profile?.id ?? null, profileVersion: profile?.version ?? null, mode: 'mock', activeSource: 'technology',
    searches: { technology: emptySearch(), ntis: emptySearch(), rfp: emptySearch() },
    items: [], selectedKeys: [], assumedKeys: [], reviewFocusKey: null,
  };
}

export function ensureMockRun(session: AnalysisSession, runId = crypto.randomUUID()): AnalysisSession {
  if (activeRun(session)) return session;
  return { ...session, runs: [...session.runs, createMockRun(null, runId)], activeRunId: runId };
}

export function hasUnconfirmedChanges(session: AnalysisSession): boolean {
  const latest = session.profiles.at(-1);
  return !!latest && JSON.stringify([cloneInput(session.draftInput), session.draftElements]) !== JSON.stringify([latest.input, latest.elements]);
}

export function isHistoricalRun(session: AnalysisSession, run: AnalysisRun | null): boolean {
  return !!run?.profileId && run.profileId !== session.profiles.at(-1)?.id;
}

export function toggleSelection(run: AnalysisRun, key: string): AnalysisRun {
  if (!run.items.some(item => item.key === key && item.mode === run.mode)) return run;
  const removing = run.selectedKeys.includes(key);
  return { ...run,
    selectedKeys: removing ? run.selectedKeys.filter(item => item !== key) : [...run.selectedKeys, key],
    assumedKeys: removing ? run.assumedKeys.filter(item => item !== key) : run.assumedKeys,
    reviewFocusKey: removing && run.reviewFocusKey === key ? null : run.reviewFocusKey,
  };
}

export function selectedItems(run: AnalysisRun | null): DiscoverItem[] {
  return run ? run.selectedKeys.flatMap(key => { const item = run.items.find(candidate => candidate.key === key); return item ? [item] : []; }) : [];
}

export function draftDiffers(session: AnalysisSession): boolean {
  const profile = runProfile(session, activeRun(session));
  return !!profile && JSON.stringify([cloneInput(session.draftInput), session.draftElements]) !== JSON.stringify([profile.input, profile.elements]);
}

export function confirmProfile(session: AnalysisSession, runId = crypto.randomUUID(), profileId = crypto.randomUUID()): AnalysisSession {
  if (!session.draftInput.technology_description.trim() || !session.draftInput.target_problem.trim()) return session;
  if (session.draftElements.some(element => !element.name.trim())) return session;
  const current = session.profiles.at(-1);
  if (current && !hasUnconfirmedChanges(session)) {
    const latestRun = [...session.runs].reverse().find(run => run.profileId === current.id);
    return latestRun && session.activeRunId !== latestRun.id ? { ...session, activeRunId: latestRun.id } : session;
  }
  const elements = session.draftElements.filter((element, index, all) => all.findIndex(other =>
    other.name.trim() === element.name.trim() && other.role === element.role && other.source === element.source && other.evidence === element.evidence) === index);
  const profile: ConfirmedProfile = {
    id: profileId, version: (session.profiles.at(-1)?.version ?? 0) + 1,
    input: cloneInput(session.draftInput), elements: elements.map(element => ({ ...element })),
  };
  const run = createMockRun(profile, runId);
  return { ...session, draftElements: elements, profiles: [...session.profiles, profile], runs: [...session.runs, run], activeRunId: run.id };
}

export function updateRun(session: AnalysisSession, runId: string, change: (run: AnalysisRun) => AnalysisRun): AnalysisSession {
  return { ...session, runs: session.runs.map(run => run.id === runId ? change(run) : run) };
}

export function selectionKey(mode: 'real', source: DiscoverSource, originalId: string, taskId?: string): string;
export function selectionKey(mode: 'mock', source: DiscoverSource, mockId: string): string;
export function selectionKey(mode: 'real' | 'mock', source: DiscoverSource, id: string, taskId?: string): string {
  if (!id.trim()) throw new Error('선택 항목의 원본 식별자가 필요합니다.');
  return [mode, source, id, ...(taskId ? [taskId] : [])].map(encodeURIComponent).join(':');
}
