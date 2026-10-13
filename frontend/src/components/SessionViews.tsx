import { Badge, Button, Form } from 'react-bootstrap';
import { selectedItems } from '../state/analysisSession';
import type { AnalysisRun, ConfirmedProfile, DiscoverItem } from '../types/analysisSession';

const sourceLabel = { technology: '외부 기술 / 특허', ntis: '선행 R&D', rfp: 'R&D 공고' };

function ItemIdentity({ item }: { item: DiscoverItem }) {
  return <span className="small text-secondary">{sourceLabel[item.source]} · {item.mode === 'mock' ? 'Mock 예시' : '실제 자료'} · 원본 ID {item.originalId || '제공되지 않음'}{item.source === 'rfp' && ` · task_id ${item.taskId || '제공되지 않음'}`}</span>;
}

export function SessionWorkspace({ profile, run, onFocus, onDiscover, onSimulation }: {
  profile: ConfirmedProfile; run: AnalysisRun; onFocus: (key: string) => void; onDiscover: () => void; onSimulation: () => void;
}) {
  const selected = selectedItems(run);
  const focused = selected.find(item => item.key === run.reviewFocusKey);
  return <section className="app-card p-4">
    <div className="eyebrow">USER REVIEW / {run.mode.toUpperCase()}</div><h2 className="h5 mt-2">선택 자료 검토</h2>
    <p className="small text-secondary">분석 실행 {run.id} · 프로필 {profile.id} / v{profile.version}</p>
    <p className="small">보유 기술: {profile.elements.filter(item => item.role === 'owned').map(item => item.name).join(', ') || '확정 요소 없음'}<br />목표 기술: {profile.elements.filter(item => item.role === 'goal').map(item => item.name).join(', ') || '확정 요소 없음'}</p>
    {selected.length === 0 ? <div className="mock-banner">선택한 검토 자료가 없습니다. Discover에서 자료를 선택할 수 있습니다.</div> : <div className="review-selected-grid"><div>{selected.map(item => <article className="selection-item" key={item.key}><div><strong className="small">{item.title}</strong><br /><ItemIdentity item={item} /></div><Button size="sm" variant="outline-secondary" onClick={() => onFocus(item.key)}>근거 검토</Button></article>)}</div><div className="app-card p-3">{focused ? <><h3 className="h6">{focused.title}</h3><ItemIdentity item={focused} />{focused.evidence.length ? focused.evidence.map(evidence => <blockquote className="evidence-block small mt-2" key={evidence.id}>{evidence.quote}<div className="text-secondary">{evidence.documentTitle} · 위치 미제공</div></blockquote>) : <p className="small text-secondary mt-3">연결된 근거가 없습니다.</p>}</> : <p className="small text-secondary mb-0">목록에서 자료의 근거를 선택해 확인하세요.</p>}</div></div>}
    <div className="mock-banner mt-3">선택 자료에 대한 Gap 분석은 연결되지 않았습니다. 검색 실패나 근거 부족을 미충족으로 판정하지 않습니다.</div>
    <div className="d-flex gap-2 flex-wrap"><Button variant="outline-secondary" onClick={onDiscover}>Discover로 돌아가기</Button><Button className="btn-accent" onClick={onSimulation}>도입 가정 검토</Button></div>
  </section>;
}

export function SessionSimulation({ profile, run, onAssumedChange, onReport }: {
  profile: ConfirmedProfile; run: AnalysisRun; onAssumedChange: (keys: string[]) => void; onReport: () => void;
}) {
  const candidates = selectedItems(run).filter(item => item.source === 'technology');
  return <section className="app-card p-4"><div className="eyebrow">SCENARIO / {run.mode.toUpperCase()}</div><h2 className="h5 mt-2">외부 기술 도입 가정</h2>
    <p className="small text-secondary">분석 실행 {run.id} · 프로필 v{profile.version}. 선택한 외부 기술만 표시합니다. 도입 가정은 보유 기술을 변경하지 않습니다.</p>
    {candidates.length === 0 && <p className="mock-banner">선택한 외부 기술이 없습니다. Discover에서 후보를 선택할 수 있습니다.</p>}
    {candidates.map(item => <article className="selection-item" key={item.key}><div><strong className="small">{item.title}</strong><br /><ItemIdentity item={item} /><p className="small text-secondary mt-2 mb-0">{item.summary}</p></div><Form.Check id={`assume-${item.key}`} label="도입 가정" checked={run.assumedKeys.includes(item.key)} onChange={() => onAssumedChange(run.assumedKeys.includes(item.key) ? run.assumedKeys.filter(key => key !== item.key) : [...run.assumedKeys, item.key])} /></article>)}
    <p className="small text-secondary mt-3">가정 선택은 실제 확보·기술이전 완료 또는 요구사항 충족을 뜻하지 않습니다.</p><Button className="btn-accent" onClick={onReport}>현재 검토 보고서 보기</Button>
  </section>;
}

export function SessionReport({ profile, run }: { profile: ConfirmedProfile; run: AnalysisRun }) {
  const selected = selectedItems(run);
  return <article className="report-paper"><div className="eyebrow">R&D MATCH / SESSION REVIEW</div><h2>기술 검토 보고서</h2>
    <p className="small text-secondary">분석 실행 {run.id} · 프로필 {profile.id} / v{profile.version} · {run.mode === 'mock' ? 'Mock 자료 포함' : '실제 API 결과'}</p>
    <h3>01. 확정 기술 프로필</h3><p><strong>보유 기술 원문</strong><br />{profile.input.technology_description}</p><p><strong>기술 문제 원문</strong><br />{profile.input.target_problem}</p><p><strong>특허번호</strong><br />{profile.input.patent_numbers?.join(', ') || '없음'}</p><p><strong>확정 기술요소</strong><br />{profile.elements.map(item => `${item.name} (${item.role === 'owned' ? '보유' : item.role === 'goal' ? '목표' : '구분 확인 필요'})`).join(', ') || '없음'}</p>
    <h3>02. Discover 선택 자료 · {selected.length}건</h3>{selected.length === 0 ? <p>선택 자료 없음</p> : selected.map(item => <div className="report-gap" key={item.key}><strong>{item.title}</strong><br /><ItemIdentity item={item} />{item.evidence.map(evidence => <blockquote className="evidence-block small mt-2" key={evidence.id}>{evidence.quote}<div>{evidence.documentTitle}</div></blockquote>)}</div>)}
    <h3>03. 도입 가정</h3>{run.assumedKeys.length === 0 ? <p>가정한 기술 없음</p> : selected.filter(item => run.assumedKeys.includes(item.key)).map(item => <p key={item.key}><Badge bg="light" text="dark">가정</Badge> {item.title}</p>)}
    <div className="mock-banner">이 실행의 Gap 분석 및 실제 적합성 판정은 연결되지 않았습니다. Mock 근거는 검증된 실제 자료가 아닙니다.</div>
  </article>;
}
