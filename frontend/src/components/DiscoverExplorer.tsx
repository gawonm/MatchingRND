import { useRef, useState } from 'react';
import { Badge, Button, Form, Nav, Offcanvas } from 'react-bootstrap';
import { searchDiscovery, DiscoveryRequestTracker, mergeDiscoveryItems } from '../discovery';
import { mockDiscoverItems } from '../data/mockDiscover';
import { selectedItems, toggleSelection } from '../state/analysisSession';
import type { AnalysisRun, ConfirmedProfile, DiscoverItem, DiscoverSource } from '../types/analysisSession';

const labels: Record<DiscoverSource, string> = { technology: '나눔 기술 / 특허', ntis: '선행 R&D', rfp: 'R&D 공고' };
const sources: DiscoverSource[] = ['technology', 'ntis', 'rfp'];
const modeLabel = (mode: DiscoverItem['mode']) => mode === 'real' ? '실제 검색' : 'Demo';
const sourceFileName = (path: string) => path.split(/[\\/]/).at(-1);

export default function DiscoverExplorer({ profile, historical, run, onRunChange, onHome, onWorkspace }: {
  profile: ConfirmedProfile | null;
  historical: boolean;
  run: AnalysisRun;
  onRunChange: (change: (run: AnalysisRun) => AnalysisRun) => void;
  onHome: () => void;
  onWorkspace: () => void;
}) {
  const source = run.activeSource;
  const [detail, setDetail] = useState<DiscoverItem | null>(null);
  const requests = useRef(new DiscoveryRequestTracker());
  const state = run.searches[source];
  const shown = state.resultKeys.flatMap(key => {
    const item = run.items.find(candidate => candidate.key === key && candidate.mode === run.mode);
    return item ? [item] : [];
  });
  const activeSelection = selectedItems(run);
  const isSelected = (item: DiscoverItem) => run.selectedKeys.includes(item.key);
  const toggle = (item: DiscoverItem) => onRunChange(current => toggleSelection(current, item.key));

  const search = async (target: DiscoverSource, page = 1) => {
    const query = run.searches[target].query.trim();
    if (!query) return;
    const requestId = requests.current.start(target, query, page);
    if (requestId === null) return;

    onRunChange(current => ({
      ...current,
      searches: {
        ...current.searches,
        [target]: {
          ...current.searches[target],
          status: page === 1 ? 'loading' : current.searches[target].status,
          loadingMore: page > 1,
          error: undefined,
        },
      },
    }));

    try {
      const response = run.mode === 'mock'
        ? {
            items: mockDiscoverItems.filter(item => item.source === target &&
              `${item.title} ${item.evidence.map(evidence => evidence.quote).join(' ')}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())),
            page: 1, has_next: false,
          }
        : await searchDiscovery(target, query, page);
      if (!requests.current.finish(target, query, page, requestId)) return;

      onRunChange(current => {
        if (current.searches[target].query.trim() !== query || current.mode !== run.mode) return current;
        const incoming = response.items.filter(item => item.mode === current.mode && item.source === target);
        const resultKeys = page === 1
          ? incoming.map(item => item.key)
          : [...new Set([...current.searches[target].resultKeys, ...incoming.map(item => item.key)])];
        return {
          ...current,
          items: mergeDiscoveryItems(current.items.filter(item => item.mode === current.mode), incoming),
          searches: {
            ...current.searches,
            [target]: {
              ...current.searches[target], resultKeys,
              status: resultKeys.length ? 'success' : 'empty',
              page: response.page, hasNext: response.has_next,
              loadingMore: false, error: undefined,
            },
          },
        };
      });
    } catch {
      if (!requests.current.finish(target, query, page, requestId)) return;
      onRunChange(current => current.searches[target].query.trim() !== query ? current : ({
        ...current,
        searches: {
          ...current.searches,
          [target]: {
            ...current.searches[target], status: 'error', loadingMore: false,
            error: '검색 자료를 불러오지 못했습니다. DB 연결 상태를 확인한 뒤 다시 시도해 주세요.',
          },
        },
      }));
    }
  };

  return <>
    <section className="app-card p-4 mb-4" aria-label="현재 기술 프로필">
      <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap"><div><div className="eyebrow">{run.mode === 'real' ? 'DISCOVER' : 'DEMO EXPLORER'}</div><h2 className="h6 mt-2">{profile ? historical ? '이전 실행의 확정 프로필' : '이 실행의 확정 프로필' : '프로필 없는 Demo 자료 탐색'}</h2></div><Button variant="outline-secondary" size="sm" onClick={onHome}>{profile ? '현재 프로필 편집' : 'Home에서 프로필 작성'}</Button></div>
      {profile ? <><p className="small text-secondary">프로필 버전 {profile.version} · 입력 기술 문제: {profile.input.target_problem}</p>
        <p className="small mb-1"><strong>보유</strong> · {profile.elements.filter(item => item.role === 'owned').map(item => item.name).join(', ') || '확정 요소 없음'}</p>
        <p className="small mb-1"><strong>목표</strong> · {profile.elements.filter(item => item.role === 'goal').map(item => item.name).join(', ') || '확정 요소 없음'}</p>
        {profile.elements.some(item => item.role === 'uncertain') && <p className="small mb-1"><strong>구분 확인 필요</strong> · {profile.elements.filter(item => item.role === 'uncertain').map(item => item.name).join(', ')}</p>}
        <details className="small text-secondary mt-2"><summary>입력 원문 및 특허번호 보기</summary><p className="mt-2 mb-1">보유 기술: {profile.input.technology_description}</p><p className="mb-1">기술 문제: {profile.input.target_problem}</p><p className="mb-0">특허번호: {profile.input.patent_numbers?.join(', ') || '없음'}</p></details></> : <p className="small text-secondary mt-3">프로필 없이 명시적인 Demo 자료를 탐색하고 선택할 수 있습니다.</p>}
      <p className="small text-secondary mt-3 mb-0">{run.mode === 'real' ? '실제 저장 자료를 검색합니다. 검색만으로 분석이나 Gap 판정을 시작하지 않습니다.' : '고정 Demo 자료입니다. 실제 검색 결과와 혼합되지 않습니다.'}</p>
      <details className="small text-secondary mt-2"><summary>실행 정보</summary>{modeLabel(run.mode)} 실행 ID: {run.id}</details>
    </section>
    <div className="discover-layout"><section className="discover-results">
      <Nav variant="tabs" activeKey={source} onSelect={key => key && onRunChange(current => ({ ...current, activeSource: key as DiscoverSource }))} aria-label="자료 출처 선택" className="mb-3">
        {sources.map(item => <Nav.Item key={item}><Nav.Link eventKey={item}>{labels[item]}</Nav.Link></Nav.Item>)}
      </Nav>
      <Form onSubmit={event => { event.preventDefault(); void search(source); }} className="discover-search"><Form.Control aria-label={`${labels[source]} 검색`} placeholder="제목과 원문에서 검색" value={state.query} onChange={event => onRunChange(current => ({ ...current, searches: { ...current.searches, [source]: { ...current.searches[source], query: event.target.value, status: 'idle', page: 0, hasNext: false, error: undefined } } }))} /><Button className="btn-accent" type="submit" disabled={state.status === 'loading' || !state.query.trim()}>검색</Button></Form>
      <p className="small text-secondary mt-2">{labels[source]} · {modeLabel(run.mode)} · 검색어는 현재 출처에만 적용됩니다.</p>
      <div aria-live="polite">
        {state.status === 'idle' && <div className="app-card p-4 text-secondary">검색어를 입력하고 검색을 실행해 주세요.</div>}
        {state.status === 'loading' && <div className="app-card p-4 text-secondary" role="status">검색 중…</div>}
        {state.status === 'empty' && <div className="app-card p-4 text-secondary">검색 결과가 없습니다. 다른 검색어를 입력해 주세요.</div>}
        {state.status === 'error' && <div className="app-card p-4" role="alert">{state.error} <Button variant="outline-secondary" size="sm" onClick={() => void search(source)}>다시 시도</Button></div>}
        {state.status === 'success' && <><p className="small text-secondary">{shown.length}건의 검색 결과</p><div className="discover-list">{shown.map(item => <article className="app-card discover-result" key={item.key}>
          <div className="d-flex justify-content-between align-items-start gap-2"><Badge bg="light" text="dark">{labels[item.source]} · {modeLabel(item.mode)}</Badge>{isSelected(item) && <Badge className="badge-accent">선택됨</Badge>}</div>
          <h2 className="h6 mt-3">{item.title}</h2>
          {(item.provider || item.year) && <p className="small text-secondary mb-1">{[item.provider, item.year].filter(Boolean).join(' · ')}</p>}
          <p className="small">{item.summary}</p>
          <p className="small text-secondary mb-3">문서 ID {item.originalId || '미제공'}{item.source === 'rfp' && ` · task_id ${item.taskId || '미제공'}`}</p>
          <div className="d-flex gap-2 flex-wrap"><Button size="sm" variant="outline-secondary" onClick={() => setDetail(item)}>상세보기</Button><Button size="sm" className={isSelected(item) ? 'btn-accent-outline' : 'btn-accent'} onClick={() => toggle(item)}>{isSelected(item) ? '선택 해제' : '선택에 추가'}</Button></div>
        </article>)}</div>
          {state.hasNext && <Button className="mt-3" variant="outline-secondary" disabled={state.loadingMore} onClick={() => void search(source, (state.page || 1) + 1)}>{state.loadingMore ? '불러오는 중…' : '더 보기'}</Button>}
        </>}
      </div>
    </section><aside className="app-card selection-panel" aria-label="선택 항목"><details open><summary className="selection-summary">선택 항목 · {activeSelection.length}건</summary><div className="selection-content"><h2 className="h6">선택 항목</h2><div className="selection-counts">{sources.map(item => <span key={item}>{labels[item]} <strong>{activeSelection.filter(saved => saved.source === item).length}</strong></span>)}</div>
      {activeSelection.length === 0 ? <p className="small text-secondary">자료를 선택하면 여기에 모입니다.</p> : activeSelection.map(item => <div className="selection-item" key={item.key}><span className="small"><strong>{labels[item.source]}</strong><br />{item.title}</span><Button size="sm" variant="outline-secondary" aria-label={`${item.title} 선택 해제`} onClick={() => toggle(item)}>해제</Button></div>)}
      <Button className="btn-accent w-100 mt-3" onClick={onWorkspace}>Selection으로 이동</Button><p className="small text-secondary mt-2 mb-0">선택 자료는 검색 목록과 별도로 이 실행에 유지됩니다.</p></div></details></aside></div>
    <Offcanvas show={!!detail} onHide={() => setDetail(null)} placement="end" aria-labelledby="discover-detail-title"><Offcanvas.Header closeButton><Offcanvas.Title id="discover-detail-title">{detail?.title}</Offcanvas.Title></Offcanvas.Header><Offcanvas.Body>{detail && <>
      <Badge bg="light" text="dark">{labels[detail.source]} · {modeLabel(detail.mode)}</Badge>
      {(detail.provider || detail.year) && <p className="small mt-3 mb-1">{[detail.provider, detail.year].filter(Boolean).join(' · ')}</p>}
      <p className="small">문서 ID: {detail.originalId || '미제공'}{detail.source === 'rfp' && <> · task_id: {detail.taskId || '미제공'}</>}</p>
      <h3 className="h6">핵심 요약</h3><p className="small">{detail.summary || '제공되지 않음'}</p>
      <h3 className="h6">검색 근거</h3>{detail.evidence.map(evidence => <blockquote className="evidence-block small" key={evidence.id}>{evidence.quote}<div className="text-secondary mt-2">{evidence.documentTitle}{evidence.section && ` · ${evidence.section}`}{evidence.page != null && ` · 저장된 페이지 값 ${evidence.page}${evidence.pageEnd != null && evidence.pageEnd !== evidence.page ? `–${evidence.pageEnd}` : ''}`}</div>{evidence.sourcePath && <div className="text-secondary mt-1">출처 파일: {sourceFileName(evidence.sourcePath)}</div>}</blockquote>)}
      <p className="small text-secondary">출처 파일명은 저장 위치 정보이며 공개 URL로 변환하지 않습니다.</p><Button className="btn-accent" onClick={() => toggle(detail)}>{isSelected(detail) ? '선택 해제' : '선택에 추가'}</Button>
    </>}</Offcanvas.Body></Offcanvas>
  </>;
}
