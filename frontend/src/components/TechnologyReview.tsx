import { useState } from 'react';
import { Button, Form } from 'react-bootstrap';
import type { TechnologyInput } from '../types/technologyInput';
import type { TechnologyElement } from '../types/technologyElement';
import { isStaleExtraction } from '../lib/analysisRequest';

const categories = ['기술 대상', '입력 데이터', '기술 방법', '보유 기능', '목표 기능', '기대 효과', '미분류'] as const;

type Props = {
  input: TechnologyInput;
  elements: TechnologyElement[];
  onElementsChange: (elements: TechnologyElement[]) => void;
  onDone: () => void;
  doneLabel: string;
  doneBlocked?: string | null;
};

const roleLabels = { owned: '내가 가진 기술', goal: '추가로 필요한 기술', uncertain: '구분 확인 필요' };
const roleHints = {
  owned: '현재 직접 보유하거나 구현한 기술입니다.',
  goal: '앞으로 확보하거나 개발해야 하는 기술입니다.',
  uncertain: '어느 목록에 둘지 정한 뒤 내용을 확정할 수 있습니다.',
};

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
    <Form.Select aria-label="목록 선택" value={draft?.role} onChange={event => setDraft({ ...element, role: event.target.value as TechnologyElement['role'] })}><option value="owned">내가 가진 기술</option><option value="goal">추가로 필요한 기술</option><option value="uncertain">구분 확인 필요</option></Form.Select>
    <Form.Select aria-label="세부 분류" value={draft?.category} onChange={event => setDraft({ ...element, category: event.target.value as TechnologyElement['category'] })}>{categories.map(category => <option key={category}>{category}</option>)}</Form.Select>
    <div className="review-edit-actions"><Button size="sm" className="btn-accent" disabled={!draft?.name.trim()} onClick={save}>저장</Button><Button size="sm" variant="outline-secondary" onClick={() => setDraft(null)}>취소</Button>
      {!isNew && <Button size="sm" variant="outline-danger" onClick={() => { onElementsChange(elements.filter(item => item.id !== element.id)); setDraft(null); }}>삭제</Button>}</div>
  </div>;

  return <section className="app-card p-4" aria-labelledby="review-title">
    <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
      <div><h2 id="review-title" className="h6 mb-1">분석할 기술을 확인해 주세요</h2><p className="small text-secondary mb-0">두 목록만 확인하면 됩니다. AI가 정리한 내용도 확정 전까지 자유롭게 수정할 수 있습니다.</p></div>
    </div>
    <details className="review-source mt-3"><summary>입력한 원문 보기</summary><div className="small mt-3"><p><strong>보유 기술 설명</strong><br />{input.technology_description}</p><p><strong>해결하려는 기술 문제</strong><br />{input.target_problem}</p><p><strong>필요 기술</strong><br />{input.required_technology || '입력 없음'}</p>{input.original_query && <p><strong>원문 질문 · 분석 입력</strong><br />{input.original_query}</p>}<p className="mb-0"><strong>특허번호</strong><br />{input.patent_numbers?.join(', ') || '없음'}</p></div></details>
    {input.policy_question && <p className="small mt-3 mb-0"><strong>추출된 제도 질문</strong><br />{input.policy_question}<br /><span className="text-secondary">분석 요청에 보존됩니다. 현재 파이프라인은 법령 검색을 수행하지 않습니다.</span></p>}
    {elements.some(element => isStaleExtraction(element, input)) && <div className="mock-banner mt-3 mb-0" role="alert">입력이 AI 추출 이후 변경되었습니다. ‘이전 입력에서 추출’ 표시 요소는 현재 입력에서 검증되지 않았습니다. 입력 단계에서 다시 추출하거나 해당 요소를 삭제해 주세요.</div>}
    {elements.length === 0 && <p className="small text-secondary mt-3 mb-0">등록된 기술요소가 없습니다. 원문과 빈 A/B 목록을 그대로 전달합니다. 필요한 경우 직접 추가해 주세요.</p>}
    <div className="technology-lists">
    {roles.map(role => <section className={`review-group review-group-${role}`} key={role}>
      <div className="review-group-heading"><span className="review-role-mark" aria-hidden="true">{role === 'owned' ? 'A' : role === 'goal' ? 'B' : '?'}</span><div><h3 className="h6 mb-1">{roleLabels[role]}</h3><p className="small text-secondary mb-0">{roleHints[role]}</p></div></div>
      {elements.filter(element => element.role === role).length === 0 && <p className="small text-secondary mb-0">등록된 요소 없음</p>}
      {elements.filter(element => element.role === role).map(element => <article className="review-row" key={element.id}>
        <div className="review-row-main">
          <span className="review-name">{element.name}</span>
          {isStaleExtraction(element, input) && <span className="small text-danger">이전 입력에서 추출 · 현재 입력 미검증</span>}
          <Button className="review-edit-button" variant="link" size="sm" aria-label={`${element.name} 수정`} onClick={() => { setDraft({ ...element }); setIsNew(false); }}><i className="bi bi-pencil" aria-hidden="true" /></Button>
        </div>
        {draft?.id === element.id && !isNew && editor(draft)}
        <details className="review-metadata small text-secondary mt-2"><summary>세부 정보</summary><p className="mt-2 mb-1">분류: {element.category} · 출처: {element.source}</p>{element.evidence && <p className="mb-0">원문 근거: {element.evidence}</p>}</details>
      </article>)}
      {isNew && draft?.role === role && editor(draft)}
      <Button variant="outline-secondary" size="sm" className="mt-2" onClick={() => add(role)}><i className="bi bi-plus-lg me-1" aria-hidden="true" />기술 추가</Button>
    </section>)}
    </div>
    <div className="d-flex justify-content-between gap-2 flex-wrap mt-4">
      <Button className="btn-accent" disabled={!!draft || !!doneBlocked || elements.some(element => !element.name.trim())}
        onClick={onDone}>{doneLabel}</Button>
      {doneBlocked && <p className="small text-secondary mb-0 align-self-center">{doneBlocked}</p>}
    </div>
  </section>;
}
