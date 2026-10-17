import { useEffect, useRef, useState } from 'react';

const pages = ['home', 'workspace', 'discover', 'selection', 'simulation'];
export type Navigation = { page: string; sessionId: string; runId: string | null; mode: 'review' | 'demo' };

export function pageFromHash(hash: string): string {
  const page = hash.replace(/^#/, '');
  return pages.includes(page) ? page : 'home';
}

export function isNavigation(value: unknown): value is Navigation {
  if (!value || typeof value !== 'object') return false;
  const route = value as Partial<Navigation>;
  return typeof route.page === 'string' && pages.includes(route.page) && typeof route.sessionId === 'string'
    && (route.runId === null || typeof route.runId === 'string') && (route.mode === 'review' || route.mode === 'demo');
}

export function useNavigation(sessionId: string, runId: string | null) {
  const [route, setRoute] = useState<Navigation>(() => ({ page: pageFromHash(window.location.hash), sessionId, runId, mode: 'review' }));
  const initial = useRef(route);
  useEffect(() => {
    window.history.replaceState(initial.current, '', `#${initial.current.page}`);
    const restore = (event: PopStateEvent) => {
      if (isNavigation(event.state)) setRoute(event.state);
      else setRoute({ ...initial.current, page: pageFromHash(window.location.hash) });
    };
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  const navigate = (next: Navigation) => {
    if (JSON.stringify(next) === JSON.stringify(route)) return;
    window.history.pushState(next, '', `#${next.page}`);
    setRoute(next);
  };
  return { route, navigate };
}
