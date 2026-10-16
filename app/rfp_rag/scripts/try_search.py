"""Interactive RFP-only search against the real index.

Run: python -m app.rfp_rag.scripts.try_search
No Technology/NTIS retrieval, Gap analysis, or answer generation is run.
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.rfp_rag.config import PROJECT_ROOT
from app.rfp_rag.retrieval.query import build_query


def read_question(args):
    owned = args.owned or input('보유기술 (여러 개는 ; 로 구분): ').split(';')
    requested = args.requested or input('요청 보완기술 (여러 개는 ; 로 구분): ').split(';')
    problem = args.problem if args.problem is not None else input('해결하려는 기술문제: ')
    owned = [name.strip() for name in owned if name.strip()]
    requested = [name.strip() for name in requested if name.strip()]
    if not owned or not requested:
        raise ValueError('보유기술과 요청 보완기술을 각각 하나 이상 입력하세요.')
    return build_query(owned, problem, unmet_elements=requested, return_details=True)


def load_index(backend):
    if backend == 'supabase':
        from app.common.supabase_retrieval import load_pdf_index

        return load_pdf_index('rfp')
    from app.common.paths import RFP_PDF_DIR, RFP_NOTICE_PATH
    from app.rfp_rag.pipeline import build_index

    return build_index(data_dir=RFP_PDF_DIR, output_dir=PROJECT_ROOT / 'db/rfp',
                       notice_path=RFP_NOTICE_PATH)


def progress_llm(verbose=False):
    from app.gap_analysis import OpenAIStructuredLLM

    client = OpenAIStructuredLLM(model=os.getenv('RFP_RELEVANCE_MODEL', 'gpt-4o-mini'),
                               cache_dir=PROJECT_ROOT / 'storage/llm_cache/rfp_relevance')
    calls = 0

    def judge(messages, response_model):
        nonlocal calls
        calls += 1
        if verbose:
            payload = json.loads(messages[-1]['content'])
            batch_count = len(payload.get('jobs', []))
            if batch_count:
                payload = payload['jobs'][0]['input']
            name = payload['technologies'][0]['name']
            suffix = f' (후보 {batch_count}개)' if batch_count else ''
            print(f'  LLM 원문 비교 {calls}: {name}{suffix}', flush=True)
        return client(messages, response_model)

    judge.usage = client.usage
    return judge


def show_result(result):
    checks = result['diagnostics']['technology_relevance']['checks']
    usage = result['diagnostics']['technology_relevance'].get('llm_usage', {})
    print(f"관련성 검증 API 호출 {usage.get('api_calls', 0)}회 / 캐시 재사용 {usage.get('cache_hits', 0)}회")
    rejected = sum(not check['accepted'] for check in checks.values())
    print(f"\nRFP 과제 후보 {len(result['hits'])}건 / 관련성 검토 {len(checks)}건 / 제외 {rejected}건")
    if not result['hits']:
        print(result['message'])
        print('이번 검색 후보 중 두 기술의 관련 근거가 모두 확인된 공고가 없습니다.')
        return
    for hit in result['hits']:
        print(f"\n[{hit['rank']}] {hit['title']}")
        print(f"  과제 ID: {hit['task_id']}")
        print(f"  원문 파일: {hit['filename']}")
        links = list(dict.fromkeys(url for source in result['sources']
                                  if source['task_id'] == hit['task_id']
                                  for url in source.get('notice_urls', [])))
        for url in links:
            print(f'  공고 URL: {url}')
        for match in (hit.get('technology_relevance') or {}).get('matches', []):
            label = {'same': '동일', 'similar': '유사', 'different': '다름',
                     'insufficient': '근거부족'}[match['relation']]
            print(f"  기술: {match['technology']} → {label}")
            print(f"    LLM 판단: {match['reason']}")
            if match['quote']:
                section = match['section'] or {}
                print(f"    원문 근거 ({section.get('item')}, {section.get('page')}쪽): {match['quote']}")
                print(f"    원문 인용 검증: {match['verified']}")
    print('\n전체 요구사항·성능지표·근거·제외 사유는 저장된 JSON에서 확인할 수 있습니다.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='직접 입력으로 실제 RFP 검색과 LLM 관련성 검증을 테스트합니다.')
    parser.add_argument('--backend', choices=['local', 'supabase'], help='생략하면 RAG_BACKEND 또는 local')
    parser.add_argument('--owned', action='append', help='보유기술. 여러 개면 옵션을 반복합니다.')
    parser.add_argument('--requested', action='append', help='요청 보완기술. 여러 개면 옵션을 반복합니다.')
    parser.add_argument('--problem', help='기술문제')
    parser.add_argument('--top-k', type=int, default=3, help='통과 과제 최대 개수 (기본 3)')
    parser.add_argument('--verbose', action='store_true', help='기술별 LLM 비교 진행 로그 표시')
    parser.add_argument('--output-dir', type=Path, default=PROJECT_ROOT / 'tmp/rfp-user-tests')
    args = parser.parse_args(argv)
    if args.top_k < 1:
        parser.error('--top-k는 1 이상이어야 합니다.')
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / '.env')
    backend = args.backend or os.getenv('RAG_BACKEND', 'local')
    if backend not in {'local', 'supabase'}:
        parser.error('RAG_BACKEND는 local 또는 supabase여야 합니다.')
    interactive = not any((args.owned, args.requested, args.problem))
    print('RFP 단독 테스트: 실제 공고 검색 → 기술별 LLM 비교 → 원문 인용 검증')
    print('OpenAI API를 사용합니다. Tech·NTIS 검색이나 Gap·최종답변 생성은 실행하지 않습니다.')
    index = None
    while True:
        try:
            details = read_question(args)
        except ValueError as exc:
            print(f'입력 오류: {exc}')
            if interactive:
                continue
            return 1
        if index is None:
            print(f'\nRFP 인덱스 준비 중 ({backend}). 첫 실행은 시간이 걸릴 수 있습니다.', flush=True)
            index = load_index(backend)
        print('\n검색 및 LLM 관련성 검증 중...', flush=True)
        from app.rfp_rag.pipeline import search

        result = search(index, details, top_k=args.top_k, relevance_llm=progress_llm(verbose=args.verbose))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M%S_%f')
        output = args.output_dir / f'rfp_search_{stamp}.json'
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        show_result(result)
        print(f'\n결과 파일: {output.resolve()}')
        if not interactive or input('\n다른 입력으로 테스트하려면 y, 종료하려면 Enter: ').strip().lower() != 'y':
            return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\n테스트를 종료합니다.')
