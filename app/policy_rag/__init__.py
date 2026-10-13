"""Public RAG entrypoints. Optional models load when an operation runs."""
from .pipeline import build_index, search, search_module_result

__all__ = ["build_index", "search", "search_module_result"]
