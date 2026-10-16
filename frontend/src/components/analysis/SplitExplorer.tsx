import { useEffect, useRef, type ReactNode } from 'react';
import { Button } from 'react-bootstrap';

// 분석 요청 상태와 분리된 목록·상세 화면 상태. 새 분석 결과가 오면 Workspace가 초기화한다.
export type SplitViewState = { selectedId: string | null; mobileDetailOpen: boolean };

type Props<T extends { id: string }> = {
  name: string;
  label: string;
  ordered: T[];
  selected: T;
  duplicates: number;
  state: SplitViewState;
  onChange: (state: SplitViewState) => void;
  row: (item: T) => ReactNode;
  eyebrow: ReactNode;
  title: string;
  children: ReactNode;
};

const isMobile = () => window.matchMedia('(max-width: 767.98px)').matches;

// RFP·기술 탭 공통 목록 + 상세 레이아웃. 데스크톱은 2열, 모바일은 목록 → 전체 너비 상세 → 목록.
export default function SplitExplorer<T extends { id: string }>({ name, label, ordered, selected, duplicates, state, onChange, row, eyebrow, title, children }: Props<T>) {
  const heading = useRef<HTMLHeadingElement>(null);
  const rows = useRef(new Map<string, HTMLButtonElement>());
  const listScroll = useRef(0);
  const returnTo = useRef<string | null>(null);
  // 모바일: 상세가 열리면 제목으로, 목록으로 돌아오면 스크롤 위치와 선택 항목으로 포커스를 되돌린다.
  useEffect(() => {
    if (state.mobileDetailOpen) {
      heading.current?.focus({ preventScroll: true });
      heading.current?.closest('section')?.scrollIntoView({ block: 'start', behavior: 'instant' }); // 상단 '목록으로'까지 보이게
      return;
    }
    if (!returnTo.current) return;
    window.scrollTo({ top: listScroll.current, behavior: 'instant' }); // Bootstrap의 smooth scroll을 피한다
    rows.current.get(returnTo.current)?.focus({ preventScroll: true });
    returnTo.current = null;
  }, [state.mobileDetailOpen, selected.id]);

  const select = (id: string) => { listScroll.current = window.scrollY; onChange({ selectedId: id, mobileDetailOpen: isMobile() }); };
  const back = () => { returnTo.current = selected.id; onChange({ selectedId: selected.id, mobileDetailOpen: false }); };

  return <div className={`split-view${state.mobileDetailOpen ? ' detail-open' : ''}`}>
    <div className="split-list">
      <ul className="list-unstyled mb-0" aria-label={label}>
        {ordered.map(item => <li key={item.id}>
          <button type="button" className="evidence-row" aria-pressed={item.id === selected.id} aria-controls={`${name}-detail`}
            ref={element => { if (element) rows.current.set(item.id, element); else rows.current.delete(item.id); }}
            onClick={() => select(item.id)}>{row(item)}</button>
        </li>)}
      </ul>
      {duplicates > 0 && <p className="small text-secondary mt-2 mb-0">같은 ID로 중복된 후보 {duplicates}개는 표시하지 않았습니다.</p>}
    </div>
    <section id={`${name}-detail`} className="split-detail app-card" aria-labelledby={`${name}-detail-title`}>
      <Button className="split-back" size="sm" variant="outline-secondary" onClick={back}>← 목록으로</Button>
      <div className="eyebrow">{eyebrow}</div>
      <h3 id={`${name}-detail-title`} className="h6 mt-2" tabIndex={-1} ref={heading}>{title}</h3>
      {children}
    </section>
  </div>;
}
