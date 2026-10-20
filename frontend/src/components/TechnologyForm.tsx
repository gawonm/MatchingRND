import { useState } from 'react';
import { Button, Form } from 'react-bootstrap';
import type { TechnologyInput } from '../types/technologyInput';

type TechnologyFormProps = {
  value: TechnologyInput;
  onChange: (input: TechnologyInput) => void;
  onReview: (input: TechnologyInput, mode: 'extract' | 'manual') => void;
  disabled?: boolean;
  submitLabel: string;
  manualLabel?: string;
};

export default function TechnologyForm({ value, onChange, onReview, disabled = false, submitLabel, manualLabel }: TechnologyFormProps) {
  const [errors, setErrors] = useState<{ owned?: string; problem?: string }>({});

  const submit = (mode: 'extract' | 'manual') => {
    if (disabled) return;
    const input = { ...value, technology_description: value.technology_description.trim(), target_problem: value.target_problem.trim(), required_technology: value.required_technology?.trim() ?? '' };
    const nextErrors = {
      owned: input.original_query?.trim() || input.technology_description ? undefined : '보유 기술 또는 원문 질문을 입력해 주세요.',
      problem: input.original_query?.trim() || input.target_problem ? undefined : '해결하려는 기술 문제 또는 원문 질문을 입력해 주세요.',
    };
    setErrors(nextErrors);
    if (nextErrors.owned || nextErrors.problem) return;
    onReview(input, mode);
  };

  return <Form onSubmit={event => { event.preventDefault(); submit('extract'); }} noValidate>
    <Form.Group controlId="owned-technology" className="mb-3">
      <Form.Label>보유 기술 <span className="text-secondary fw-normal">원문 질문이 없으면 필수</span></Form.Label>
      <Form.Control as="textarea" rows={3} placeholder="예: 산업용 모터 진동 데이터를 활용한 머신러닝 기반 이상 탐지 기술을 보유하고 있습니다."
        value={value.technology_description}
        onChange={e => { onChange({ ...value, technology_description: e.target.value, policy_question: null }); setErrors(current => ({ ...current, owned: undefined })); }} isInvalid={!!errors.owned} required />
      {errors.owned && <Form.Control.Feedback type="invalid" className="d-block">{errors.owned}</Form.Control.Feedback>}
    </Form.Group>
    <Form.Group controlId="required-technology" className="mb-3">
      <Form.Label>필요 기술 <span className="text-secondary fw-normal">선택</span></Form.Label>
      <Form.Control as="textarea" rows={2} placeholder="예: 잔존수명 예측 기술을 보완하거나 확보하고 싶습니다."
        value={value.required_technology ?? ''} onChange={e => onChange({ ...value, required_technology: e.target.value, policy_question: null })} />
    </Form.Group>
    <Form.Group controlId="technical-problem" className="mb-3">
      <Form.Label>해결하려는 기술 문제 <span className="text-secondary fw-normal">원문 질문이 없으면 필수</span></Form.Label>
      <Form.Control as="textarea" rows={3} placeholder="예: 설비 고장 시점을 사전에 예측하고 유지보수 비용을 줄이고 싶습니다."
        value={value.target_problem} onChange={e => { onChange({ ...value, target_problem: e.target.value, policy_question: null }); setErrors(current => ({ ...current, problem: undefined })); }} isInvalid={!!errors.problem} required />
      {errors.problem && <Form.Control.Feedback type="invalid" className="d-block">{errors.problem}</Form.Control.Feedback>}
    </Form.Group>
    <Form.Group controlId="original-query" className="mb-3">
      <Form.Label>원문 질문 <span className="text-secondary fw-normal">선택</span></Form.Label>
      <Form.Control as="textarea" rows={3} placeholder="원래 작성한 질문 전체가 있다면 그대로 붙여 넣으세요. 분석에도 이 원문을 사용합니다."
        value={value.original_query ?? ''} onChange={e => onChange({ ...value, original_query: e.target.value, policy_question: null })} />
    </Form.Group>
    <div className="home-cta">
      <Button type="submit" className="analyze-button" disabled={disabled}>{submitLabel}</Button>
      {manualLabel && <Button type="button" variant="outline-secondary" disabled={disabled} onClick={() => submit('manual')}>{manualLabel}</Button>}
    </div>
  </Form>;
}
