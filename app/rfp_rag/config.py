"""RFP paths, section constants and environment configuration."""
import os
from pathlib import Path
from app.common.validation import _positive_int
from app.common.paths import PROJECT_ROOT, RFP_PDF_DIR

TECHNICAL_SECTIONS = (
    '개발목표', '개발내용', '요구기술', '적용대상', '성능지표',
    '실증조건', '연구개발범위', '평가방법·평가조건',
)
CONTEXT_SECTIONS = TECHNICAL_SECTIONS + ('지원기간', '지원금액', '지원조건·특이사항')


def load_config(data_dir=None, output_dir=None, *, model_name=None):
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
    data_dir = Path(data_dir) if data_dir is not None else RFP_PDF_DIR
    data_dir = (PROJECT_ROOT / data_dir).resolve() if not data_dir.is_absolute() else data_dir.resolve()
    OUTPUT = Path(output_dir) if output_dir is not None else Path('db/rfp')
    OUTPUT = (PROJECT_ROOT / OUTPUT).resolve() if not OUTPUT.is_absolute() else OUTPUT.resolve()
    pdf_files = sorted(data_dir.rglob('*.pdf'))
    if not pdf_files:
        raise ValueError(f'검색할 PDF가 없습니다: {data_dir}')
    (OUTPUT / 'cache').mkdir(parents=True, exist_ok=True)
    EMBEDDING_MODEL = os.getenv('RFP_EMBEDDING_MODEL', 'BAAI/bge-m3')
    CHUNK_TOKENS = _positive_int(os.getenv('RFP_CHUNK_TOKENS', '1400'), 'RFP_CHUNK_TOKENS')
    OVERLAP_TOKENS = _positive_int(os.getenv('RFP_OVERLAP_TOKENS', '100'), 'RFP_OVERLAP_TOKENS', 0)
    KEYWORD_K = _positive_int(os.getenv('RFP_KEYWORD_CANDIDATES', '30'), 'RFP_KEYWORD_CANDIDATES')
    VECTOR_K = _positive_int(os.getenv('RFP_VECTOR_CANDIDATES', '30'), 'RFP_VECTOR_CANDIDATES')
    TOP_K = _positive_int(os.getenv('RFP_TOP_K', '5'), 'RFP_TOP_K')
    RRF_K = _positive_int(os.getenv('RFP_RRF_K', '60'), 'RFP_RRF_K')
    CONTEXT_TOKENS = _positive_int(os.getenv('RFP_CONTEXT_TOKENS', '3500'), 'RFP_CONTEXT_TOKENS')
    if not (CHUNK_TOKENS > 300 and 0 <= OVERLAP_TOKENS < CHUNK_TOKENS - 200):
        raise ValueError('Invalid RAG configuration.')
    EMBEDDING_MODEL = model_name or os.getenv('RFP_EMBEDDING_MODEL', EMBEDDING_MODEL)
    return {key: value for key, value in locals().items() if key in {'data_dir', 'OUTPUT', 'pdf_files', 'EMBEDDING_MODEL', 'CHUNK_TOKENS', 'OVERLAP_TOKENS', 'KEYWORD_K', 'VECTOR_K', 'TOP_K', 'RRF_K', 'CONTEXT_TOKENS'}}
