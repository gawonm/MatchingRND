"""Law article retrieval and evidence context assembly."""
from app.common.validation import _positive_int
from app.common.retrieval import rrf, _retrieve, _ranking_rows

def search(index, question, *, top_k=None, context_tokens=None, law_filter="", filters=None):
    """제도 참고용 조문과 원문 위치·검색 순위를 반환합니다.

    filters는 law_name, law_type, law_family, kind, document_id, article_number를
    지원합니다. PDF 표제 시행일은 제공하되 현재 유효성·지원자격은 판정하지 않습니다.
    top_k는 고유 조문 수이며 동일 조문의 다른 청크는 문맥 예산 내에서 확장합니다.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError('검색 질문을 문자열로 입력하세요.')
    query = question.strip()
    top_k = _positive_int(top_k if top_k is not None else index['TOP_K'], 'top_k')
    context_tokens = _positive_int(
        context_tokens if context_tokens is not None else index['CONTEXT_TOKENS'], 'context_tokens',
    )
    tokenizer = index['tokenizer']
    if len(tokenizer.encode(query, add_special_tokens=False)) + 2 > index['max_query_tokens']:
        raise ValueError('질문이 임베딩 토큰 한도를 넘었습니다.')
    if filters is not None and not isinstance(filters, dict):
        raise ValueError('filters는 dict여야 합니다.')
    filters = dict(filters or {})
    if not isinstance(law_filter, str):
        raise ValueError('law_filter는 법령명 문자열이어야 합니다.')
    if law_filter:
        if 'law_name' in filters and filters['law_name'] != law_filter:
            raise ValueError('law_filter와 filters의 법령명이 다릅니다.')
        filters['law_name'] = law_filter
    keyword, vector, allowed_docs = _retrieve(
        index, query, filters,
        {'law_name', 'law_type', 'law_family', 'kind', 'document_id', 'article_number'},
    )
    ranking = rrf([keyword, vector], k=index['RRF_K'])
    keyword_ranks = {cid: rank for rank, (cid, _) in enumerate(keyword, 1)}
    vector_ranks = {cid: rank for rank, (cid, _) in enumerate(vector, 1)}
    ranking_rows = _ranking_rows(index, ranking, keyword_ranks, vector_ranks)
    rows_by_id = {row['chunk_id']: row for row in ranking_rows}
    chunks = index['chunks_by_id']
    selected, seen_articles = [], set()
    for cid, score in ranking:
        article_id = chunks[cid].metadata['article_id']
        if article_id not in seen_articles:
            seen_articles.add(article_id)
            selected.append((cid, score))
        if len(selected) == top_k:
            break
    context_parts, sources = [], []
    used_ids, skipped_ids = set(), set()

    def add(cid, candidate_rank, expanded_from=None):
        if cid in used_ids:
            return
        document = chunks[cid]
        metadata = document.metadata
        expanded = expanded_from is not None
        label = (
            f"[근거 {cid} | {metadata['law_name']} {metadata['article_number']} | "
            f"{metadata['filename']} | {metadata['pages']}쪽 | 확장={expanded}]"
        )
        part = label + '\n' + document.page_content
        if len(tokenizer.encode('\n\n'.join(context_parts + [part]), add_special_tokens=False)) > context_tokens:
            skipped_ids.add(cid)
            return
        origin = rows_by_id[expanded_from or cid]
        source = {
            'evidence_id': cid, 'chunk_id': cid, 'article_id': metadata['article_id'],
            'document_id': metadata['document_id'], 'source_type': 'law',
            'role': 'institutional_reference', 'source': metadata['source'],
            'filename': metadata['filename'], 'pages': metadata['pages'],
            'article_pages': metadata.get('article_pages', metadata['pages']),
            'source_locations': metadata.get('source_locations', []),
            'text': metadata.get('original_text', document.page_content), 'content': document.page_content,
            'law_name': metadata['law_name'], 'law_type': metadata['law_type'],
            'law_family': metadata['law_family'], 'article_number': metadata['article_number'],
            'article_title': metadata['article_title'], 'kind': metadata['kind'],
            'effective_date': metadata['effective_date'], 'publication': metadata['publication'],
            'source_url': metadata['source_url'], 'source_url_type': 'law_name_lookup',
            'validity_status': 'not_verified', 'review_note': metadata['review_note'],
            'expanded': expanded, 'expanded_from': expanded_from,
            'rank': None if expanded else candidate_rank,
            'rrf_score': None if expanded else origin['rrf_score'],
            'keyword_rank': None if expanded else origin['keyword_rank'],
            'vector_rank': None if expanded else origin['vector_rank'],
        }
        source.update({
            '법령명': source['law_name'], '법령종류': source['law_type'],
            '조문': source['article_number'], '조문제목': source['article_title'],
            'PDF표제시행일': source['effective_date'], '파일명': source['filename'],
            '페이지': source['pages'], '페이지범위설명': metadata['page_scope'],
            '공식조회URL': source['source_url'], '검토사항': source['review_note'],
            '확장': expanded, '확장원본': expanded_from, '검색순위': source['rank'],
            'RRF점수': source['rrf_score'], 'BM25순위': source['keyword_rank'],
            '벡터순위': source['vector_rank'], '원문': source['text'],
        })
        used_ids.add(cid)
        context_parts.append(part)
        sources.append(source)

    # 후보 조문들의 직접 검색 근거를 우선 넣은 후 주변 조문 청크를 추가합니다.
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        add(cid, candidate_rank)
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        if cid not in used_ids:
            continue
        original = chunks[cid].metadata
        related = [
            doc for doc in allowed_docs
            if doc.metadata['article_id'] == original['article_id']
            and doc.metadata['chunk_id'] != cid
        ]
        related.sort(key=lambda doc: abs(doc.metadata['part'] - original['part']))
        for document in related:
            add(document.metadata['chunk_id'], candidate_rank, expanded_from=cid)
    hits = []
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        metadata = chunks[cid].metadata
        hits.append({
            **rows_by_id[cid], 'rank': candidate_rank,
            'law_name': metadata['law_name'], 'law_type': metadata['law_type'],
            'article_number': metadata['article_number'], 'article_title': metadata['article_title'],
            'effective_date': metadata['effective_date'], 'validity_status': 'not_verified',
            'result_type': 'institutional_reference', 'review_note': metadata['review_note'],
            'context_evidence_ids': [row['chunk_id'] for row in sources if row['article_id'] == metadata['article_id']],
        })
    status = 'ok' if sources else ('context_limit' if ranking else 'no_matches')
    return {
        'question': query, 'context': '\n\n'.join(context_parts), 'sources': sources,
        'hits': hits, 'ranking': ranking_rows, 'status': status,
        'result_type': 'institutional_reference', 'filters': filters,
        'context_truncated': bool(skipped_ids), 'omitted_context_ids': sorted(skipped_ids),
        'diagnostics': {
            'failed_files': index.get('failed_files', []),
            'review_list': index.get('review_list', []),
            'excluded_section_count': len(index.get('excluded_sections', [])),
        },
    }
