"""Public RAG entrypoints for index construction and search."""
from .indexing.build_index import build_index
from .retrieval.pipeline import search
from .adapter import to_module_result

def search_module_result(index, question, **search_options):
    """팀 통합 진입점. 원문 검색 결과를 공통 ModuleResult로 검증해 반환합니다."""
    return to_module_result(search(index, question, **search_options), index)
