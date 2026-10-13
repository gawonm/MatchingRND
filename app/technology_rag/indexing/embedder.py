"""
문장 임베딩 (BGE-m3-ko) + 캐시.

캐시를 두는 이유
----------------
청킹 전략을 바꿔 가며 실험하면 같은 텍스트를 반복해서 임베딩하게 된다.
(모델명 + 텍스트) 해시를 키로 저장해 두면 바뀐 청크만 다시 계산한다.
실측: 3전략 전체(5,910청크) 최초 40초 → 재실행 0.03초.

모델은 **지연 로딩**한다. 이 모듈을 import 하는 것만으로 GPU 메모리를 잡지 않는다.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from app.technology_rag.config import EmbeddingConfig, resolve_device

log = logging.getLogger(__name__)


class Embedder:
    def __init__(self, config: EmbeddingConfig, cache_path: Path | None = None) -> None:
        self.config = config
        self.cache_path = Path(cache_path) if cache_path else None
        self._model = None
        self._cache: dict[str, np.ndarray] | None = None

    # ------------------------------------------------------------------ 모델
    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            device, fp16 = resolve_device(self.config.device, self.config.fp16)
            log.info("임베딩 모델 로드: %s (device=%s, fp16=%s)", self.config.model, device, fp16)
            m = SentenceTransformer(self.config.model, device=device)
            if fp16:
                m.half()
            self._model = m
        return self._model

    @property
    def dim(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    @property
    def max_seq_length(self) -> int:
        return self.model.max_seq_length

    def token_length(self, text: str) -> int:
        """모델 입력 한도를 넘는 청크가 있는지 확인할 때 쓴다."""
        return len(self.model.tokenizer(text)["input_ids"])

    # ------------------------------------------------------------------ 캐시
    def _key(self, text: str) -> str:
        return hashlib.sha1(f"{self.config.model}|{text}".encode("utf-8")).hexdigest()

    @property
    def cache(self) -> dict[str, np.ndarray]:
        if self._cache is None:
            self._cache = {}
            if self.cache_path and self.cache_path.exists():
                z = np.load(self.cache_path, allow_pickle=False)
                self._cache = dict(zip(z["keys"].tolist(), z["vecs"]))
                log.info("임베딩 캐시 로드: %d건", len(self._cache))
        return self._cache

    def save_cache(self) -> None:
        if not self.cache_path or not self.cache:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            self.cache_path,
            keys=np.array(list(self.cache)),
            vecs=np.stack(list(self.cache.values())).astype(np.float32),
        )

    # ------------------------------------------------------------------ 인코딩
    def encode(self, texts: Sequence[str], *, use_cache: bool = True) -> tuple[np.ndarray, int]:
        """(벡터 행렬, 새로 계산한 개수). 벡터는 L2 정규화된 float32."""
        texts = list(texts)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32), 0
        if not use_cache:
            return self._encode_raw(texts), len(texts)

        keys = [self._key(t) for t in texts]
        cache = self.cache
        missing = [i for i, k in enumerate(keys) if k not in cache]
        if missing:
            vecs = self._encode_raw([texts[i] for i in missing])
            for i, v in zip(missing, vecs):
                cache[keys[i]] = v
        return np.stack([cache[k] for k in keys]), len(missing)

    def encode_query(self, query: str) -> np.ndarray:
        """쿼리는 캐시하지 않는다 (매번 다르다)."""
        return self._encode_raw([query])[0]

    def _encode_raw(self, texts: Iterable[str]) -> np.ndarray:
        return self.model.encode(
            list(texts),
            batch_size=self.config.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype(np.float32)
