"""Database-backed retrieval adapters preserving the existing RAG contracts."""
from functools import lru_cache
import re

from app.common.embedding import get_embedder
from app.common.supabase_store import SupabaseRepository
from app.common.supabase_ingestion import unpack


def flat_filter(where):
    if not where:
        return {}
    if '$and' in where:
        result = {}
        for condition in where['$and']:
            for key,value in flat_filter(condition).items():
                if key in result and result[key] != value:
                    raise ValueError('상충하는 검색 필터입니다.')
                result[key] = value
        return result
    if any(key.startswith('$') or isinstance(value,(dict,list)) for key,value in where.items()):
        raise ValueError('Supabase 검색은 동등 조건과 $and 필터를 지원합니다.')
    return dict(where)


class DatabaseDenseRetriever:
    def __init__(self, store, k):
        self.store, self.k = store,k

    def invoke(self, query):
        return self.store.similarity_search(query,k=self.k)


class DatabaseVectorStore:
    def __init__(self, corpus_id, repository=None):
        self.corpus_id = corpus_id
        self.repository = repository or SupabaseRepository()
        self.repository.corpus(corpus_id)

    def similarity_search_with_score(self, query, k=30, filter=None):
        from langchain_core.documents import Document
        rows = self.repository.search(self.corpus_id,get_embedder().encode_query(query),k,flat_filter(filter))
        return [(Document(page_content=r['content'],metadata=r['metadata']),1-r['similarity']) for r in rows]

    def similarity_search(self, query, k=30, filter=None):
        return [d for d,_ in self.similarity_search_with_score(query,k,filter)]

    def as_retriever(self, search_kwargs):
        return DatabaseDenseRetriever(self,search_kwargs['k'])


def load_pdf_index(module, repository=None):
    from langchain_core.documents import Document
    from langchain_community.retrievers import BM25Retriever
    from kiwipiepy import Kiwi
    repo = repository or SupabaseRepository()
    _,chunks,payload = repo.snapshot(module)
    docs = [Document(page_content=c['content'], metadata=c['metadata']) for c in chunks]
    kiwi = Kiwi()
    def tokenize(text):
        text = re.sub('[—–−]', '-', text.lower())
        words = [t.form for t in kiwi.tokenize(text)]
        if module == 'rfp':
            return words + re.findall(r'[a-z0-9가-힣]+(?:[-+&./][a-z0-9가-힣]+)*', text)
        return words + re.findall(r'제\d+조(?:의\d+)?|[a-z][a-z0-9-]*', text)
    bm25 = BM25Retriever.from_documents(docs,preprocess_func=tokenize)
    bm25.k = min(payload['KEYWORD_K'],len(docs))
    store = DatabaseVectorStore(module,repo)
    embedder = get_embedder()
    index = {**unpack(payload), 'docs':docs, 'chunks_by_id':{d.metadata['chunk_id']:d for d in docs},
             'tokenizer':embedder.model.tokenizer, 'max_query_tokens':embedder.max_seq_length,
             'vectorstore':store, 'dense':store.as_retriever({'k':min(payload['VECTOR_K'],len(docs))}),
             'bm25':bm25,'kiwi_tokenize':tokenize}
    if module == 'rfp':
        index['tasks_by_id'] = {t['task_id']:t for t in index['tasks']}
    return index


@lru_cache(maxsize=1)
def ntis_runtime():
    from rank_bm25 import BM25Okapi
    from kiwipiepy import Kiwi
    from sentence_transformers import CrossEncoder
    from app.ntis_rag.config import RERANKER_MODEL
    repo = SupabaseRepository()
    documents,chunks,_ = repo.snapshot('ntis')
    kiwi = Kiwi()
    tokenize = lambda text: [t.form for t in kiwi.tokenize(text)]
    bm25 = BM25Okapi([tokenize(c['content']) for c in chunks])
    return repo,{d['document_id']:d for d in documents},chunks,bm25,tokenize,CrossEncoder(RERANKER_MODEL)


def retrieve_ntis(structured_query, analysis_top_n):
    import numpy as np
    from app.ntis_rag.config import DENSE_K, BM25_K, RRF_K, RERANK_CANDIDATES
    repo,documents,chunks,bm25,tokenize,reranker = ntis_runtime()
    query = structured_query['search_query']
    dense = repo.search('ntis',get_embedder().encode_query(query),max(DENSE_K,analysis_top_n))
    scores = bm25.get_scores(tokenize(query))
    keyword = [chunks[i] for i in np.argsort(scores)[::-1][:max(BM25_K,analysis_top_n)] if scores[i]>0]
    fused, source_ranks = {},{}
    # Aggregate to projects before fusion: one project cannot consume all ranks.
    for source,rows in (('dense',dense),('bm25',keyword)):
        seen = set()
        for row in rows:
            did = row['document_id']
            if did in seen:
                continue
            seen.add(did)
            rank = len(seen)
            fused[did] = fused.get(did,0) + 1/(RRF_K+rank)
            source_ranks.setdefault(did,{})[source] = rank
    selected = sorted(fused,key=fused.get,reverse=True)[:max(RERANK_CANDIDATES,analysis_top_n)]
    if not selected:
        return []
    rerank_scores = reranker.predict([(query,documents[did]['full_text']) for did in selected])
    ranked = sorted(zip(selected,map(float,rerank_scores)),key=lambda row:-row[1])[:analysis_top_n]
    return [dict(project_id=documents[did]['metadata']['project_id'],project_title=documents[did]['title'],
                 organization=documents[did]['institution'],text=documents[did]['full_text'],metadata=documents[did]['metadata'],
                 rank=rank,rrf_score=fused[did],rerank_score=score,source_ranks=source_ranks[did])
            for rank,(did,score) in enumerate(ranked,1)]


def run_ntis_module(problem, **options):
    from app.ntis_rag.config import ANALYSIS_TOP_N
    from app.ntis_rag.generation.analysis import structure_query,extract_all_project_tech,canonicalize_technologies,aggregate_prior_rd_axes
    from app.ntis_rag.adapter import to_module_result
    top_n = options.pop('analysis_top_n',ANALYSIS_TOP_N)
    if top_n < 1:
        raise ValueError('analysis_top_n은 1 이상이어야 합니다.')
    structured = structure_query(problem,**options)
    projects = retrieve_ntis(structured,top_n)
    analyses = extract_all_project_tech(projects)
    canonical = canonicalize_technologies(analyses)
    return to_module_result(dict(query={'original_query':problem,'structured_query':structured},related_projects=projects,
                                 project_analyses=analyses,canonical_technologies=canonical,prior_rd_axes=aggregate_prior_rd_axes(canonical)))
