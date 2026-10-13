"""의미 기반 검색: 쿼리를 임베딩해 벡터 저장소에서 가까운 청크를 찾는다."""

from __future__ import annotations

from app.technology_rag.indexing.embedder import Embedder
from app.technology_rag.indexing.vector_store import VectorStore
from app.technology_rag.retrieval.types import Hit


class DenseRetriever:
    def __init__(self, embedder: Embedder, store: VectorStore) -> None:
        self.embedder = embedder
        self.store = store

    def search(self, query: str, top_k: int = 50, where: dict | None = None) -> list[Hit]:
        return self.store.query(self.embedder.encode_query(query), top_k, where=where)
