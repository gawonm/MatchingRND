import json
import os
from pathlib import Path

from dotenv import load_dotenv
from app.common.paths import PROJECT_ROOT, NTIS_DATA_PATH, NTIS_INDEX_DIR, resolve_project_path

ROOT = PROJECT_ROOT
load_dotenv(ROOT / ".env")

DATA_PATH = resolve_project_path(os.getenv("NTIS_DATA_PATH", NTIS_DATA_PATH))
INDEX_DIR = resolve_project_path(os.getenv("NTIS_INDEX_DIR", NTIS_INDEX_DIR))
MANIFEST_PATH = INDEX_DIR / "manifest.json"

RERANKER_MODEL = os.getenv("NTIS_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
LLM_MODEL = os.getenv("NTIS_LLM_MODEL", "gpt-4.1-mini")

DENSE_K = int(os.getenv("NTIS_DENSE_K", "30"))
BM25_K = int(os.getenv("NTIS_BM25_K", "30"))
RRF_K = int(os.getenv("NTIS_RRF_K", "60"))
RERANK_CANDIDATES = int(os.getenv("NTIS_RERANK_CANDIDATES", "20"))
ANALYSIS_TOP_N = int(os.getenv("NTIS_ANALYSIS_TOP_N", "10"))


def load_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(
            f"인덱스 manifest가 없습니다: {MANIFEST_PATH}. "
            "python -m app.ntis_rag.build_index 를 먼저 실행하세요."
        )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"지원하지 않는 manifest schema: {manifest.get('schema_version')}")
    return manifest
