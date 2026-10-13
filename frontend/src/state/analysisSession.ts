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
  return session.profiles.find(profile => profile.id === run?.profileId && profile.version === run.profileVersion) ?? null;
}

export function selectedItems(run: AnalysisRun | null): DiscoverItem[] {
  return run ? run.selectedKeys.flatMap(key => { const item = run.items.find(candidate => candidate.key === key); return item ? [item] : []; }) : [];
}

export function draftDiffers(session: AnalysisSession): boolean {
  const profile = runProfile(session, activeRun(session));
  return !!profile && JSON.stringify([session.draftInput, session.draftElements]) !== JSON.stringify([profile.input, profile.elements]);
}

export function confirmProfile(session: AnalysisSession, runId = crypto.randomUUID(), profileId = crypto.randomUUID()): AnalysisSession {
  if (!session.draftInput.technology_description.trim() || !session.draftInput.target_problem.trim()) return session;
  if (session.draftElements.some(element => !element.name.trim())) return session;
  const current = runProfile(session, activeRun(session));
  if (current && !draftDiffers(session)) return session;
  const elements = session.draftElements.filter((element, index, all) => all.findIndex(other =>
    other.name.trim() === element.name.trim() && other.role === element.role && other.source === element.source && other.evidence === element.evidence) === index);
  const profile: ConfirmedProfile = {
    id: profileId, version: (session.profiles.at(-1)?.version ?? 0) + 1,
    input: cloneInput(session.draftInput), elements: elements.map(element => ({ ...element })),
  };
  const run: AnalysisRun = {
    id: runId, profileId: profile.id, profileVersion: profile.version, mode: 'mock',
    searches: { technology: emptySearch(), ntis: emptySearch(), rfp: emptySearch() },
    items: [], selectedKeys: [], assumedKeys: [], reviewFocusKey: null,
  };
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
