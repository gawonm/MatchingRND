"""기존 Chroma/BM25 인덱스 로드 → Dense + BM25 → RRF → CrossEncoder rerank."""
import hashlib
import json
import pickle
from collections import defaultdict
from typing import Any, Dict, List, Sequence

import numpy as np
from kiwipiepy import Kiwi
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from sentence_transformers import CrossEncoder

from .config import (
    ANALYSIS_TOP_N,
    BM25_K,
    DENSE_K,
    INDEX_DIR,
    RERANK_CANDIDATES,
    RERANKER_MODEL,
    RRF_K,
    load_manifest,
)

# ==================================================
# 인덱스 로드 (manifest가 단일 설정 소스)
# ==================================================
manifest = load_manifest()

CHROMA_DIR = INDEX_DIR / manifest["chroma"]["path"]
BM25_PATH = INDEX_DIR / manifest["bm25"]["path"]
COLLECTION_NAME = manifest["chroma"]["collection"]
EMBEDDING_MODEL = manifest["embedding_model"]
TOKENIZER_NAME = manifest["bm25"]["tokenizer"]

if not CHROMA_DIR.is_dir():
    raise FileNotFoundError(f"Chroma 인덱스가 없습니다: {CHROMA_DIR}")
if not BM25_PATH.is_file():
    raise FileNotFoundError(f"BM25 인덱스가 없습니다: {BM25_PATH}")
if TOKENIZER_NAME != "kiwi.form.v1":
    raise ValueError(f"지원하지 않는 BM25 tokenizer: {TOKENIZER_NAME}")

embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
vectorstore = Chroma(
    collection_name=COLLECTION_NAME,
    persist_directory=str(CHROMA_DIR),
    embedding_function=embeddings,
)

# pickle은 신뢰할 수 있는 로컬 구축 산출물에만 사용한다.
with BM25_PATH.open("rb") as file:
    bm25_payload = pickle.load(file)

if not isinstance(bm25_payload, dict):
    raise TypeError("BM25 payload는 build_index가 저장한 dict 형식이어야 합니다.")
bm25_index = bm25_payload.get("bm25_index")
bm25_documents = bm25_payload.get("documents")
if bm25_index is None or not hasattr(bm25_index, "get_scores"):
    raise TypeError("BM25 payload에서 get_scores() 가능한 인덱스를 찾지 못했습니다.")
if bm25_documents is None:
    raise TypeError("BM25 payload에 Document 목록이 없습니다.")

bm25_documents = list(bm25_documents)
expected_count = int(manifest["document_count"])
actual_counts = {
    "chroma": vectorstore._collection.count(),
    "bm25": len(bm25_documents),
}
if any(count != expected_count for count in actual_counts.values()):
    raise ValueError(f"인덱스 문서 수 불일치: expected={expected_count}, actual={actual_counts}")

kiwi = Kiwi()
reranker = CrossEncoder(RERANKER_MODEL)


def kiwi_tokenize(text: str) -> List[str]:
    return [token.form for token in kiwi.tokenize(text)]


# ==================================================
# 공통 문서 형식과 안정적인 과제 식별자
# ==================================================
def doc_text(doc: Any) -> str:
    if hasattr(doc, "page_content"):
        return str(doc.page_content)
    if isinstance(doc, dict):
        return str(doc.get("page_content") or doc.get("content") or doc.get("text") or "")
    return str(doc)


def doc_metadata(doc: Any) -> Dict[str, Any]:
    if hasattr(doc, "metadata"):
        return dict(doc.metadata or {})
    if isinstance(doc, dict):
        return dict(doc.get("metadata") or {})
    return {}


def project_key(doc: Any) -> str:
    metadata = doc_metadata(doc)
    if metadata.get("project_id"):
        return str(metadata["project_id"])
    stable_text = json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n" + doc_text(doc)
    return "sha256::" + hashlib.sha256(stable_text.encode("utf-8")).hexdigest()


# ==================================================
# Dense + BM25 검색
# ==================================================
def dense_search(query: str, k: int = DENSE_K) -> List[Dict[str, Any]]:
    rows = vectorstore.similarity_search_with_score(query, k=k)
    return [
        {"key": project_key(doc), "doc": doc, "raw_score": float(score), "rank": rank}
        for rank, (doc, score) in enumerate(rows, start=1)
    ]


def bm25_search(query: str, k: int = BM25_K) -> List[Dict[str, Any]]:
    scores = bm25_index.get_scores(kiwi_tokenize(query))
    top_indices = np.argsort(scores)[::-1][:k]
    return [
        {
            "key": project_key(bm25_documents[index]),
            "doc": bm25_documents[index],
            "raw_score": float(scores[index]),
            "rank": rank,
        }
        for rank, index in enumerate(top_indices, start=1)
    ]


# ==================================================
# Reciprocal Rank Fusion
# ==================================================
def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[Dict[str, Any]]],
    rrf_k: int = RRF_K,
    limit: int = RERANK_CANDIDATES,
) -> List[Dict[str, Any]]:
    scores = defaultdict(float)
    best_docs = {}
    source_ranks = defaultdict(dict)
    source_names = ["dense", "bm25"]

    for source_index, results in enumerate(ranked_lists):
        source = source_names[source_index]
        seen = set()
        for item in results:
            key = item["key"]
            if key in seen:
                continue
            seen.add(key)
            scores[key] += 1.0 / (rrf_k + item["rank"])
            source_ranks[key][source] = item["rank"]
            best_docs.setdefault(key, item["doc"])

    ordered_keys = sorted(scores, key=scores.get, reverse=True)[:limit]
    return [
        {
            "key": key,
            "doc": best_docs[key],
            "rrf_score": scores[key],
            "source_ranks": source_ranks[key],
        }
        for key in ordered_keys
    ]


# ==================================================
# CrossEncoder reranking
# ==================================================
def rerank(
    query: str,
    candidates: Sequence[Dict[str, Any]],
    top_n: int = ANALYSIS_TOP_N,
) -> List[Dict[str, Any]]:
    if not candidates:
        return []
    pairs = [(query, doc_text(item["doc"])) for item in candidates]
    scores = reranker.predict(pairs)
    enriched = [
        {**item, "rerank_score": float(score)}
        for item, score in zip(candidates, scores)
    ]
    enriched.sort(key=lambda item: item["rerank_score"], reverse=True)
    selected = enriched[:top_n]
    for rank, item in enumerate(selected, start=1):
        item["final_rank"] = rank
    return selected


# ==================================================
# 통합 retrieval
# ==================================================
def project_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    metadata = doc_metadata(item["doc"])
    return {
        "project_id": item["key"],
        "project_title": metadata.get("project_title"),
        "organization": metadata.get("research_agency"),
        "text": doc_text(item["doc"]),
        "metadata": metadata,
        "rank": item["final_rank"],
        "rrf_score": item["rrf_score"],
        "rerank_score": item["rerank_score"],
        "source_ranks": dict(item["source_ranks"]),
    }


def retrieve_ntis(structured_query: Dict[str, Any], analysis_top_n: int) -> List[Dict[str, Any]]:
    query = structured_query["search_query"]
    dense_results = dense_search(query, k=max(DENSE_K, analysis_top_n))
    bm25_results = bm25_search(query, k=max(BM25_K, analysis_top_n))
    fused = reciprocal_rank_fusion(
        [dense_results, bm25_results],
        limit=max(RERANK_CANDIDATES, analysis_top_n),
    )
    ranked = rerank(query, fused, top_n=analysis_top_n)
    return [project_summary(item) for item in ranked]
