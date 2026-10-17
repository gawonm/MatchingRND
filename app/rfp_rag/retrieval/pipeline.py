"""RFP task retrieval and evidence context assembly."""
import os
from app.common.validation import _positive_int
from app.common.retrieval import rrf, _retrieve, _ranking_rows
from ..config import CONTEXT_SECTIONS, TECHNICAL_SECTIONS
from .eligibility import TechnologyRelevanceGate
from .context_selection import filter_candidates

def _task_requirements(task):
    """검색된 과제의 명시적 요구항목 원문을 위치와 함께 반환합니다."""
    return {
        item: [{
            'text': fragment.page_content, 'page': fragment.metadata['page'],
            'bbox': fragment.metadata.get('bbox'), 'source': fragment.metadata['source'],
            'source_kind': fragment.metadata['kind'],
        } for fragment in fragments]
        for item, fragments in task.get('fields', {}).items()
        if item in TECHNICAL_SECTIONS
    }

def search(index, question, *, top_k=None, context_tokens=None, run_reranker=False,
           filters=None, reranker=None, relevance_llm=None,
           relevance_context_mode=None, relevance_batch_mode=None,
           candidate_order=None, candidate_window=None):
    """RFP 후보와 요구사항 원문·문맥·출처·검증된 검색 순위를 반환합니다.

    question은 문자열 또는 build_query(..., return_details=True)의 결과입니다.
    top_k는 중복 청크 수가 아닌 고유 과제 후보 수입니다. 필터는 키워드·벡터
    검색 및 문맥 확장에 동일하게 적용합니다. 보유+보완 기술 입력은 LLM으로 양쪽
    관련성을 검증합니다(relevance_llm 주입 가능). 답변 생성·Gap 판정은 수행하지 않습니다.
    """
    details = dict(question) if isinstance(question, dict) else None
    query = details.get('query') if details is not None else question
    if not isinstance(query, str) or not query.strip():
        raise ValueError('검색 질문을 문자열로 입력하세요.')
    query = query.strip()
    if details is not None and details.get('baseline_query') and not query.startswith(details['baseline_query']):
        raise ValueError('Cascade 질문에는 최초 입력인 baseline_query가 유지되어야 합니다.')
    tokenizer = index['tokenizer']
    top_k = _positive_int(top_k if top_k is not None else index['TOP_K'], 'top_k')
    context_tokens = _positive_int(
        context_tokens if context_tokens is not None else index['CONTEXT_TOKENS'], 'context_tokens',
    )
    if len(tokenizer.encode(query, add_special_tokens=False)) + 2 > index['max_query_tokens']:
        raise ValueError('질문이 임베딩 토큰 한도를 넘었습니다. 최초 기술문제를 유지하며 확장 요소를 줄이세요.')
    keyword, vector, allowed_docs = _retrieve(
        index, query, filters,
        {'document_id', 'task_id', 'task_number', 'filename', 'source', 'item'},
    )
    ranking = rrf([keyword, vector], k=index['RRF_K'])
    keyword_ranks = {cid: rank for rank, (cid, _) in enumerate(keyword, 1)}
    vector_ranks = {cid: rank for rank, (cid, _) in enumerate(vector, 1)}
    chunks = index['chunks_by_id']
    reranker_scores = {}
    if ranking and (run_reranker or reranker is not None):
        import math

        if reranker is None:
            from sentence_transformers import CrossEncoder

            model = os.getenv('RFP_RERANKER_MODEL', '')
            if not model:
                raise ValueError('RFP_RERANKER_MODEL을 지정하거나 reranker를 전달하세요.')
            reranker = CrossEncoder(model, device='cpu', local_files_only=True)
        scores = list(reranker.predict([(query, chunks[cid].page_content) for cid, _ in ranking]))
        if len(scores) != len(ranking) or any(not math.isfinite(float(score)) for score in scores):
            raise ValueError('리랭커의 점수 개수 또는 값이 올바르지 않습니다.')
        reranker_scores = {cid: float(score) for (cid, _), score in zip(ranking, scores)}
        ranking.sort(key=lambda pair: -reranker_scores[pair[0]])
    gate = TechnologyRelevanceGate(question, relevance_llm,
                                  context_mode=relevance_context_mode, batch_mode=relevance_batch_mode)
    tasks_by_id = index.get('tasks_by_id') or {
        task['task_id']: task for task in index['dataset'].get('tasks', [])
    }
    seen_tasks, candidates = set(), []
    for cid, score in ranking:
        task_id = chunks[cid].metadata['task_id']
        if task_id not in seen_tasks:
            seen_tasks.add(task_id)
            candidates.append((cid, score))
    candidate_order = candidate_order or os.getenv('RFP_RELEVANCE_CANDIDATE_ORDER', 'retrieval')
    if candidate_window is None and os.getenv('RFP_RELEVANCE_CANDIDATE_WINDOW'):
        candidate_window = int(os.environ['RFP_RELEVANCE_CANDIDATE_WINDOW'])
    selected, relevance_checks, selection_diagnostics = filter_candidates(
        candidates, chunks, tasks_by_id, gate, top_k, order=candidate_order, window=candidate_window)
    if gate.active:
        accepted_tasks = {chunks[cid].metadata['task_id'] for cid, _ in selected}
        ranking = [(cid, score) for cid, score in ranking
                   if chunks[cid].metadata['task_id'] in accepted_tasks]
    ranking_rows = _ranking_rows(index, ranking, keyword_ranks, vector_ranks, reranker_scores)
    rows_by_id = {row['chunk_id']: row for row in ranking_rows}

    # 모든 후보의 대표 근거를 먼저 배치한 뒤 같은 과제의 조건을 보충합니다.
    sources, context_parts = [], []
    used_ids, skipped_ids = set(), set()
    notices_by_id = index['dataset']['notices']

    def add(cid, candidate_rank, expanded_from=None):
        if cid in used_ids:
            return
        document = chunks[cid]
        metadata = document.metadata
        expanded = expanded_from is not None
        label = (
            f"[근거 {cid} | {metadata['source']} | {metadata['pages']}쪽 | "
            f"과제={metadata['task_id']} | 항목={metadata['item']} | 확장={expanded}]"
        )
        part = label + '\n' + document.page_content
        if len(tokenizer.encode('\n\n'.join(context_parts + [part]), add_special_tokens=False)) > context_tokens:
            skipped_ids.add(cid)
            return
        linked = [notices_by_id[nid] for nid in metadata.get('notice_ids', []) if nid in notices_by_id]
        origin = rows_by_id[expanded_from or cid]
        evidence = {
            'evidence_id': cid, 'chunk_id': cid, 'task_id': metadata['task_id'],
            'document_id': metadata['document_id'], 'source_type': 'rfp',
            'role': 'technical_candidate', 'source': metadata['source'],
            'filename': metadata['filename'], 'pages': metadata['pages'],
            'text': metadata.get('original_text', document.page_content),
            'content': document.page_content, 'item': metadata['item'], 'title': metadata['title'],
            'source_locations': [{
                'page': source['page'], 'bbox': source.get('bbox'),
                'source_kind': source['kind'], 'text': source.get('original_text', ''),
            } for source in metadata.get('sources', [])],
            'rank': None if expanded else candidate_rank,
            'rrf_score': None if expanded else origin['rrf_score'],
            'keyword_rank': None if expanded else origin['keyword_rank'],
            'vector_rank': None if expanded else origin['vector_rank'],
            'reranker_score': None if expanded else origin['reranker_score'],
            'expanded': expanded, 'expanded_from': expanded_from,
            'notice_ids': metadata.get('notice_ids', []),
            'notice_titles': [notice['title'] for notice in linked],
            'notice_urls': [notice['url'] for notice in linked if notice['url']],
            'notice_link_status': 'linked' if linked else 'not_available',
        }
        # 기존 표시용 필드도 유지하여 통합 시 호출부 수정을 줄입니다.
        evidence.update({
            '과제명': evidence['title'], '항목': evidence['item'],
            '파일명': evidence['filename'], '페이지': evidence['pages'],
            '공고명': evidence['notice_titles'], '공고URL': evidence['notice_urls'],
            '원문': evidence['text'],
        })
        used_ids.add(cid)
        context_parts.append(part)
        sources.append(evidence)

    for candidate_rank, (cid, _) in enumerate(selected, 1):
        add(cid, candidate_rank)
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        original = chunks[cid]
        if cid not in used_ids or original.metadata['item'] == '과제전체':
            continue
        for item in CONTEXT_SECTIONS:
            for related in allowed_docs:
                if related.metadata['task_id'] == original.metadata['task_id'] and related.metadata['item'] == item:
                    add(related.metadata['chunk_id'], candidate_rank, expanded_from=cid)

    hits = []
    for candidate_rank, (cid, _) in enumerate(selected, 1):
        metadata = chunks[cid].metadata
        task = tasks_by_id.get(metadata['task_id'], {})
        hits.append({
            **rows_by_id[cid], 'rank': candidate_rank, 'title': metadata['title'],
            'task_number': metadata.get('task_number', ''), 'filename': metadata['filename'],
            'source': metadata['source'], 'result_type': 'technical_candidate',
            'requirements': _task_requirements(task), 'metrics': task.get('metrics', []),
            'technology_relevance': relevance_checks.get(metadata['task_id']),
            'context_evidence_ids': [row['chunk_id'] for row in sources if row['task_id'] == metadata['task_id']],
            'review_notes': [row for row in index.get('review_list', []) if row.get('filename') == metadata['filename']],
        })
    status = 'ok' if sources else ('context_limit' if ranking else 'no_matches')
    return {
        'question': query, 'query_details': details, 'context': '\n\n'.join(context_parts),
        'sources': sources, 'hits': hits, 'ranking': ranking_rows, 'status': status,
        'message': '관련 공고가 없습니다.' if status == 'no_matches' else '',
        'result_type': 'technical_candidate', 'filters': dict(filters or {}),
        'context_truncated': bool(skipped_ids), 'omitted_context_ids': sorted(skipped_ids),
        'diagnostics': {
            'candidate_selection': selection_diagnostics,
            'technology_relevance': {'enabled': gate.active, 'checks': relevance_checks, 'llm_usage': gate.stats},
            'failed_files': index.get('failed_files', []),
            'excluded_files': index.get('excluded_files', []),
            'matching_issues': index.get('matching_issues', []),
        },
    }
