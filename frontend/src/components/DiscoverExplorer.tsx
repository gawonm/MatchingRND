import { useState } from 'react';
import { Badge, Button, Form, Nav, Offcanvas } from 'react-bootstrap';
import { mockDiscoverItems } from '../data/mockDiscover';
import { selectedItems } from '../state/analysisSession';
import type { AnalysisRun, ConfirmedProfile, DiscoverItem, DiscoverSource } from '../types/analysisSession';

const labels: Record<DiscoverSource, string> = { technology: '외부 기술 / 특허', ntis: '선행 R&D', rfp: 'R&D 공고' };
const sources: DiscoverSource[] = ['technology', 'ntis', 'rfp'];
export default function DiscoverExplorer({ profile, run, onRunChange, onHome, onWorkspace }: {
  profile: ConfirmedProfile;
  run: AnalysisRun;
  onRunChange: (change: (run: AnalysisRun) => AnalysisRun) => void;
  onHome: () => void;
  onWorkspace: () => void;
}) {
  const [source, setSource] = useState<DiscoverSource>('technology');
  const [detail, setDetail] = useState<DiscoverItem | null>(null);
  const state = run.searches[source];
  const shown = state.resultKeys.flatMap(key => { const item = run.items.find(candidate => candidate.key === key); return item ? [item] : []; });
  const activeSelection = selectedItems(run);
  const isSelected = (item: DiscoverItem) => run.selectedKeys.includes(item.key);
  const toggle = (item: DiscoverItem) => onRunChange(current => ({ ...current, selectedKeys: current.selectedKeys.includes(item.key)
    ? current.selectedKeys.filter(key => key !== item.key) : [...current.selectedKeys, item.key],
    assumedKeys: current.assumedKeys.filter(key => key !== item.key),
    reviewFocusKey: current.reviewFocusKey === item.key ? null : current.reviewFocusKey }));
  const searchMock = async (target: DiscoverSource) => {
    const query = run.searches[target].query.trim().toLocaleLowerCase();
    onRunChange(current => ({ ...current, searches: { ...current.searches, [target]: { ...current.searches[target], status: 'loading' } } }));
    try {
      await new Promise(resolve => window.setTimeout(resolve, 150));
      const results = mockDiscoverItems.filter(item => item.source === target &&
        `${item.title} ${item.evidence.map(evidence => evidence.quote).join(' ')}`.toLocaleLowerCase().includes(query));
      onRunChange(current => current.searches[target].query.trim().toLocaleLowerCase() !== query ? current : ({ ...current,
        items: [...current.items, ...results.filter(item => !current.items.some(saved => saved.key === item.key))],
        searches: { ...current.searches, [target]: { ...current.searches[target], resultKeys: results.map(item => item.key), status: results.length ? 'success' : 'empty' } },
      }));
    } catch {
      onRunChange(current => current.searches[target].query.trim().toLocaleLowerCase() !== query ? current : ({ ...current, searches: { ...current.searches, [target]: { ...current.searches[target], status: 'error', error: 'Mock 검색 실패' } } }));
    }
  };

  return <>
    <section className="app-card p-4 mb-4" aria-label="현재 기술 프로필">
      <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap"><div><div className="eyebrow">CURRENT TECHNOLOGY PROFILE</div><h2 className="h6 mt-2">현재 기술 프로필</h2></div><Button variant="outline-secondary" size="sm" onClick={onHome}>Home에서 수정</Button></div>
      <p className="small text-secondary">프로필 버전 {profile.version} · 분석 실행 {run.id} · {run.mode === 'mock' ? 'Mock 검색' : '실제 API 결과'}</p>
      <><p className="small mb-1"><strong>보유</strong> · {profile.elements.filter(item => item.role === 'owned').map(item => item.name).join(', ') || '확정 요소 없음'}</p>
        <p className="small mb-1"><strong>목표</strong> · {profile.elements.filter(item => item.role === 'goal').map(item => item.name).join(', ') || '확정 요소 없음'}</p>
        {profile.elements.some(item => item.role === 'uncertain') && <p className="small mb-1"><strong>구분 확인 필요</strong> · {profile.elements.filter(item => item.role === 'uncertain').map(item => item.name).join(', ')}</p>}
        <details className="small text-secondary mt-2"><summary>입력 원문 및 특허번호 보기</summary><p className="mt-2 mb-1">보유 기술: {profile.input.technology_description}</p><p className="mb-1">기술 문제: {profile.input.target_problem}</p><p className="mb-0">특허번호: {profile.input.patent_numbers?.join(', ') || '없음'}</p></details></>
      <p className="small text-secondary mt-3 mb-0">아래 결과는 입력 프로필로 검색한 자료가 아닌 고정 Mock입니다. 실제 RAG 검색 API는 연결되지 않았습니다.</p>
    </section>
    <div className="discover-layout"><section className="discover-results">
      <Nav variant="tabs" activeKey={source} onSelect={key => key && setSource(key as DiscoverSource)} aria-label="자료 출처 선택" className="mb-3">
        {sources.map(item => <Nav.Item key={item}><Nav.Link eventKey={item}>{labels[item]}</Nav.Link></Nav.Item>)}
      </Nav>
      <Form onSubmit={event => { event.preventDefault(); void searchMock(source); }} className="discover-search"><Form.Control aria-label={`${labels[source]} Mock 검색`} placeholder="Mock 자료에서 제목·근거 검색" value={state.query} onChange={event => onRunChange(current => ({ ...current, searches: { ...current.searches, [source]: { ...current.searches[source], query: event.target.value, status: 'idle' } } }))} /><Button className="btn-accent" type="submit" disabled={state.status === 'loading'}>Mock 탐색</Button></Form>
      <p className="small text-secondary mt-2">{labels[source]} · 고정 예시 자료 · 검색어는 이 탭에서만 적용됩니다.</p>
      <div aria-live="polite">{state.status === 'idle' && <div className="app-card p-4 text-secondary">Mock 탐색을 누르면 예시 결과를 볼 수 있습니다.</div>}
        {state.status === 'loading' && <div className="app-card p-4 text-secondary" role="status">검색 중…</div>}
        {state.status === 'empty' && <div className="app-card p-4 text-secondary">검색 결과 0건 · 다른 검색어를 입력해 주세요.</div>}
        {state.status === 'error' && <div className="app-card p-4" role="alert">Mock 자료를 불러오지 못했습니다. <Button variant="outline-secondary" size="sm" onClick={() => void searchMock(source)}>다시 시도</Button></div>}
        {state.status === 'success' && <><p className="small text-secondary">{shown.length}건의 Mock 결과</p><div className="discover-list">{shown.map(item => <article className="app-card discover-result" key={item.key}>
          <div className="d-flex justify-content-between align-items-start gap-2"><Badge bg="light" text="dark">{labels[item.source]} · Mock</Badge>{isSelected(item) && <Badge className="badge-accent">선택됨</Badge>}</div>
          <h2 className="h6 mt-3">{item.title}</h2><p className="small text-secondary">{item.summary}</p>
          <p className="small text-secondary mb-3">{item.source === 'technology' ? '외부 기술 보완 후보' : item.source === 'ntis' ? '선행연구 참고 자료' : '참여·요건 검토 대상'} · 원본 ID {item.originalId || 'Mock에 없음'}{item.source === 'rfp' && ` · task_id ${item.taskId || 'Mock에 없음'}`}</p>
          <div className="d-flex gap-2 flex-wrap"><Button size="sm" variant="outline-secondary" onClick={() => setDetail(item)}>상세보기</Button><Button size="sm" className={isSelected(item) ? 'btn-accent-outline' : 'btn-accent'} onClick={() => toggle(item)}>{isSelected(item) ? '선택 해제' : '선택에 추가'}</Button></div>
        </article>)}</div></>}
      </div>
    </section><aside className="app-card selection-panel" aria-label="선택 항목"><details open><summary className="selection-summary">선택 항목 · {activeSelection.length}건</summary><div className="selection-content"><h2 className="h6">선택 항목</h2><div className="selection-counts">{sources.map(item => <span key={item}>{labels[item]} <strong>{activeSelection.filter(saved => saved.source === item).length}</strong></span>)}</div>
      {activeSelection.length === 0 ? <p className="small text-secondary">자료를 선택하면 여기에 모입니다.</p> : activeSelection.map(item => <div className="selection-item" key={item.key}><span className="small"><strong>{labels[item.source]}</strong><br />{item.title}</span><Button size="sm" variant="outline-secondary" aria-label={`${item.title} 선택 해제`} onClick={() => toggle(item)}>해제</Button></div>)}
      <Button className="btn-accent w-100 mt-3" onClick={onWorkspace}>Workspace로 이동</Button><p className="small text-secondary mt-2 mb-0">선택 자료는 검토 목록에 전달됩니다. 선택만으로 권리나 적합성이 확정되지 않습니다.</p></div></details></aside></div>
    <Offcanvas show={!!detail} onHide={() => setDetail(null)} placement="end" aria-labelledby="discover-detail-title"><Offcanvas.Header closeButton><Offcanvas.Title id="discover-detail-title">{detail?.title}</Offcanvas.Title></Offcanvas.Header><Offcanvas.Body>{detail && <>
      <Badge bg="light" text="dark">{labels[detail.source]} · Mock</Badge><p className="small mt-3">원본 문서 ID: {detail.originalId || 'Mock에 없음'}{detail.source === 'rfp' && <> · task_id: {detail.taskId || 'Mock에 없음'}</>}</p>
      <h3 className="h6">핵심 요약</h3><p className="small">{detail.summary || '제공되지 않음'}</p><h3 className="h6">검색 근거</h3>{detail.evidence.map(evidence => <blockquote className="evidence-block small" key={evidence.id}>{evidence.quote}<div className="text-secondary mt-2">{evidence.documentTitle} · 원문 위치 미제공</div></blockquote>)}
      <p className="small text-secondary">제공기관·기간·상태·기술요소·원문 URL은 현재 Mock에 없습니다. 검색된 인용은 실제 원문 검증 결과가 아닙니다.</p><Button className="btn-accent" onClick={() => toggle(detail)}>{isSelected(detail) ? '선택 해제' : '선택에 추가'}</Button>
    </>}</Offcanvas.Body></Offcanvas>
  </>;
}
