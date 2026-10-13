"""
하이브리드 검색 (RRF) 과 문서 단위 집계.

왜 RRF 인가
-----------
BM25 점수(수십~수백)와 코사인 유사도(0~1)는 척도가 달라 그대로 더할 수 없다.
RRF 는 점수 대신 **순위**를 쓴다.

    RRF(c) = Σ_m  w_m / (k + rank_m(c))        k = 60 (기본)

한쪽에만 걸린 청크도 점수를 받고, 양쪽에서 상위인 청크가 가장 높아진다.

두 가지 구현
------------
- `rrf_fuse`      : 직접 구현. 방식별 순위를 함께 돌려주므로 디버깅과 분석에 쓴다.
- `ensemble_fuse` : LangChain `EnsembleRetriever`. 팀이 LangChain 체인에 꽂을 때 쓴다.

두 구현은 **같은 순서**를 낸다 (쿼리 15개 × 전략 3개에서 전부 일치, tests/test_hybrid.py 가 검사).
EnsembleRetriever 는 점수와 방식별 순위를 돌려주지 않아, 래퍼가 직전 호출의 순위를 보관했다가 복원한다.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Mapping, Sequence

from app.technology_rag.schemas import Chunk
from app.technology_rag.retrieval.filters import matches
from app.technology_rag.retrieval.types import DocHit, Hit

#: {chunk_id: {"bm25": 3, "dense": 1}} — 각 방식에서 몇 위였는지
RankDetail = dict[str, dict[str, int]]


# =============================================================================
# 융합
# =============================================================================

def rrf_fuse(
    ranked: Mapping[str, Sequence[Hit]],
    k: int = 60,
    weights: Mapping[str, float] | None = None,
) -> tuple[list[Hit], RankDetail]:
    score: dict[str, float] = defaultdict(float)
    detail: RankDetail = defaultdict(dict)
    for method, hits in ranked.items():
        w = 1.0 if weights is None else float(weights.get(method, 0.0))
        for h in hits:
            score[h.chunk_id] += w / (k + h.rank)
            detail[h.chunk_id][method] = h.rank
    order = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))
    return [Hit(cid, s, r) for r, (cid, s) in enumerate(order, 1)], dict(detail)


def ensemble_fuse(
    searchers: Mapping[str, Callable[[str], Sequence[Hit]]],
    query: str,
    chunk_map: Mapping[str, Chunk],
    k: int = 60,
    weights: Mapping[str, float] | None = None,
) -> tuple[list[Hit], RankDetail]:
    """LangChain EnsembleRetriever 로 같은 융합을 수행한다 (langchain 은 여기서만 import)."""
    from langchain_classic.retrievers.ensemble import EnsembleRetriever
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever

    class _HitsRetriever(BaseRetriever):
        """우리 검색 함수를 LangChain Retriever 로 감싼다. 직전 호출의 순위를 보관한다."""

        model_config = {"arbitrary_types_allowed": True}
        search_fn: Callable
        texts: Mapping[str, Chunk]
        method: str
        last: dict = {}

        def _get_relevant_documents(self, q: str, *, run_manager=None) -> list[Document]:
            hits = list(self.search_fn(q))
            self.last = {h.chunk_id: h.rank for h in hits}
            return [
                Document(page_content=self.texts[h.chunk_id].text,
                         metadata={"chunk_id": h.chunk_id, "method": self.method, "rank": h.rank})
                for h in hits
            ]

    names = list(searchers)
    retrievers = [_HitsRetriever(search_fn=searchers[n], texts=chunk_map, method=n) for n in names]
    w = [1.0 / len(names)] * len(names) if weights is None else [float(weights.get(n, 0.0)) for n in names]
    docs = EnsembleRetriever(retrievers=retrievers, weights=w, c=k, id_key="chunk_id").invoke(query)

    detail: RankDetail = {}
    hits: list[Hit] = []
    for rank, d in enumerate(docs, 1):
        cid = d.metadata["chunk_id"]
        ranks = {n: r.last[cid] for n, r in zip(names, retrievers) if cid in r.last}
        detail[cid] = ranks
        # Ensemble 은 점수를 돌려주지 않으므로 같은 공식으로 다시 계산한다
        hits.append(Hit(cid, sum(wi / (k + ranks[n]) for n, wi in zip(names, w) if n in ranks), rank))
    return hits, detail


# =============================================================================
# 문서 단위 집계 (parent-child)
# =============================================================================

def aggregate_to_docs(
    hits: Sequence[Hit],
    chunk_map: Mapping[str, Chunk],
    mode: str = "max",
) -> list[DocHit]:
    """청크 단위 결과를 기술(문서) 단위로 모은다.

    검색은 청크 단위로 일어나지만 사용자에게 보여줄 단위는 기술 1건이다.
    `best_chunk_id` 는 그 문서에서 가장 점수가 높았던 청크 = 근거를 보여줄 위치.
    """
    best: dict[str, tuple[float, str]] = {}
    total: dict[str, float] = defaultdict(float)
    for h in hits:
        doc_id = chunk_map[h.chunk_id].parent_doc_id
        total[doc_id] += h.score
        if doc_id not in best or h.score > best[doc_id][0]:
            best[doc_id] = (h.score, h.chunk_id)
    scored = [
        (doc_id, total[doc_id] if mode == "sum" else best[doc_id][0], best[doc_id][1])
        for doc_id in best
    ]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return [DocHit(d, s, c, r) for r, (d, s, c) in enumerate(scored, 1)]


# =============================================================================
# 검색기
# =============================================================================

class HybridRetriever:
    """BM25 + Dense → 융합. 결과는 청크 단위.

    `where` 필터는 **양쪽 모두에** 적용된다. Dense 는 Chroma 가 네이티브로 거르고,
    BM25 는 넉넉히 뽑은 뒤 파이썬에서 거른다 (BM25 는 어차피 전체 점수를 계산하므로
    많이 뽑아도 비용이 거의 같다). 한쪽만 거르면 융합 후 조건에 맞지 않는 문서가 섞인다.
    """

    #: 필터가 있을 때 BM25 를 몇 배로 뽑은 뒤 거를지
    FILTER_OVERSAMPLE = 10

    def __init__(
        self,
        bm25,
        dense,
        chunk_map: Mapping[str, Chunk],
        *,
        fusion: str = "rrf",
        bm25_top_k: int = 50,
        dense_top_k: int = 50,
        rrf_k: int = 60,
        weights: Sequence[float] = (0.5, 0.5),
    ) -> None:
        self.bm25 = bm25
        self.dense = dense
        self.chunk_map = chunk_map
        self.fusion = fusion
        self.bm25_top_k = bm25_top_k
        self.dense_top_k = dense_top_k
        self.rrf_k = rrf_k
        self.weights = {"bm25": float(weights[0]), "dense": float(weights[1])}

    def _bm25_search(self, query: str, where: dict | None) -> list[Hit]:
        if not where:
            return self.bm25.search(query, self.bm25_top_k)
        wide = self.bm25.search(query, self.bm25_top_k * self.FILTER_OVERSAMPLE)
        kept = [h for h in wide if matches(self.chunk_map[h.chunk_id].metadata, where)]
        # 걸러낸 뒤 순위를 다시 매긴다 (RRF 는 순위를 쓰므로 1부터 연속이어야 한다)
        return [Hit(h.chunk_id, h.score, r) for r, h in enumerate(kept[: self.bm25_top_k], 1)]

    def search(self, query: str, where: dict | None = None) -> tuple[list[Hit], RankDetail]:
        searchers = {
            "bm25": lambda q: self._bm25_search(q, where),
            "dense": lambda q: self.dense.search(q, self.dense_top_k, where=where),
        }
        if self.fusion == "ensemble":
            return ensemble_fuse(searchers, query, self.chunk_map, k=self.rrf_k, weights=self.weights)
        return rrf_fuse({n: fn(query) for n, fn in searchers.items()}, k=self.rrf_k, weights=self.weights)
