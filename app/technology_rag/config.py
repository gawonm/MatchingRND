"""
app/technology_rag/configs/technology_rag.yaml → 타입이 있는 설정 객체.

설정을 코드에 흩어 두지 않고 한 곳에 모으는 이유
  1. 코드 수정 없이 실험 조건(청킹 전략, top-k, 가중치)을 바꾸기 위해
  2. 인덱스가 "어떤 설정으로 만들어졌는지" 이름과 지문으로 추적하기 위해
"""

from __future__ import annotations

from app.common.llm_config import DEFAULT_LLM_MODEL

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from app.technology_rag.paths import resolve
from app.technology_rag.paths import CONFIG_DIR, DEFAULT_CONFIG_PATH


class ChunkingConfig(BaseModel):
    strategy: Literal["doc", "section", "section_group"] = "section_group"
    include_title_prefix: bool = True

    @property
    def tag(self) -> str:
        """전략 식별자. 설정이 다르면 이름도 달라야 인덱스가 섞이지 않는다."""
        return self.strategy if self.include_title_prefix else f"{self.strategy}+noprefix"


def resolve_device(device: str, fp16: bool) -> tuple[str, bool]:
    """`auto` 면 CUDA 가 있을 때 cuda, 없으면 cpu 를 고른다. CPU 에서는 fp16 을 쓰지 않는다(느리거나 오류).

    명시한 `cuda` 는 그대로 존중한다 — GPU 가 없으면 모델 로드 때 오류가 나서 설정 실수를 바로 알 수 있다.
    """
    if device == "auto":
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
    return device, fp16 and device.startswith("cuda")


class EmbeddingConfig(BaseModel):
    model: str = "dragonkue/BGE-m3-ko"
    tag: str = "bgem3ko"
    device: str = "auto"   # auto | cuda | cpu
    fp16: bool = True
    batch_size: int = 16


class TokenizerConfig(BaseModel):
    min_len: int = 2
    keep_verbs: bool = True
    char_bigrams: bool = False
    #: 상대경로면 모듈의 configs/ 에서 먼저 찾고, 없으면 프로젝트 루트 기준으로 찾는다
    user_dict: str = "user_dict.txt"


class RetrievalConfig(BaseModel):
    fusion: Literal["rrf", "ensemble"] = "rrf"
    bm25_top_k: int = 50
    dense_top_k: int = 50
    rrf_k: int = 60
    weights: list[float] = Field(default_factory=lambda: [0.5, 0.5])
    aggregate: Literal["max", "sum"] = "max"
    top_docs: int = 10


class RerankConfig(BaseModel):
    enabled: bool = True
    model: str = "BAAI/bge-reranker-v2-m3"
    device: str = "auto"   # auto | cuda | cpu
    fp16: bool = True
    pool: int = 50
    batch_size: int = 16
    max_length: int = 1024
    min_score: float | None = None


class IndexConfig(BaseModel):
    backend: Literal["chroma", "supabase"] = "chroma"
    persist_dir: str = "storage/chroma"
    embedding_cache_dir: str = "storage/embeddings"
    processed_dir: str = "data/processed/technology"


class LLMConfig(BaseModel):
    """생성 단계(검색된 문서 → 답변 + 검증된 근거)."""

    provider: Literal["openai"] = "openai"
    model: str = DEFAULT_LLM_MODEL
    #: B와 같거나 유사한지 문서별로 판정할 기술 수 (검색 상위 N건, 문서 전체를 LLM 에게 준다). 많을수록 비용이 늘어난다
    judge_docs: int = Field(default=8, ge=1, le=20)
    #: 매칭 근거(인용문+문서명)가 B·검색어와 공유해야 하는 분야 고유 글자쌍 수의 하한. 0 이면 검사하지 않는다
    min_term_overlap: int = Field(default=2, ge=0)
    temperature: float | None = None
    seed: int | None = 0                # 재현성 (best-effort)
    max_output_tokens: int = 3000       # 비용 상한. 매칭된 문서만 출력하므로 보통 ~800 토큰
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=0, ge=0, le=2)
    #: USD / 1M 토큰. 요금은 바뀔 수 있으니 OpenAI 요금표를 확인할 것 (비용 추정에만 쓰인다)
    price_per_1m_input: float = 0.20
    price_per_1m_output: float = 1.20


class TechnologyRagConfig(BaseModel):
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    tokenizer: TokenizerConfig = Field(default_factory=TokenizerConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)

    # ---- 설정에서 파생되는 이름/경로 (한 곳에서만 만든다) ----

    @property
    def collection_name(self) -> str:
        """Chroma 컬렉션 이름. 예) tech_section_group_bgem3ko"""
        return f"tech_{self.chunking.tag.replace('+', '_')}_{self.embedding.tag}"

    @property
    def chunks_path(self) -> Path:
        return resolve(self.index.processed_dir) / f"chunks_{self.chunking.tag.replace('+', '_')}.jsonl"

    @property
    def documents_path(self) -> Path:
        return resolve(self.index.processed_dir) / "tech_documents.jsonl"

    @property
    def bm25_path(self) -> Path:
        tok = "kiwi_bigram" if self.tokenizer.char_bigrams else "kiwi"
        return resolve("storage/bm25") / f"{self.chunking.tag.replace('+', '_')}_{tok}.json"

    @property
    def embedding_cache_path(self) -> Path:
        return resolve(self.index.embedding_cache_dir) / f"{self.embedding.tag}.npz"

    @property
    def chroma_path(self) -> Path:
        return resolve(self.index.persist_dir)

    @property
    def user_dict_path(self) -> Path:
        p = Path(self.tokenizer.user_dict)
        if p.is_absolute():
            return p
        in_module = CONFIG_DIR / p          # 기본: app/technology_rag/configs/<이름>
        return in_module if in_module.exists() else resolve(p)


def load_config(path: str | Path | None = None) -> TechnologyRagConfig:
    """YAML 을 읽어 설정 객체를 만든다.

    - `path` 를 **지정하지 않았고** 기본 yaml 이 없으면 → 코드의 기본값(`TechnologyRagConfig()`)을 쓴다.
      yaml 없이 코드만으로도 동작한다.
    - `path` 를 **지정했는데** 파일이 없으면 → `FileNotFoundError`.
      오타 난 경로가 조용히 기본값으로 대체되면, 실험 설정이 적용됐다고 착각하게 된다.
    """
    explicit = path is not None
    p = Path(path) if explicit else DEFAULT_CONFIG_PATH
    if not p.is_absolute():
        p = resolve(p)
    if not p.exists():
        if explicit:
            raise FileNotFoundError(f"설정 파일이 없습니다: {p}")
        return TechnologyRagConfig()
    return TechnologyRagConfig.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")) or {})
