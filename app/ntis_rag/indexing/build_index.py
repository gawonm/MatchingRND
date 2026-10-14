"""NTIS 원문(xlsx) → Chroma + BM25 인덱스 최초 1회 구축.

실행: python -m app.ntis_rag.scripts.build_index
"""
import hashlib
import json
import os
import pickle
from pathlib import Path

from kiwipiepy import Kiwi
from langchain_chroma import Chroma
from langchain_core.documents import Document
from app.common.embedding import MODEL, require_model, langchain_embeddings
from rank_bm25 import BM25Okapi

from ..config import DATA_PATH, INDEX_DIR, MANIFEST_PATH
from ..parsing.excel_loader import load_documents, SEARCH_FIELDS

CHROMA_DIR = INDEX_DIR / "chroma"
BM25_PATH = INDEX_DIR / "ntis_bm25.pkl"

COLLECTION_NAME = os.getenv("NTIS_CHROMA_COLLECTION", "ntis_projects")
EMBEDDING_MODEL = require_model(os.getenv("NTIS_EMBEDDING_MODEL", MODEL))

TOKENIZER_NAME = "kiwi.form.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not DATA_PATH.is_file():
        raise FileNotFoundError(f"NTIS 원문 파일이 없습니다: {DATA_PATH}")

    existing_outputs = [p for p in (CHROMA_DIR, BM25_PATH, MANIFEST_PATH) if p.exists()]
    if existing_outputs:
        paths = "\n  - ".join(str(p) for p in existing_outputs)
        raise FileExistsError(
            "기존 인덱스 산출물을 발견해 중단했습니다. 자동 덮어쓰기는 지원하지 않습니다."
            f"\n  - {paths}"
        )
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    documents = load_documents(DATA_PATH, Document)

    document_ids = [d.metadata["project_id"] for d in documents]
    if not documents:
        raise ValueError("인덱싱할 Document가 없습니다.")
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("과제번호가 중복되어 Chroma ID로 사용할 수 없습니다.")

    # Chroma
    embeddings = langchain_embeddings()
    vectorstore = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        ids=document_ids,
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
    )
    chroma_count = vectorstore._collection.count()
    if chroma_count != len(documents):
        raise RuntimeError(f"Chroma 문서 수 불일치: {chroma_count} != {len(documents)}")

    # BM25
    kiwi = Kiwi()
    tokenized_corpus = [
        [token.form for token in kiwi.tokenize(d.page_content)] for d in documents
    ]
    bm25_index = BM25Okapi(tokenized_corpus)
    with BM25_PATH.open("wb") as file:
        pickle.dump(
            {"bm25_index": bm25_index, "documents": documents, "tokenizer": TOKENIZER_NAME},
            file,
            protocol=pickle.HIGHEST_PROTOCOL,
        )

    # Manifest
    manifest = {
        "schema_version": 1,
        "source": {"path": str(DATA_PATH), "sha256": sha256(DATA_PATH)},
        "document_count": len(documents),
        "chroma": {"path": "chroma", "collection": COLLECTION_NAME},
        "bm25": {"path": BM25_PATH.name, "tokenizer": TOKENIZER_NAME},
        "embedding_model": EMBEDDING_MODEL,
        "search_fields": SEARCH_FIELDS,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
