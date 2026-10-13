"""Compatibility CLI; prefer python -m app.ntis_rag.scripts.build_index."""
from .indexing.build_index import main, sha256
from .parsing.excel_loader import clean_text, make_search_text, scalar_metadata

if __name__ == "__main__":
    main()
