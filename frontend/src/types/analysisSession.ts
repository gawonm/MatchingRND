import type { Evidence } from './analysis';
import type { TechnologyElement } from './technologyElement';
import type { TechnologyInput } from './technologyInput';

export type DiscoverSource = 'technology' | 'ntis' | 'rfp';
export type DataMode = 'mock' | 'real';

export type DiscoverItem = {
  key: string;
  mode: DataMode;
  source: DiscoverSource;
  title: string;
  originalId?: string;
  taskId?: string;
  summary?: string;
  provider?: string;
  year?: number;
  evidence: Evidence[];
};

export type ModuleSearch = {
  query: string;
  status: 'idle' | 'loading' | 'success' | 'empty' | 'error';
  resultKeys: string[];
  page: number;
  hasNext: boolean;
  loadingMore?: boolean;
  error?: string;
};

export type ConfirmedProfile = {
  id: string;
  version: number;
  input: TechnologyInput;
  elements: TechnologyElement[];
};

export type AnalysisRun = {
  id: string;
  profileId: string | null;
  profileVersion: number | null;
  mode: DataMode;
  activeSource: DiscoverSource;
  searches: Record<DiscoverSource, ModuleSearch>;
  items: DiscoverItem[];
  selectedKeys: string[];
  assumedKeys: string[];
  reviewFocusKey: string | null;
};

export type AnalysisSession = {
  id: string;
  draftInput: TechnologyInput;
  draftElements: TechnologyElement[];
  workspaceReferences: DiscoverItem[];
  reviewSource: TechnologyInput | null;
  profiles: ConfirmedProfile[];
  runs: AnalysisRun[];
  activeRunId: string | null;
  demo: { projectId: string; compared: string[]; assumed: string[]; included: string[] };
};

