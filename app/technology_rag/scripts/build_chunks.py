r"""
tech_documents.jsonl → data/processed/chunks_{strategy}.jsonl  (전략별)

실행:
    .venv\Scripts\python.exe -X utf8 -m app.technology_rag.scripts.build_chunks
    .venv\Scripts\python.exe -X utf8 -m app.technology_rag.scripts.build_chunks --strategies section_group
"""

from __future__ import annotations

import argparse
import sys

from app.technology_rag.paths import PROJECT_ROOT
from app.technology_rag.schemas import TechDocument
from app.technology_rag.indexing.chunker import available_strategies, get_chunker

ROOT = PROJECT_ROOT   # app.technology_rag.paths — TECHRAG_ROOT 로 바꿀 수 있다
DOCS = ROOT / "data" / "processed" / "tech_documents.jsonl"
OUT_DIR = ROOT / "data" / "processed"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", nargs="+", default=available_strategies())
    ap.add_argument("--no-prefix", action="store_true", help="기술명/섹션명 prefix 없이 (비교 실험용)")
    args = ap.parse_args()

    with DOCS.open(encoding="utf-8") as f:
        docs = [TechDocument.model_validate_json(l) for l in f if l.strip()]
    print(f"문서 {len(docs)}건 로드")

    for name in args.strategies:
        chunker = get_chunker(name, include_title_prefix=not args.no_prefix)
        chunks = chunker.chunk_all(docs)
        out = OUT_DIR / f"chunks_{chunker.strategy_tag.replace('+', '_')}.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(c.model_dump_json() + "\n")
        n_ids = len({c.chunk_id for c in chunks})
        n_docs = len({c.parent_doc_id for c in chunks})
        print(f"[{chunker.strategy_tag:<14}] {len(chunks):>5}청크  문서 {n_docs}  id유일 {n_ids == len(chunks)}"
              f"  → {out.name} ({out.stat().st_size / 1e6:.1f} MB)")
        if n_ids != len(chunks) or n_docs != len(docs):
            print("  ❌ 청크 id 중복 또는 문서 누락")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
