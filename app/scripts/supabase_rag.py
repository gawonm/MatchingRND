"""Apply schema, ingest once, and smoke-test retrieval without LLM calls."""
import argparse
import json
import time

from app.common.embedding import MODEL,get_embedder
from app.common.supabase_store import SupabaseRepository,corpus_fingerprint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('setup')
    sub.add_parser('status')
    ingest = sub.add_parser('ingest')
    ingest.add_argument('--modules',nargs='+',choices=['technology','ntis','rfp','policy','company'],default=['technology','ntis','rfp','policy','company'])
    ingest.add_argument('--force',action='store_true')
    search = sub.add_parser('search')
    search.add_argument('--module',choices=['technology','ntis','rfp','policy','company'],required=True)
    search.add_argument('--query',required=True)
    search.add_argument('--top-k',type=int,default=5)
    search.add_argument('--year',type=int)
    search.add_argument('--institution')
    args = parser.parse_args(argv)
    repo = SupabaseRepository()
    if args.command == 'setup':
        repo.apply_schema()
        print('Supabase rag 스키마·검색 함수·권한 적용 완료',flush=True)
        return 0
    if args.command == 'status':
        with repo.connection() as conn:
            rows = conn.execute("select p.corpus_id,p.embedding_model,p.embedding_profile,(select count(*) from rag.documents d where d.corpus_id=p.corpus_id),(select count(*) from rag.chunks c where c.corpus_id=p.corpus_id),(select count(*) from rag.embeddings e where e.corpus_id=p.corpus_id) from rag.corpora p order by p.corpus_id").fetchall()
            for corpus,model,profile,docs,chunks,vectors in rows:
                if chunks != vectors:
                    raise RuntimeError(f'{corpus}: 청크·벡터 개수가 다릅니다.')
                print(f'{corpus}: 문서 {docs}, 청크 {chunks}, 벡터 {vectors}, {model}, {profile}',flush=True)
        return 0
    if args.command == 'search':
        repo.corpus(args.module)
        filters = {k:v for k,v in {'year':args.year,'institution':args.institution}.items() if v is not None}
        rows = repo.search(args.module,get_embedder().encode_query(args.query),args.top_k,document_filters=filters)
        print(json.dumps(rows,ensure_ascii=False,indent=2))
        return 0
    from app.common.supabase_ingestion import build_snapshot
    for module in args.modules:
        started = time.perf_counter()
        print(f'[{module}] 원문 파싱·청킹 시작 ({MODEL})',flush=True)
        docs,chunks,payload = build_snapshot(module)
        fp = corpus_fingerprint(docs,chunks,payload)
        try:
            existing = repo.corpus(module)
        except RuntimeError:
            existing = None
        if existing and existing['fingerprint'] == fp and not args.force:
            print(f'[{module}] 변경 없음: 문서 {len(docs)}개, 청크 {len(chunks)}개',flush=True)
            continue
        embedder = get_embedder()
        print(f'[{module}] 장치: {embedder.model.device}, 청크 {len(chunks)}개',flush=True)
        vectors = []
        batch = embedder.config.batch_size
        for start in range(0,len(chunks),batch):
            texts = [c['content'] for c in chunks[start:start+batch]]
            if any(embedder.token_length(text)>embedder.max_seq_length for text in texts):
                raise ValueError(f'{module}: 모델 입력 한도를 초과하는 청크가 있습니다. 청킹을 수정하세요.')
            part,_ = embedder.encode(texts)
            vectors.extend(part)
            if start % (batch*10) == 0 or start+batch>=len(chunks):
                print(f'[{module}] 임베딩 {len(vectors)}/{len(chunks)}',flush=True)
                embedder.save_cache()
        print(f'[{module}] DB 적재 시작',flush=True)
        repo.replace(module,docs,chunks,vectors,payload,fp)
        print(f'[{module}] 완료: 문서 {len(docs)}, 청크 {len(chunks)}, {time.perf_counter()-started:.1f}초',flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
