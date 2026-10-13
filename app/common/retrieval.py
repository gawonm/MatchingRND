"""Shared PDF filtering, rank fusion and retrieval evaluation."""

from .validation import _positive_int

def rrf(result_lists, k=60):
    """키워드 및 벡터 검색 순위를 reciprocal rank fusion으로 병합합니다."""
    if k <= 0:
        raise ValueError('RRF k는 양수여야 합니다.')
    scores = {}
    for hits in result_lists:
        seen = set()
        rank = 0
        for chunk_id, _ in hits:
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            rank += 1
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)

def _retrieve(index, query, filters, allowed_keys):
    """메타데이터 조건을 키워드·벡터 검색과 문맥 확장에 함께 적용합니다."""
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        raise ValueError('filters는 메타데이터 키와 값을 담은 dict여야 합니다.')
    for key, value in filters.items():
        if key not in allowed_keys or not isinstance(value, (str, int, float, bool)):
            raise ValueError(f'지원하지 않는 검색 필터: {key}')
        if isinstance(value, str) and not value.strip():
            raise ValueError(f'검색 필터 값이 비어 있습니다: {key}')
    allowed = [
        doc for doc in index['docs']
        if all(doc.metadata.get(key) == value for key, value in filters.items())
    ]
    if not allowed:
        return [], [], []
    if filters:
        from langchain_community.retrievers import BM25Retriever

        keyword = BM25Retriever.from_documents(allowed, preprocess_func=index['kiwi_tokenize'])
        keyword.k = min(index['KEYWORD_K'], len(allowed))
        conditions = [{key: value} for key, value in filters.items()]
        where = conditions[0] if len(conditions) == 1 else {'$and': conditions}
        keyword_hits = keyword.invoke(query)
        dense_hits = index['vectorstore'].similarity_search(
            query, k=min(index['VECTOR_K'], len(allowed)), filter=where,
        )
    else:
        keyword_hits = index['bm25'].invoke(query)
        dense_hits = index['dense'].invoke(query)
    valid_ids = {doc.metadata['chunk_id'] for doc in allowed}

    def valid_hits(hits):
        seen = set()
        result = []
        for doc in hits:
            cid = doc.metadata.get('chunk_id') or getattr(doc, 'id', None)
            if cid in valid_ids and cid not in seen:
                seen.add(cid)
                result.append((cid, 0))
        return result

    return valid_hits(keyword_hits), valid_hits(dense_hits), allowed

def _ranking_rows(index, ranking, keyword_ranks, vector_ranks, reranker_scores=None):
    """문맥에 넣기 전의 검색 순위를 보존해 문맥 예산과 독립적으로 평가합니다."""
    rows = []
    for rank, (cid, score) in enumerate(ranking, 1):
        metadata = index['chunks_by_id'][cid].metadata
        rows.append({
            'rank': rank, 'chunk_id': cid,
            'document_id': metadata['document_id'],
            'article_id': metadata.get('article_id'),
            'task_id': metadata.get('task_id'),
            'rrf_score': score, 'keyword_rank': keyword_ranks.get(cid),
            'vector_rank': vector_ranks.get(cid),
            'reranker_score': (reranker_scores or {}).get(cid),
        })
    return rows

def evaluate_retrieval(result, relevant_ids, *, k=5, id_key='document_id'):
    """정답 ID를 직접 제공해 단일 질문의 Recall@K, MRR, Hit@K를 계산합니다.

    id_key를 chunk_id로 지정하면 정답 근거 청크의 검색 여부를 평가합니다.
    같은 문서의 여러 청크는 문서·과제 단위 평가에서 한 번만 계산합니다.
    relevance는 점수나 검색 실패로 추정하지 않고 외부 정답을 사용합니다.
    """
    k = _positive_int(k, 'k')
    if id_key not in {'document_id', 'article_id', 'task_id', 'chunk_id'}:
        raise ValueError('지원하지 않는 평가 ID입니다.')
    if isinstance(relevant_ids, str):
        raise ValueError('relevant_ids는 정답 ID의 목록 또는 집합이어야 합니다.')
    relevant = set(relevant_ids)
    if not relevant or any(not isinstance(value, str) or not value for value in relevant):
        raise ValueError('평가에는 하나 이상의 비어 있지 않은 정답 ID가 필요합니다.')
    ordered = list(dict.fromkeys(
        row[id_key] for row in result['ranking'] if row.get(id_key)
    ))
    first = next((rank for rank, value in enumerate(ordered, 1) if value in relevant), None)
    retrieved = ordered[:k]
    matched = relevant.intersection(retrieved)
    return {
        'k': k, 'id_key': id_key, 'recall_at_k': len(matched) / len(relevant),
        'mrr': 1.0 / first if first else 0.0, 'hit_at_k': bool(matched),
        'retrieved_ids': retrieved,
    }
