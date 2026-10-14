"""
★ Technology RAG (A 모듈) 진입점 — 팀 통합은 이 파일만 보면 된다.

    from app.technology_rag import TechnologyRagPipeline
    pipe = TechnologyRagPipeline.from_config()     # 설정·인덱스 로드 (모델은 지연 로딩)
    result = pipe.search("작업자와 지게차가 함께 다니는 공장에서 충돌을 줄이고 싶다")
    result.candidates[0].doc_id, result.hits[0].rerank_score

반환형은 `app.common.schemas.ModuleResult` 로, B(NTIS)·C(RFP)·integration 이 공유하는 계약이다.

검색 흐름
---------
    query ─┬─ BM25 (Kiwi)        top 50 ┐
           └─ Dense (BGE-m3-ko)  top 50 ┴─ RRF 융합 ─ 리랭커(상위 50) ─ 문서 단위 집계 ─ top 10
                                                                                    │
                                                            ModuleResult(hits, candidates)

두 가지 진입점
----------------
search(query)  검색만. hits(청크 단위 전 점수)·candidates(문서 식별정보·점수)·stats 를 채운다.
               candidates[].relation_summary / tech_elements / evidences 는 **비어 있다**.
answer(query)  search 결과 상위 기술의 문서 전체를 LLM 에 주고, 인용을 코드로 검증한 뒤
               위 빈 필드를 채워 돌려준다 (`generation/`). OpenAI 키가 필요하며 `dry_run=True` 면 호출 없이 프롬프트만 만든다.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Mapping, Sequence

from app.common.schemas import ExternalTechCandidate, ModuleResult, RetrievalHit, TechTaxonomy
from app.technology_rag.schemas import Chunk, TechDocument
from app.technology_rag.config import TechnologyRagConfig, load_config
from app.technology_rag.indexing.bm25_index import BM25Index
from app.technology_rag.indexing.chunker import load_chunks
from app.technology_rag.indexing.embedder import Embedder
from app.technology_rag.indexing.vector_store import VectorStore, build_store
from app.technology_rag.retrieval.dense import DenseRetriever
from app.technology_rag.retrieval.hybrid import HybridRetriever, aggregate_to_docs
from app.technology_rag.retrieval.reranker import Reranker
from app.technology_rag.retrieval.types import DocHit, Hit

log = logging.getLogger(__name__)

RETRIEVER_NAMES = {True: "hybrid_rerank", False: "hybrid"}


class TechnologyRagPipeline:
    """기술나눔 591건에 대한 검색 파이프라인."""

    def __init__(
        self,
        config: TechnologyRagConfig,
        chunks: Sequence[Chunk],
        bm25: BM25Index,
        store: VectorStore,
        embedder: Embedder,
        documents: Mapping[str, TechDocument] | None = None,
    ) -> None:
        self.config = config
        self.chunks = list(chunks)
        self.chunk_map: dict[str, Chunk] = {c.chunk_id: c for c in self.chunks}
        self.documents = dict(documents or {})
        self.bm25 = bm25
        self.embedder = embedder
        self.dense = DenseRetriever(embedder, store)
        self.hybrid = HybridRetriever(
            bm25, self.dense, self.chunk_map,
            fusion=config.retrieval.fusion,
            bm25_top_k=config.retrieval.bm25_top_k,
            dense_top_k=config.retrieval.dense_top_k,
            rrf_k=config.retrieval.rrf_k,
            weights=config.retrieval.weights,
        )
        self.reranker = Reranker(config.rerank) if config.rerank.enabled else None
        self._generator = None   # answer() 를 처음 부를 때 만든다 (openai 는 그때까지 import 하지 않는다)

    # ------------------------------------------------------------------ 생성
    @classmethod
    def from_config(
        cls,
        config: TechnologyRagConfig | str | Path | None = None,
        *,
        load_documents: bool = True,
    ) -> "TechnologyRagPipeline":
        """설정과 이미 만들어진 인덱스를 읽어 파이프라인을 만든다.

        인덱스가 없으면 `python -m app.technology_rag.scripts.build_index` 를 먼저 실행해야 한다.
        무거운 모델(임베딩·리랭커)은 첫 검색 때 로드된다.
        """
        cfg = config if isinstance(config, TechnologyRagConfig) else load_config(config)

        from app.common.embedding import require_model
        require_model(cfg.embedding.model)
        if cfg.index.backend == 'supabase':
            from app.common.embedding import get_embedder
            from app.common.supabase_store import SupabaseRepository
            from app.technology_rag.indexing.tokenizer import KiwiTokenizer, load_user_dict
            rows, chunk_rows, payload = SupabaseRepository().snapshot('technology')
            if payload.get('chunking') != cfg.chunking.model_dump():
                raise ValueError('기술나눔 청킹 설정이 Supabase와 다릅니다. 동일 설정으로 적재하세요.')
            from app.technology_rag.schemas import Chunk
            chunks = [Chunk.model_validate(row['payload']) for row in chunk_rows]
            documents = {row['document_id']: TechDocument.model_validate(row['payload']) for row in rows}
            tok = KiwiTokenizer(min_len=cfg.tokenizer.min_len,keep_verbs=cfg.tokenizer.keep_verbs,
                                char_bigrams=cfg.tokenizer.char_bigrams,user_words=load_user_dict(cfg.user_dict_path))
            return cls(cfg,chunks,BM25Index(tok).fit(chunks),
                       build_store('supabase',cfg.chroma_path,cfg.collection_name),get_embedder(),documents)

        chunks = load_chunks(cfg.chunks_path)
        if not cfg.bm25_path.exists():
            raise FileNotFoundError(f"{cfg.bm25_path} 가 없습니다. python -m app.technology_rag.scripts.build_index 를 먼저 실행하세요.")
        bm25 = BM25Index.load(cfg.bm25_path)
        if len(bm25) != len(chunks):
            raise RuntimeError(
                f"BM25 인덱스({len(bm25)}건)와 청크({len(chunks)}건) 수가 다릅니다. 인덱스를 다시 만드세요."
            )

        store = build_store(cfg.index.backend, cfg.chroma_path, cfg.collection_name)
        if store.count() != len(chunks):
            raise RuntimeError(
                f"컬렉션 {cfg.collection_name}({store.count()}건)과 청크({len(chunks)}건) 수가 다릅니다. "
                "인덱스를 다시 만드세요."
            )

        documents: dict[str, TechDocument] = {}
        if load_documents and cfg.documents_path.exists():
            with cfg.documents_path.open(encoding="utf-8") as f:
                documents = {
                    d.doc_id: d for d in (TechDocument.model_validate_json(l) for l in f if l.strip())
                }

        return cls(cfg, chunks, bm25, store,
                   Embedder(cfg.embedding, cfg.embedding_cache_path), documents)

    # ------------------------------------------------------------------ 검색
    def search(
        self,
        query: str,
        *,
        top_docs: int | None = None,
        where: dict | None = None,
        use_reranker: bool | None = None,
    ) -> ModuleResult:
        """기술문제 → 외부기술 후보.

        Args:
            query: 사용자 입력(보유기술 + 기술문제) 또는 Cascade 로 확장된 질의
            top_docs: 반환할 기술 수 (기본: 설정값 10)
            where: 메타데이터 필터. 예) {"transfer_condition": "통상실시"}
            use_reranker: 설정을 무시하고 끄거나 켠다 (실험용)
        """
        t0 = time.perf_counter()
        rerank_on = self.config.rerank.enabled if use_reranker is None else use_reranker
        top_docs = top_docs or self.config.retrieval.top_docs

        fused, detail = self.hybrid.search(query, where=where)
        bm25_scores = {h.chunk_id: h.score for h in self.bm25.search(query, self.config.retrieval.bm25_top_k)}

        final: Sequence[Hit] = fused
        rerank_scores: dict[str, float] = {}
        if rerank_on and self.reranker is not None:
            final = self.reranker.rerank(query, fused, self.chunk_map)
            rerank_scores = {h.chunk_id: h.score for h in final}

        doc_hits = aggregate_to_docs(final, self.chunk_map, self.config.retrieval.aggregate)[:top_docs]
        rrf_scores = {h.chunk_id: h.score for h in fused}

        hits = [
            self._to_retrieval_hit(h, detail, bm25_scores, rrf_scores, rerank_scores, rerank_on)
            for h in final[: self.config.rerank.pool]
        ]
        candidates = [self._to_candidate(d) for d in doc_hits]

        top_score = final[0].score if final else None
        threshold = self.config.rerank.min_score
        return ModuleResult(
            module="technology",
            query=query,
            query_expansion=[],
            candidates=candidates,
            tech_elements=[],  # 생성 단계에서 채운다
            hits=hits,
            stats={
                "strategy": self.config.chunking.tag,
                "collection": self.config.collection_name,
                "fusion": self.config.retrieval.fusion,
                "reranked": rerank_on,
                "n_chunks_searched": len(self.chunks),
                "n_fused": len(fused),
                "top_score": top_score,
                # 근거부족 판정용. min_score 가 null 이면 판정하지 않고 None 을 돌려준다.
                "below_threshold": (None if threshold is None or top_score is None
                                    else top_score < threshold),
                "elapsed_sec": round(time.perf_counter() - t0, 3),
                "generation_implemented": False,   # search() 결과 기준. answer() 가 돌려주는 result 에서는 True
            },
        )

    # ------------------------------------------------------------------ 생성
    def answer(
        self,
        query: str,
        *,
        where: dict | None = None,
        use_reranker: bool | None = None,
        dry_run: bool = False,
        n_docs: int | None = None,
        client=None,
    ):
        """검색 → 상위 `llm.n_docs` 기술의 **문서 전체**를 LLM 에 제공 → 답변 → 인용 검증.

        반환 `GenerationResult`:
          .answer / .verdict        최종 답변과, 코드 검증 후의 판정 (검증된 근거가 없으면 no_answer 로 강등)
          .references               참고한 문서·인용·검증 결과(✅/❌)·원문 위치(페이지·섹션·bbox)
          .result                   검증을 통과한 evidences·tech_elements 가 채워진 ModuleResult (팀 통합 계약)

        Args:
            dry_run: True 면 API 를 호출하지 않고 LLM 에 보낼 프롬프트만 만든다 (키 없이 확인 가능)
            n_docs: 이번 호출에서 LLM 에게 문서 전체를 줄 기술 수 (기본: 설정 `llm.n_docs`)
            client: 테스트용 가짜 OpenAI 클라이언트
        """
        from app.technology_rag.generation import Generator, LLMClient   # 지연 import

        search = self.search(query, where=where, use_reranker=use_reranker)
        if client is not None:                        # 테스트: 캐시하지 않고 그 클라이언트만 쓴다
            gen = Generator(self.config.llm, LLMClient(self.config.llm, client))
        else:
            if self._generator is None:
                self._generator = Generator(self.config.llm)
            gen = self._generator
        return gen.run(query, search, self.documents, dry_run=dry_run, n_docs=n_docs)

    # ------------------------------------------------------------------ 변환
    def _to_retrieval_hit(self, h, detail, bm25_scores, rrf_scores, rerank_scores, rerank_on) -> RetrievalHit:
        c = self.chunk_map[h.chunk_id]
        ranks = detail.get(h.chunk_id, {})
        return RetrievalHit(
            chunk_id=c.chunk_id,
            doc_id=c.parent_doc_id,
            source=c.source,
            section_key=c.section_key,
            text=c.text,
            bm25_score=bm25_scores.get(c.chunk_id),
            bm25_rank=ranks.get("bm25"),
            dense_rank=ranks.get("dense"),
            rrf_score=rrf_scores.get(c.chunk_id),
            rerank_score=rerank_scores.get(c.chunk_id),
            final_rank=h.rank,
            retriever=RETRIEVER_NAMES[rerank_on],
        )

    def _to_candidate(self, d: DocHit) -> ExternalTechCandidate:
        doc = self.documents.get(d.doc_id)
        meta = self.chunk_map[d.best_chunk_id].metadata
        return ExternalTechCandidate(
            doc_id=d.doc_id,
            title=doc.title if doc else meta.get("title", ""),
            provider=doc.provider if doc else meta.get("provider"),
            taxonomy=doc.taxonomy if doc else TechTaxonomy(
                major=meta.get("major"), middle=meta.get("middle"), minor=meta.get("minor")),
            transfer_condition=(doc.transfer_condition.value if doc else
                                meta.get("transfer_condition", "미상")),
            relevance_score=d.score,
            relation_summary="",   # ↓ 아래 세 필드는 생성 단계(LLM)에서 채운다
            tech_elements=[],
            evidences=[],
            hits=[],
        )

    # ------------------------------------------------------------------ 편의
    def document(self, doc_id: str) -> TechDocument | None:
        return self.documents.get(doc_id)

    def chunk(self, chunk_id: str) -> Chunk:
        return self.chunk_map[chunk_id]

    def __repr__(self) -> str:
        return (f"TechnologyRagPipeline(strategy={self.config.chunking.tag!r}, "
                f"chunks={len(self.chunks)}, docs={len(self.documents)}, "
                f"rerank={self.config.rerank.enabled})")
