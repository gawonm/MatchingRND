"""
리랭커 (Cross-Encoder).

융합 상위 pool 개를 (쿼리, 청크) **쌍으로 직접 읽어** 점수를 다시 매긴다.
임베딩 검색은 쿼리와 문서를 따로 벡터로 만들어 비교하지만, 리랭커는 둘을 함께 보므로 더 정확하다.
대신 쿼리마다 모델을 pool 회 돌려야 해서 느리다 (실측: 후보 50개에 0.39초).

모델은 지연 로딩한다.
"""

from __future__ import annotations

import logging
from typing import Mapping, Sequence

from app.technology_rag.schemas import Chunk
from app.technology_rag.config import RerankConfig, resolve_device
from app.technology_rag.retrieval.types import Hit

log = logging.getLogger(__name__)


class Reranker:
    def __init__(self, config: RerankConfig) -> None:
        self.config = config
        self._model = None
        # 같은 (쿼리, 후보)를 다시 재정렬하지 않도록 마지막 몇 건을 기억한다.
        # CPU 에서는 한 번에 ~20초라, search → 추적 → answer 가 각각 부르면 곱절로 느려진다.
        self._memo: dict[tuple, list[Hit]] = {}

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            device, fp16 = resolve_device(self.config.device, self.config.fp16)
            log.info("리랭커 로드: %s (device=%s, fp16=%s)", self.config.model, device, fp16)
            m = CrossEncoder(self.config.model, device=device, max_length=self.config.max_length)
            if fp16:
                m.model.half()
            self._model = m
        return self._model

    def rerank(self, query: str, hits: Sequence[Hit], chunk_map: Mapping[str, Chunk]) -> list[Hit]:
        """상위 pool 개를 재정렬해 돌려준다. pool 밖의 후보는 버린다."""
        pool = list(hits[: self.config.pool])
        if not pool:
            return []
        key = (query, tuple(h.chunk_id for h in pool))
        if key in self._memo:
            return list(self._memo[key])
        scores = self.model.predict(
            [(query, chunk_map[h.chunk_id].text) for h in pool],
            batch_size=self.config.batch_size,
            show_progress_bar=False,
        )
        order = sorted(zip(pool, scores), key=lambda x: -float(x[1]))
        out = [Hit(h.chunk_id, float(s), r) for r, (h, s) in enumerate(order, 1)]
        if len(self._memo) >= 32:
            self._memo.pop(next(iter(self._memo)))
        self._memo[key] = out
        return list(out)
