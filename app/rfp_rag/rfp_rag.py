"""Compatibility imports; new integrations should use this package pipeline."""
from .pipeline import build_index, search
from .config import PROJECT_ROOT
from app.common.validation import _positive_int
from app.common.chunking import _split_with_prefix
from app.common.retrieval import rrf, _retrieve, _ranking_rows, evaluate_retrieval
from .config import TECHNICAL_SECTIONS, CONTEXT_SECTIONS
from .parsing.notices import _source_key, _load_notices
from .retrieval.query import build_query
from .retrieval.evaluation import compare_queries
from .retrieval.pipeline import _task_requirements

def search_module_result(index, question, **search_options):
    """팀 통합 진입점. 원문 검색 결과를 공통 ModuleResult로 검증해 반환합니다."""
    from app.common.adapters import adapt_pdf_result

    return adapt_pdf_result(search(index, question, **search_options), index, 'rfp')
