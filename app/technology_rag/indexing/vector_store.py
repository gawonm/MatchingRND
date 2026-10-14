"""
벡터 저장소.

`VectorStore` 추상 클래스를 두는 이유는 **Supabase/pgvector 교체 지점을 한 곳으로 묶기 위해서**다
(plan.md: "현재는 테스트로 Chroma, 나중에 Supabase 고려"). 교체할 때 이 파일에
`SupabaseVectorStore` 를 추가하면 되고, 검색·파이프라인 코드는 손대지 않는다.

지문(fingerprint)
-----------------
컬렉션에 적재된 내용이 지금 청크와 같은지 판단할 때 **개수만 비교하면 안 된다.**
prefix 를 끄거나 정제 규칙을 고치면 개수는 그대로인데 내용이 달라진다.
그래서 전체 청크 텍스트의 해시를 컬렉션 메타데이터에 저장해 두고 비교한다.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from app.technology_rag.schemas import Chunk
from app.technology_rag.retrieval.types import Hit

log = logging.getLogger(__name__)


def fingerprint(chunks: Sequence[Chunk], model_name: str) -> str:
    h = hashlib.sha1(model_name.encode("utf-8"))
    for c in chunks:
        h.update(c.chunk_id.encode("utf-8"))
        h.update(c.text.encode("utf-8"))
    return h.hexdigest()[:16]


class VectorStore(ABC):
    @abstractmethod
    def count(self) -> int: ...

    @abstractmethod
    def stored_fingerprint(self) -> str | None: ...

    @abstractmethod
    def rebuild(self, chunks: Sequence[Chunk], vectors: np.ndarray, fp: str) -> None: ...

    @abstractmethod
    def query(self, vector: np.ndarray, top_k: int, where: dict | None = None) -> list[Hit]: ...

    def is_fresh(self, chunks: Sequence[Chunk], fp: str) -> bool:
        return self.stored_fingerprint() == fp and self.count() == len(chunks)


class ChromaVectorStore(VectorStore):
    """코사인 거리 기반 Chroma 컬렉션 하나를 감싼다."""

    def __init__(self, persist_dir: Path, collection: str) -> None:
        import chromadb

        self.persist_dir = Path(persist_dir)
        self.collection_name = collection
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))

    # ------------------------------------------------------------------
    def _get(self):
        try:
            return self._client.get_collection(self.collection_name)
        except Exception:  # noqa: BLE001  컬렉션 없음
            return None

    def count(self) -> int:
        col = self._get()
        return col.count() if col else 0

    def stored_fingerprint(self) -> str | None:
        col = self._get()
        return (col.metadata or {}).get("fp") if col else None

    def rebuild(self, chunks: Sequence[Chunk], vectors: np.ndarray, fp: str, batch: int = 1000) -> None:
        if self._get() is not None:
            self._client.delete_collection(self.collection_name)
        col = self._client.create_collection(
            self.collection_name, metadata={"hnsw:space": "cosine", "fp": fp}
        )
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            col.add(
                ids=[c.chunk_id for c in part],
                embeddings=vectors[i : i + batch].tolist(),
                documents=[c.text for c in part],
                metadatas=[c.metadata for c in part],
            )
        log.info("컬렉션 %s 적재 완료: %d건", self.collection_name, col.count())

    def query(self, vector: np.ndarray, top_k: int, where: dict | None = None) -> list[Hit]:
        col = self._get()
        if col is None:
            raise RuntimeError(f"컬렉션 {self.collection_name!r} 이 없습니다. python -m app.technology_rag.scripts.build_index 를 먼저 실행하세요.")
        res = col.query(
            query_embeddings=[np.asarray(vector, dtype=np.float32).tolist()],
            n_results=top_k,
            **({"where": where} if where else {}),
        )
        # 코사인 거리 → 유사도
        return [
            Hit(cid, 1.0 - float(dist), rank)
            for rank, (cid, dist) in enumerate(zip(res["ids"][0], res["distances"][0]), 1)
        ]


def build_store(backend: str, persist_dir: Path, collection: str, **kwargs: Any) -> VectorStore:
    if backend == "chroma":
        return ChromaVectorStore(persist_dir, collection)
    if backend == "supabase":
        return SupabaseVectorStore(collection)
    raise ValueError(f"지원하지 않는 backend: {backend!r}")


class SupabaseVectorStore(VectorStore):
    """Read adapter; complete corpus publication belongs to the ingest command."""
    def __init__(self, collection):
        from app.common.supabase_store import SupabaseRepository
        self.repository = SupabaseRepository()
        header = self.repository.corpus('technology')
        if header['payload'].get('collection') != collection:
            raise ValueError('Supabase 기술나눔 청킹 설정이 다릅니다. 같은 설정으로 다시 적재하세요.')

    def count(self):
        with self.repository.connection() as conn:
            return conn.execute("select count(*) from rag.chunks where corpus_id='technology'").fetchone()[0]

    def stored_fingerprint(self):
        return self.repository.corpus('technology')['fingerprint']

    def rebuild(self, chunks, vectors, fp):
        raise RuntimeError('Supabase 적재는 python -m app.scripts.supabase_rag ingest --modules technology 를 사용하세요.')

    def query(self, vector, top_k, where=None):
        from app.common.supabase_retrieval import flat_filter
        rows = self.repository.search('technology',vector,top_k,flat_filter(where))
        return [Hit(row['chunk_id'],row['similarity'],rank) for rank,row in enumerate(rows,1)]
