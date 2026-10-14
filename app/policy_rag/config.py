"""Policy paths and environment configuration."""
import os
from pathlib import Path
from app.common.validation import _positive_int
from app.common.paths import PROJECT_ROOT, POLICY_RAW_DIR


def load_config(data_dir=None, output_dir=None, *, model_name=None):
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
    data_dir = Path(data_dir) if data_dir is not None else POLICY_RAW_DIR
    data_dir = (PROJECT_ROOT / data_dir).resolve() if not data_dir.is_absolute() else data_dir.resolve()
    OUTPUT = Path(output_dir) if output_dir is not None else Path('db/law')
    OUTPUT = (PROJECT_ROOT / OUTPUT).resolve() if not OUTPUT.is_absolute() else OUTPUT.resolve()
    pdf_files = sorted(data_dir.rglob('*.pdf'))
    if not pdf_files:
        raise ValueError(f'검색할 PDF가 없습니다: {data_dir}')
    (OUTPUT / 'cache').mkdir(parents=True, exist_ok=True)
    root = data_dir
    from app.common.embedding import MODEL as SHARED_MODEL, require_model
    MODEL = require_model(model_name or os.getenv('LAW_EMBEDDING_MODEL', SHARED_MODEL))
    CHUNK_TOKENS = _positive_int(os.getenv('LAW_CHUNK_TOKENS', '1000'), 'LAW_CHUNK_TOKENS')
    OVERLAP_TOKENS = _positive_int(os.getenv('LAW_OVERLAP_TOKENS', '80'), 'LAW_OVERLAP_TOKENS', 0)
    KEYWORD_K = _positive_int(os.getenv('LAW_KEYWORD_CANDIDATES', '30'), 'LAW_KEYWORD_CANDIDATES')
    VECTOR_K = _positive_int(os.getenv('LAW_VECTOR_CANDIDATES', '30'), 'LAW_VECTOR_CANDIDATES')
    TOP_K = _positive_int(os.getenv('LAW_TOP_K', '5'), 'LAW_TOP_K')
    RRF_K = _positive_int(os.getenv('LAW_RRF_K', '60'), 'LAW_RRF_K')
    CONTEXT_TOKENS = _positive_int(os.getenv('LAW_CONTEXT_TOKENS', '4000'), 'LAW_CONTEXT_TOKENS')
    MODEL = model_name or os.getenv('LAW_EMBEDDING_MODEL', MODEL)
    return {key: value for key, value in locals().items() if key in {'data_dir', 'OUTPUT', 'pdf_files', 'MODEL', 'CHUNK_TOKENS', 'OVERLAP_TOKENS', 'KEYWORD_K', 'VECTOR_K', 'TOP_K', 'RRF_K', 'CONTEXT_TOKENS'}}
