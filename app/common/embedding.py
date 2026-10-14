"""The embedding contract shared by every corpus and every query."""
from functools import lru_cache
import os

MODEL = "dragonkue/BGE-m3-ko"
DIMENSION = 1024
PROFILE = "bgem3ko-normalized-v1"


def require_model(value):
    if value != MODEL:
        raise ValueError(f"임베딩 모델은 {MODEL}로 통일되었습니다. 이전 모델 설정·인덱스를 갱신하세요.")
    return value


@lru_cache(maxsize=1)
def get_embedder():
    from dotenv import load_dotenv
    from app.common.paths import PROJECT_ROOT
    from app.technology_rag.config import EmbeddingConfig
    from app.technology_rag.indexing.embedder import Embedder
    load_dotenv(PROJECT_ROOT / ".env")
    config = EmbeddingConfig(model=MODEL, device=os.getenv("RAG_EMBEDDING_DEVICE", "auto"),
                             batch_size=int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "8")))
    # Existing Technology cache uses the same model+text key and normalized vectors.
    return Embedder(config, PROJECT_ROOT / "storage/embeddings/bgem3ko.npz")


def langchain_embeddings():
    from langchain_core.embeddings import Embeddings

    class SharedEmbeddings(Embeddings):
        def embed_documents(self, texts):
            vectors, _ = get_embedder().encode(texts)
            get_embedder().save_cache()
            return vectors.tolist()

        def embed_query(self, text):
            return get_embedder().encode_query(text).tolist()

    return SharedEmbeddings()
