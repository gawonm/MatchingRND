"""Live read-only smoke check for all retrieval adapters; never calls an LLM."""
import json
import time
from datetime import datetime

from app.common.paths import PROJECT_ROOT
from app.common.supabase_store import SupabaseRepository
from app.common.supabase_retrieval import load_pdf_index, retrieve_ntis, DatabaseVectorStore


def main():
    repo = SupabaseRepository()
    query = '배가스 폐열 회수 열교환기 유기랭킨사이클 ORC 터빈'
    report = {}
    from app.technology_rag.config import load_config
    from app.technology_rag.pipeline import TechnologyRagPipeline
    cfg = load_config()
    cfg.index.backend = 'supabase'
    started = time.perf_counter()
    technology = TechnologyRagPipeline.from_config(cfg).search(query,top_docs=3)
    report['technology'] = technology.model_dump(mode='json')
    print(f'technology: 후보 {len(technology.candidates)}, {time.perf_counter()-started:.1f}초',flush=True)
    for module in ('rfp','policy'):
        started = time.perf_counter()
        index = load_pdf_index(module)
        if module == 'rfp':
            from app.rfp_rag.pipeline import search_module_result
            result = search_module_result(index,query,top_k=3)
        else:
            from app.policy_rag.pipeline import search_module_result
            result = search_module_result(index,'국가연구개발사업 참여 연구개발기관 기술이전',top_k=3)
        assert result.hits and result.candidates, module + ': 검색 결과가 없습니다.'
        assert all(e.page is None or e.page>=0 for c in result.candidates for e in c.evidences)
        report[module] = result.model_dump(mode='json')
        print(f'{module}: 후보 {len(result.candidates)}, {time.perf_counter()-started:.1f}초',flush=True)
    started = time.perf_counter()
    projects = retrieve_ntis({'search_query':query},3)
    assert projects and all(p['project_id'] and p['text'] for p in projects)
    report['ntis'] = projects
    print(f'ntis: 후보 {len(projects)}, {time.perf_counter()-started:.1f}초',flush=True)
    company = DatabaseVectorStore('company',repo).similarity_search(query,k=3)
    assert company
    report['company'] = [{'text':d.page_content,'metadata':d.metadata} for d in company]
    from app.common.embedding import get_embedder
    vector = get_embedder().encode_query(query)
    filtered = repo.search('technology',vector,50,document_filters={'year':2026})
    assert len(filtered)==50
    with repo.connection() as conn:
        years = conn.execute('select year from rag.documents where corpus_id=%s and document_id=any(%s)',('technology',[r['document_id'] for r in filtered])).fetchall()
        assert years and all(row[0]==2026 for row in years)
        assert not conn.execute('select has_schema_privilege(%s,%s,%s)',('anon','rag','USAGE')).fetchone()[0]
        diagnostics = repo.corpus('rfp')['payload']
        report['rfp_diagnostics'] = {key:diagnostics.get(key,[]) for key in ('failed_files','excluded_files','matching_issues')}
        print('연도 필터: 50개 모두 2026년 / 익명 접근: 차단',flush=True)
        print(f"RFP 실패 {len(diagnostics.get('failed_files',[]))}, 검토 제외 {len(diagnostics.get('excluded_files',[]))}",flush=True)
    output = PROJECT_ROOT/'outputs'/('supabase_retrieval_check_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json')
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('검색 점검 결과: '+str(output),flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
