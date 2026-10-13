r"""
청크 → BM25 인덱스 + 벡터 인덱스(Chroma).

실행:
    .venv\Scripts\python.exe -X utf8 -m app.technology_rag.scripts.build_index
    .venv\Scripts\python.exe -X utf8 -m app.technology_rag.scripts.build_index --strategies doc section section_group
    .venv\Scripts\python.exe -X utf8 -m app.technology_rag.scripts.build_index --force      # 최신이어도 다시 만들기

전제: python -m app.technology_rag.scripts.build_chunks 로 chunks_*.jsonl 이 있어야 한다.
임베딩은 (모델+텍스트) 해시 캐시를 쓰므로, 전략을 바꿔도 겹치는 텍스트는 다시 계산하지 않는다.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from app.technology_rag.config import load_config
from app.technology_rag.indexing.bm25_index import BM25Index
from app.technology_rag.indexing.chunker import load_chunks
from app.technology_rag.indexing.embedder import Embedder
from app.technology_rag.indexing.tokenizer import KiwiTokenizer, load_user_dict
from app.technology_rag.indexing.vector_store import build_store, fingerprint


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--strategies", nargs="+", default=None, help="기본: 설정 파일의 전략 하나")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    base = load_config(args.config)
    strategies = args.strategies or [base.chunking.strategy]
    embedder = Embedder(base.embedding, base.embedding_cache_path)
    ok = True

    for strategy in strategies:
        cfg = base.model_copy(deep=True)
        cfg.chunking.strategy = strategy
        print(f"\n{'=' * 70}\n[{cfg.chunking.tag}] {cfg.collection_name}")

        chunks = load_chunks(cfg.chunks_path)
        print(f"  청크 {len(chunks)}건  ← {cfg.chunks_path.name}")

        # --- BM25 ---
        t = time.time()
        tok = KiwiTokenizer(
            min_len=cfg.tokenizer.min_len, keep_verbs=cfg.tokenizer.keep_verbs,
            char_bigrams=cfg.tokenizer.char_bigrams, user_words=load_user_dict(cfg.user_dict_path),
        )
        BM25Index(tok).fit(chunks).save(cfg.bm25_path)
        print(f"  BM25   저장 {cfg.bm25_path.name} ({time.time() - t:.1f}s, 사전 {len(tok.user_words)}단어)")

        # --- 임베딩 + 벡터 저장소 ---
        store = build_store(cfg.index.backend, cfg.chroma_path, cfg.collection_name)
        fp = fingerprint(chunks, cfg.embedding.model)
        if store.is_fresh(chunks, fp) and not args.force:
            print(f"  벡터   최신 상태 ({store.count()}건) — 건너뜀")
            continue
        t = time.time()
        vectors, n_new = embedder.encode([c.text for c in chunks])
        embedder.save_cache()
        over = sum(1 for c in chunks if embedder.token_length(c.text) > embedder.max_seq_length)
        store.rebuild(chunks, vectors, fp)
        print(f"  벡터   {store.count()}건 적재 (새 임베딩 {n_new}건, {time.time() - t:.1f}s, "
              f"dim={vectors.shape[1]}, 입력한도 초과 {over}건)")
        if store.count() != len(chunks) or over:
            ok = False

    print("\n" + "=" * 70)
    print("✅ 인덱스 생성 완료" if ok else "❌ 적재 수 불일치 또는 입력 한도 초과")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
