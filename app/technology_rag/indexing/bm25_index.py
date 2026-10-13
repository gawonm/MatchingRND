"""
BM25 인덱스 (청크 단위).

rank_bm25.BM25Okapi 위에 얇게 감싼다. 검색 결과는 청크 단위이며,
문서(기술) 단위 집계는 retrieval/hybrid.py 의 책임이다.

저장 형식은 JSON(토큰화된 말뭉치 + 토크나이저 설정)이다. 불러올 때 BM25Okapi 만 다시 만든다.
(pickle 은 쓰지 않는다: 버전 의존성과 신뢰 문제)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np
from rank_bm25 import BM25Okapi

from app.technology_rag.schemas import Chunk
from app.technology_rag.indexing.tokenizer import KiwiTokenizer, default_tokenizer
from app.technology_rag.retrieval.types import Hit

#: 과거 이름 (BM25 도 공통 Hit 을 쓴다)
BM25Hit = Hit


class BM25Index:
    def __init__(
        self,
        tokenizer: KiwiTokenizer | None = None,
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.tokenizer = tokenizer or default_tokenizer()
        self.k1 = k1
        self.b = b
        self._pos: dict[str, int] | None = None   # chunk_id → 말뭉치 위치 (matched_tokens 용, 지연 생성)
        self.chunk_ids: list[str] = []
        self._corpus: list[list[str]] = []
        self._bm25: BM25Okapi | None = None

    # ------------------------------------------------------------------
    def fit(self, chunks: Sequence[Chunk]) -> "BM25Index":
        self._pos = None  # 다시 학습하면 위치 맵을 버린다
        self.chunk_ids = [c.chunk_id for c in chunks]
        self._corpus = self.tokenizer.tokenize_many(c.text for c in chunks)
        self._bm25 = BM25Okapi(self._corpus, k1=self.k1, b=self.b)
        return self

    def __len__(self) -> int:
        return len(self.chunk_ids)

    def search(self, query: str, top_k: int = 50) -> list[Hit]:
        """점수가 0 인 청크는 반환하지 않는다 (쿼리 토큰이 하나도 안 걸린 청크)."""
        if self._bm25 is None:
            raise RuntimeError("fit() 또는 load() 먼저")
        q = self.tokenizer(query)
        if not q:
            return []
        scores = self._bm25.get_scores(q)
        k = min(top_k, len(scores))
        idx = np.argpartition(-scores, k - 1)[:k]
        idx = idx[np.argsort(-scores[idx], kind="stable")]
        return [
            Hit(self.chunk_ids[i], float(scores[i]), r)
            for r, i in enumerate(idx, 1)
            if scores[i] > 0
        ]

    def explain(self, query: str) -> list[str]:
        """쿼리가 어떤 토큰으로 검색되는지 (디버깅용)."""
        return self.tokenizer(query)

    def matched_tokens(self, query: str, chunk_id: str) -> list[str]:
        """쿼리 토큰 중 이 청크에 실제로 들어 있는 것 = BM25 가 이 청크를 고른 이유.

        쿼리에 같은 토큰이 여러 번 나와도 한 번만 돌려준다 (등장 순서 유지).
        """
        if self._pos is None:
            self._pos = {cid: i for i, cid in enumerate(self.chunk_ids)}
        if chunk_id not in self._pos:
            raise KeyError(f"BM25 인덱스에 없는 chunk_id: {chunk_id}")
        in_chunk = set(self._corpus[self._pos[chunk_id]])
        seen: set[str] = set()
        out: list[str] = []
        for t in self.tokenizer(query):
            if t in in_chunk and t not in seen:
                seen.add(t)
                out.append(t)
        return out

    # ------------------------------------------------------------------
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tokenizer": self.tokenizer.config(),
            "k1": self.k1,
            "b": self.b,
            "chunk_ids": self.chunk_ids,
            "corpus": self._corpus,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg = {k: v for k, v in d["tokenizer"].items() if k != "name"}
        idx = cls(KiwiTokenizer(**cfg), k1=d["k1"], b=d["b"])
        idx.chunk_ids = d["chunk_ids"]
        idx._corpus = d["corpus"]
        idx._bm25 = BM25Okapi(idx._corpus, k1=idx.k1, b=idx.b)
        return idx
