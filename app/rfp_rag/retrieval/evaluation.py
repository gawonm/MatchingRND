"""Baseline/cascade comparison using the shared evaluation metrics."""
from app.common.retrieval import evaluate_retrieval
from .pipeline import search

def compare_queries(index, query_details, relevant_ids, *, k=5, id_key='task_id', **search_options):
    """같은 인덱스·검색 설정으로 Baseline/Cascade의 단일 질문 평가를 비교합니다."""
    if not isinstance(query_details, dict) or not query_details.get('baseline_query'):
        raise ValueError('build_query(..., return_details=True)의 결과가 필요합니다.')
    baseline = search(index, query_details['baseline_query'], **search_options)
    cascade = search(index, query_details, **search_options)
    relevant_ids = list(relevant_ids) if not isinstance(relevant_ids, str) else relevant_ids
    return {
        'baseline': {'result': baseline, 'metrics': evaluate_retrieval(baseline, relevant_ids, k=k, id_key=id_key)},
        'cascade': {'result': cascade, 'metrics': evaluate_retrieval(cascade, relevant_ids, k=k, id_key=id_key)},
    }
