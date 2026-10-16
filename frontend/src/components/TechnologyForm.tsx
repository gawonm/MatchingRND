import { useState } from 'react';
import { Button, Form } from 'react-bootstrap';
import type { TechnologyInput } from '../types/technologyInput';

type TechnologyFormProps = {
  value: TechnologyInput;
  onChange: (input: TechnologyInput) => void;
  onReview: (input: TechnologyInput) => void;
  disabled?: boolean;
};

export default function TechnologyForm({ value, onChange, onReview, disabled = false }: TechnologyFormProps) {
  const [errors, setErrors] = useState<{ owned?: string; problem?: string }>({});
  const [patentDraft, setPatentDraft] = useState('');

  const handleSubmit = (event: React.SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (disabled) return;
    const input = { ...value, technology_description: value.technology_description.trim(), target_problem: value.target_problem.trim() };
    const nextErrors = {
      owned: input.technology_description ? undefined : '보유 기술을 입력해 주세요.',
      problem: input.target_problem ? undefined : '해결하려는 기술 문제를 입력해 주세요.',
    };
    setErrors(nextErrors);
    if (nextErrors.owned || nextErrors.problem) return;
    onReview(input);
  };

  return <Form onSubmit={handleSubmit} noValidate>
    <Form.Group controlId="owned-technology" className="mb-3">
      <Form.Label>보유 기술 설명</Form.Label>
      <Form.Control as="textarea" rows={3} placeholder="예: 산업용 모터 진동 데이터를 활용한 머신러닝 기반 이상 탐지 기술을 보유하고 있습니다."
        value={value.technology_description}
        onChange={e => { onChange({ ...value, technology_description: e.target.value }); setErrors(current => ({ ...current, owned: undefined })); }} isInvalid={!!errors.owned} required />
      {errors.owned && <Form.Control.Feedback type="invalid" className="d-block">{errors.owned}</Form.Control.Feedback>}
    </Form.Group>
    <Form.Group controlId="technical-problem" className="mb-3">
      <Form.Label>해결하려는 기술 문제</Form.Label>
      <Form.Control as="textarea" rows={3} placeholder="예: 설비 고장 시점을 사전에 예측하고 유지보수 비용을 줄이고 싶습니다."
        value={value.target_problem} onChange={e => { onChange({ ...value, target_problem: e.target.value }); setErrors(current => ({ ...current, problem: undefined })); }} isInvalid={!!errors.problem} required />
      {errors.problem && <Form.Control.Feedback type="invalid" className="d-block">{errors.problem}</Form.Control.Feedback>}
    </Form.Group>
    <Form.Group controlId="patent-number" className="mb-3">
      <Form.Label>보유 특허정보 <span className="text-secondary fw-normal">선택</span></Form.Label>
      <div className="patent-row">
        <Form.Control value={patentDraft} onChange={e => setPatentDraft(e.target.value)}
          placeholder="특허번호 입력" aria-label="특허번호 입력" />
        <Button type="button" variant="outline-secondary" className="patent-add" disabled={!patentDraft.trim()} onClick={() => {
          const number = patentDraft.trim();
          if (number && !(value.patent_numbers ?? []).includes(number)) onChange({ ...value, patent_numbers: [...(value.patent_numbers ?? []), number] });
          setPatentDraft('');
        }}>추가</Button>
      </div>
      {!!value.patent_numbers?.length && <ul className="list-unstyled d-flex flex-wrap gap-2 mt-2 mb-0">
        {value.patent_numbers.map(number => <li className="technology-tag" key={number}>{number}
          <button type="button" aria-label={`특허번호 ${number} 삭제`} onClick={() => onChange({ ...value, patent_numbers: value.patent_numbers?.filter(item => item !== number) })}>
            <i className="bi bi-x" aria-hidden="true" />
          </button>
        </li>)}
      </ul>}
      <Form.Text>번호를 저장하며, 특허 조회는 아직 연결되어 있지 않습니다.</Form.Text>
    </Form.Group>
    <div className="home-cta">
      <Button type="submit" className="analyze-button" disabled={disabled}>프로필 저장 후 Mock 자료 탐색</Button>
    </div>
  </Form>;
}
