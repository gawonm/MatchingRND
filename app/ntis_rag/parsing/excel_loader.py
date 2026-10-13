"""NTIS spreadsheet cleanup and document metadata parsing."""
import pandas as pd

PLACEHOLDER = "데이터이관 글자수 검증"
TOKENIZER_NAME = "kiwi.form.v1"

REQUIRED_COLUMNS = ["과제번호", "과제명", "연구목표", "연구내용", "기대효과", "키워드"]
SEARCH_FIELDS = ["과제명", "연구목표", "연구내용", "기대효과", "키워드"]

METADATA_MAP = {
    "과제번호": "project_id",
    "과제명": "project_title",
    "연구수행기관": "research_agency",
    "부처명": "ministry",
    "사업명": "business_name",
    "연구개발단계": "development_phase",
    "과학기술분류1_대": "science_large",
    "과학기술분류1_중": "science_medium",
    "과학기술분류1_소": "science_small",
    "적용분야_1": "apply_area",
}


def clean_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if PLACEHOLDER in text else text

def make_search_text(row: pd.Series) -> str:
    parts = []
    for column in SEARCH_FIELDS:
        text = clean_text(row[column])
        if text:
            parts.append(f"{column}: {text}")
    return "\n".join(parts)

def scalar_metadata(row: pd.Series) -> dict:
    metadata = {}
    for source, target in METADATA_MAP.items():
        if source not in row or pd.isna(row[source]):
            continue
        value = row[source]
        if hasattr(value, "item"):
            value = value.item()
        if not isinstance(value, (str, int, float, bool)):
            value = str(value)
        metadata[target] = value
    metadata["project_id"] = str(metadata["project_id"])
    return metadata

def load_documents(data_path, document_factory):
    df = pd.read_excel(data_path, engine="openpyxl", dtype=str, keep_default_na=False)
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise ValueError(f"필수 컬럼이 없습니다: {missing_columns}")
    df["검색텍스트_clean"] = df.apply(make_search_text, axis=1)
    return [document_factory(page_content=row["검색텍스트_clean"].strip(), metadata=scalar_metadata(row))
            for _, row in df.iterrows() if row["검색텍스트_clean"].strip()]
