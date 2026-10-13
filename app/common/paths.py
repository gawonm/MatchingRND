"""Project-relative data locations shared by RAG modules and orchestration."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
EVALUATION_DIR = DATA_DIR / "evaluation"

TECHNOLOGY_RAW_DIR = RAW_DIR / "technology"
TECHNOLOGY_PROCESSED_DIR = PROCESSED_DIR / "technology"
NTIS_DATA_PATH = RAW_DIR / "ntis" / "ntis_projects_2026_mechanical.xlsx"
NTIS_INDEX_DIR = PROCESSED_DIR / "ntis" / "index"
RFP_RAW_DIR = RAW_DIR / "rfp"
RFP_PDF_DIR = RFP_RAW_DIR / "pdf"
RFP_NOTICE_PATH = RFP_RAW_DIR / "RFP_공고목록.xlsx"
POLICY_RAW_DIR = RAW_DIR / "policy"


def resolve_project_path(path: str | Path) -> Path:
    """Resolve relative paths against the repository, independent of the cwd."""
    path = Path(path).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
