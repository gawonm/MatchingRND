"""
기술나눔 목록 엑셀 2종 → ExcelRecord (출원번호 키).

- 공공기관: 2. 2026년 공공기관 기술나눔 목록(298건).xlsx  (결측 없음, 이전조건 포함)
- 포스코  : 나눔기술.xls                                  (본문 필드 거의 비어 있음)

두 소스의 컬럼 체계가 달라 canonical 필드로 통일한다. 본문(초록/배경기술 등)은
포스코 엑셀에 293건 중 2~12건만 값이 있어 사용하지 않고 `raw`에만 보관한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from app.common.schemas import SourceType
from app.technology_rag.schemas import TransferCondition
from app.technology_rag.text import normalize_application_number, parse_date
from app.technology_rag import constants as C


@dataclass(slots=True)
class ExcelRecord:
    source: SourceType
    application_number: str                      # 정규화(숫자 13자리) — 조인 키
    row_id: str                                  # 엑셀 내 번호(일련번호/나눔번호)
    title: str | None = None
    provider: str | None = None
    major: str | None = None
    middle: str | None = None
    minor: str | None = None
    country: str | None = None
    application_date: date | None = None
    registration_number: str | None = None
    registration_date: date | None = None
    expiry_date: date | None = None
    transfer_condition: TransferCondition = TransferCondition.UNKNOWN
    ipc: list[str] = field(default_factory=list)
    applicant: str | None = None
    sharing_start: date | None = None
    sharing_end: date | None = None
    manager_org: str | None = None
    #: 정규 필드로 올리지 않는 값 (분류 체계가 다른 대분류, 연락처, 코드 등)
    extra: dict[str, Any] = field(default_factory=dict)


def _s(v: Any) -> str | None:
    """NaN/NaT/빈 문자열 → None, 그 외 문자열."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return None
    t = str(v).strip()
    return t or None


def _split_ipc(v: Any) -> list[str]:
    t = _s(v)
    if not t:
        return []
    return [p.strip() for p in t.replace("|", ";").split(";") if p.strip()]


def _transfer(v: Any) -> TransferCondition:
    t = _s(v)
    for member in TransferCondition:
        if t == member.value:
            return member
    return TransferCondition.UNKNOWN


def _public_row(r: pd.Series, app: str) -> ExcelRecord:
    return ExcelRecord(
        source=SourceType.PUBLIC_TECH,
        application_number=app,
        row_id=f"{int(r['일련번호']):03d}",
        title=_s(r["기술명"]),
        provider=_s(r["제공기관"]),
        major=_s(r["대분류"]),
        middle=_s(r["중분류"]),
        minor=_s(r["소분류"]),
        country=_s(r["출원국가"]),
        application_date=parse_date(r["출원일"]),
        registration_number=normalize_application_number(r["등록번호"]),
        registration_date=parse_date(r["등록일"]),
        expiry_date=parse_date(r["권리만료예상일"]),
        transfer_condition=_transfer(r["이전조건"]),
        extra={
            "application_year": None if pd.isna(r["출원연도"]) else int(r["출원연도"]),
            "expiry_year": None if pd.isna(r["권리만료연도"]) else int(r["권리만료연도"]),
        },
    )


def _posco_row(r: pd.Series, app: str) -> ExcelRecord:
    return ExcelRecord(
        source=SourceType.POSCO_TECH,
        application_number=app,
        row_id=str(_s(r["나눔번호"])),
        title=_s(r["발명의명칭"]),
        application_date=parse_date(r["출원일자"]),
        registration_number=normalize_application_number(r["등록번호"]),
        registration_date=parse_date(r["등록일자"]),
        ipc=_split_ipc(r["IPC"]),
        applicant=_s(r["출원인"]),
        sharing_start=parse_date(r["나눔기간시작"]),
        sharing_end=parse_date(r["나눔기간종료"]),
        manager_org=_s(r["나눔관리기관명"]),
        extra={
            # 포스코 엑셀의 대분류는 PDF의 대분류(첨단로봇·제조/ESG)와 체계가 다르다
            "excel_category": _s(r["대분류"]),
            "excel_category_code": _s(r["대분류코드"]),
            "manager_phone": _s(r["기관전화번호"]),
            "listed_at": _s(r["등록일"]),
        },
    )


_BUILDERS = {
    SourceType.PUBLIC_TECH: _public_row,
    SourceType.POSCO_TECH: _posco_row,
}


def load_excel(source: SourceType, raw_dir: Path) -> dict[str, ExcelRecord]:
    """엑셀을 읽어 {정규화 출원번호: ExcelRecord} 를 반환한다.

    출원번호가 비었거나 중복이면 ValueError (조인 키가 유일해야 한다).
    """
    spec = C.SOURCE_SPECS[source]
    df = pd.read_excel(Path(raw_dir) / spec["excel"], sheet_name=spec["excel_sheet"])
    build = _BUILDERS[source]

    out: dict[str, ExcelRecord] = {}
    for _, r in df.iterrows():
        app = normalize_application_number(r[spec["join_key_excel"]])
        if not app:
            raise ValueError(f"{source.value}: 출원번호 없는 행 {dict(r.head(3))}")
        if app in out:
            raise ValueError(f"{source.value}: 출원번호 중복 {app}")
        out[app] = build(r, app)
    return out
