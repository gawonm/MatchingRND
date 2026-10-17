import { useState } from 'react';
import { Button, Form } from 'react-bootstrap';
import type { TechnologyInput } from '../types/technologyInput';
import type { TechnologyElement } from '../types/technologyElement';

const categories = ['기술 대상', '입력 데이터', '기술 방법', '보유 기능', '목표 기능', '기대 효과', '미분류'] as const;

type Props = {
  input: TechnologyInput;
  elements: TechnologyElement[];
  onElementsChange: (elements: TechnologyElement[]) => void;
  onDone: () => void;
  doneLabel: string;
  doneBlocked?: string | null;
};

const roleLabels = { owned: '현재 보유 기술', goal: '확보·개발 목표 기술', uncertain: '구분 확인 필요' };

export default function TechnologyReview({ input, elements, onElementsChange, onDone, doneLabel, doneBlocked = null }: Props) {
  const [draft, setDraft] = useState<TechnologyElement | null>(null);
  const [isNew, setIsNew] = useState(false);
  const roles: TechnologyElement['role'][] = ['owned', 'goal'];
  if (elements.some(element => element.role === 'uncertain') || draft?.role === 'uncertain') roles.push('uncertain');
  const add = (role: TechnologyElement['role']) => {
    setDraft({ id: crypto.randomUUID(), name: '', category: '미분류', role, evidence: '', source: '사용자 추가' });
    setIsNew(true);
  };
  const save = () => {
    if (!draft?.name.trim()) return;
    const saved = { ...draft, name: draft.name.trim() };
    onElementsChange(isNew ? [...elements, saved] : elements.map(element => element.id === saved.id ? saved : element));
    setDraft(null);
  };
  const editor = (element: TechnologyElement) => <div className="review-edit" key={`edit-${element.id}`}>
    <Form.Control autoFocus aria-label="기술명 수정" placeholder="예: 진동 데이터 기반 이상 탐지" value={draft?.name ?? ''} onChange={event => setDraft({ ...element, name: event.target.value })} onKeyDown={event => { if (event.key === 'Enter') save(); if (event.key === 'Escape') setDraft(null); }} />
    <Form.Select aria-label="기술요소 역할" value={draft?.role} onChange={event => setDraft({ ...element, role: event.target.value as TechnologyElement['role'] })}><option value="owned">현재 보유</option><option value="goal">확보·개발 목표</option><option value="uncertain">구분 확인 필요</option></Form.Select>
    <Form.Select aria-label="기술요소 유형" value={draft?.category} onChange={event => setDraft({ ...element, category: event.target.value as TechnologyElement['category'] })}>{categories.map(category => <option key={category}>{category}</option>)}</Form.Select>
    <div className="review-edit-actions"><Button size="sm" className="btn-accent" disabled={!draft?.name.trim()} onClick={save}>저장</Button><Button size="sm" variant="outline-secondary" onClick={() => setDraft(null)}>취소</Button>
      {!isNew && <Button size="sm" variant="outline-danger" onClick={() => { onElementsChange(elements.filter(item => item.id !== element.id)); setDraft(null); }}>삭제</Button>}</div>
  </div>;

  return <section className="app-card p-4" aria-labelledby="review-title">
    <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
      <div><h3 id="review-title" className="h6 mb-1">기술요소 검토 · 수정</h3><p className="small text-secondary mb-0">AI 추출 요소는 후보입니다. 역할(보유 A / 필요 B)을 확인하고 수정·추가·삭제해 주세요.</p></div>
    </div>
    <details className="review-source mt-3"><summary>입력한 원문 보기</summary><div className="small mt-3"><p><strong>보유 기술 설명</strong><br />{input.technology_description}</p><p><strong>해결하려는 기술 문제</strong><br />{input.target_problem}</p><p><strong>필요 기술</strong><br />{input.required_technology || '입력 없음'}</p><p className="mb-0"><strong>특허번호</strong><br />{input.patent_numbers?.join(', ') || '없음'}</p></div></details>
    {elements.length === 0 && <p className="small text-secondary mt-3 mb-0">아직 등록된 기술요소가 없습니다. 보유 기술을 1개 이상 추가해 주세요.</p>}
    {roles.map(role => <section className="review-group" key={role}>
      <h3 className="h6">{roleLabels[role]}</h3>
      {elements.filter(element => element.role === role).length === 0 && <p className="small text-secondary mb-0">등록된 요소 없음</p>}
      {elements.filter(element => element.role === role).map(element => <article className="review-row" key={element.id}>
        <div className="review-row-main">
          <span className="review-name">{element.name}</span>
          <span className="small text-secondary">{element.category === '미분류' ? element.source : `${element.category} · ${element.source}`}</span>
          <Button className="review-edit-button" variant="link" size="sm" aria-label={`${element.name} 수정`} onClick={() => { setDraft({ ...element }); setIsNew(false); }}><i className="bi bi-pencil" aria-hidden="true" /></Button>
        </div>
        {draft?.id === element.id && !isNew && editor(draft)}
        {element.evidence && <details className="small text-secondary mt-2"><summary>원문 근거 보기 · {element.source}</summary><p className="mt-2 mb-0">{element.evidence}</p></details>}
      </article>)}
      {isNew && draft?.role === role && editor(draft)}
      <Button variant="outline-secondary" size="sm" className="mt-2" onClick={() => add(role)}><i className="bi bi-plus-lg me-1" aria-hidden="true" />기술 추가</Button>
    </section>)}
    <div className="d-flex justify-content-between gap-2 flex-wrap mt-4">
      <Button className="btn-accent" disabled={!!draft || !!doneBlocked || elements.some(element => !element.name.trim())}
        onClick={onDone}>{doneLabel}</Button>
      {doneBlocked && <p className="small text-secondary mb-0 align-self-center">{doneBlocked}</p>}
    </div>
  </section>;
}
