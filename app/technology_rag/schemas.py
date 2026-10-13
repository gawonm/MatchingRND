"""
Technology RAG(A) 전용 데이터 모델 — 기술나눔 PDF의 구조를 그대로 옮긴 것.

팀 공용 계약(`app/common/schemas.py`)과 달리 B(NTIS)·C(RFP)는 쓰지 않는다.
공용 계약과의 연결점은 두 가지뿐이다.
  - `SectionCode.value` (str)  → `Evidence.section`
  - `TransferCondition.value` (str) → `ExternalTechCandidate.transfer_condition`
공용 쪽은 이 파일의 enum 을 import 하지 않고 문자열로 받는다 (공용 → A 역방향 의존 없음).

ID 규칙
-------
doc_id    : "{source}-{year}-{seq:03d}"      예) "pub-2026-001", "pos-2025-001"
chunk_id  : "{doc_id}#{section_key}#{idx}"   예) "pub-2026-001#overview+problem#0"
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas import BBox, SourceType, TechTaxonomy


class SectionCode(StrEnum):
    """기술나눔 기술소개자료 PDF의 6개 섹션.

    PDF에서 섹션 제목이 '이미지'로 렌더링되어 텍스트로 추출되지 않는다.
    따라서 제목 이미지의 md5 digest로 섹션을 식별한다.
    매핑 테이블: app/technology_rag/constants.py:SECTION_BANNERS
    """

    OVERVIEW = "overview"          # 기술 개요
    PROBLEM = "problem"            # 산업계 문제 해결 포인트
    STRENGTH = "strength"          # 기술의 강점 및 차별성
    APPLICATION = "application"    # 주요 적용 산업 및 활용처
    COMPOSITION = "composition"    # 기술의 구성 및 특징
    MARKET = "market"              # 시장성 및 사업화 가능성
    META = "meta"                  # 표지 영역(기술명/분류/출원정보) — 검색 대상 아님

class TransferCondition(StrEnum):
    """이전조건. 공공기관 목록 엑셀에만 존재(통상실시 280 / 양도 18)."""

    NON_EXCLUSIVE = "통상실시"
    ASSIGNMENT = "양도"
    UNKNOWN = "미상"

class TextBlock(BaseModel):
    """PDF에서 추출한 텍스트 블록 1개.

    bbox를 파싱 시점에 반드시 보존한다. 나중에 복원할 수 없고,
    Evidence의 원문 복귀(PRD 수용기준 7-2)가 여기에 의존한다.
    """

    page: int = Field(description="PDF 물리 페이지 번호 (0-based)")
    bbox: BBox
    text: str
    order: int = Field(description="페이지 내 읽기 순서 (y, x 정렬)")

class PatentInfo(BaseModel):
    """특허 서지정보. 출원번호가 PDF↔엑셀 조인 키."""

    application_number: str | None = Field(
        default=None, description="정규화된 13자리 숫자. 예) '1020080054298'"
    )
    application_number_raw: str | None = Field(
        default=None, description="원문 표기. 예) '10-2008-0054298'"
    )
    application_date: date | None = None
    registration_number: str | None = None
    registration_number_raw: str | None = None
    registration_date: date | None = None
    expiry_date: date | None = Field(default=None, description="존속기간 만료일")
    country: str | None = "KR"
    ipc: list[str] = Field(default_factory=list)

    @field_validator("application_number", "registration_number", mode="before")
    @classmethod
    def _digits_only(cls, v: Any) -> str | None:
        """'10-2008-0054298' / 1020080054298 / '10-2008-0054298 ' 를 모두 흡수."""
        if v is None:
            return None
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        return digits or None

class Section(BaseModel):
    """기술 1건 안의 섹션 1개."""

    code: SectionCode
    title: str = Field(description="사람이 읽는 섹션명. 예) '기술 개요'")
    text: str = Field(description="블록을 읽기 순서로 join 한 본문")
    blocks: list[TextBlock] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

class TechDocument(BaseModel):
    """기술나눔 기술 1건 = 검색/판정의 기본 단위 (총 591건).

    PDF 본문을 주 내용으로 하고, 엑셀은 PDF에 없는 메타데이터만 보강한다.
    본문이 겹칠 경우 PDF 우선 (plan.md 설계 결정).
    """

    model_config = ConfigDict(use_enum_values=False)

    doc_id: str
    source: SourceType
    seq_no: str = Field(description="자료집 내 일련번호. 예) '001'")

    title: str
    subtitle: str | None = Field(default=None, description="PDF 기술명 아래 괄호 부제")
    provider: str | None = Field(
        default=None, description="제공기관. PDF 러닝헤더 또는 엑셀에서 추출"
    )
    taxonomy: TechTaxonomy = Field(default_factory=TechTaxonomy)
    inventors: list[str] = Field(default_factory=list)
    patent: PatentInfo = Field(default_factory=PatentInfo)

    # --- 엑셀 보강 메타 ---
    transfer_condition: TransferCondition = TransferCondition.UNKNOWN
    sharing_start: date | None = None
    sharing_end: date | None = None
    applicant: str | None = Field(default=None, description="출원인(포스코 목록에만 일부)")
    manager_org: str | None = Field(default=None, description="나눔관리기관명")

    # --- 원문 위치 ---
    pdf_path: str
    page_start: int = Field(description="0-based, 레코드 첫 페이지")
    page_end: int = Field(description="0-based, 레코드 마지막 페이지(포함)")

    sections: list[Section] = Field(default_factory=list)

    # --- 추적용 ---
    excel_joined: bool = Field(
        default=False, description="출원번호로 엑셀 레코드와 조인에 성공했는지"
    )
    extra: dict[str, Any] = Field(
        default_factory=dict, description="출처별 비공통 필드 원본 보관"
    )

    def section(self, code: SectionCode) -> Section | None:
        return next((s for s in self.sections if s.code == code), None)

    @property
    def full_text(self) -> str:
        """기술당 1청크(doc 전략)에서 사용할 본문."""
        parts = [f"[{s.title}]\n{s.text}" for s in self.sections if not s.is_empty]
        return f"{self.title}\n{self.subtitle or ''}\n\n" + "\n\n".join(parts)

class Chunk(BaseModel):
    """임베딩/BM25 색인의 최소 단위.

    parent_doc_id를 항상 유지한다. 섹션 단위로 검색하고 기술 단위로 집계하는
    parent-child 구조가 가능해지고, 청킹 전략 비교 실험의 비교축이 된다.

    청킹 전략에 따라 한 청크가 담는 섹션이 다르다.
        doc            : section_key="doc",              sections=[6개 전부]
        section        : section_key="overview",         sections=[OVERVIEW]
        section_group  : section_key="overview+problem", sections=[OVERVIEW, PROBLEM]
    """

    chunk_id: str
    parent_doc_id: str
    source: SourceType
    section_key: str = Field(description="'doc' | 섹션코드 | '코드+코드' (chunk_id 의 일부)")
    sections: list[SectionCode] = Field(description="이 청크에 포함된 섹션들(읽는 순서)")
    text: str = Field(description="임베딩/BM25에 들어가는 최종 문자열")
    token_len: int | None = None

    page_start: int
    page_end: int
    blocks: list[TextBlock] = Field(
        default_factory=list,
        description="청크에 포함된 원문 항목들. Evidence 의 page/bbox 복원에 쓴다.",
    )

    strategy: str = Field(description="생성 전략. 예) 'doc' | 'section' | 'section_group'")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Chroma where 필터용 평탄화 메타 (None 값은 넣지 않는다)",
    )
