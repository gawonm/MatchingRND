import { Nav } from 'react-bootstrap';
const pages = [['home', 'house', 'Home', '새 분석 시작'], ['workspace', 'layout-split', 'Workspace', '입력·승인·분석·결과'], ['discover', 'compass', 'Discover', 'Mock 자료 탐색']];
// Discover 하위 화면(선택 자료 검토·도입 가정)은 Discover 메뉴로 표시한다.
const parent: Record<string, string> = { selection: 'discover', simulation: 'discover' };
export default function Sidebar({ activePage, onNavigate }: { activePage: string; onNavigate: (page: string) => void }) {
  return <aside className="sidebar"><div className="brand"><span className="brand-icon"><i className="bi bi-intersect" /></span>R&D Match<span className="brand-dot">.</span></div><p className="sidebar-caption">TECHNOLOGY TO OPPORTUNITY</p><div className="nav-caption">워크스페이스</div><Nav className="flex-column gap-2" aria-label="주요 화면">{pages.map(([id, icon, name, label]) => <Nav.Link as="button" key={id} active={(parent[activePage] ?? activePage) === id} aria-current={(parent[activePage] ?? activePage) === id ? 'page' : undefined} onClick={() => onNavigate(id)}><i className={`bi bi-${icon}`} /><span>{name}<small>{label}</small></span></Nav.Link>)}</Nav><div className="sidebar-note"><i className="bi bi-flask" /><strong>데이터 구분</strong><p>Workspace 분석은 실제 RAG API를 호출합니다.</p><span>Discover는 Mock 데이터</span></div></aside>;
}
