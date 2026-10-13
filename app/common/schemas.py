"""
공통 데이터 계약 (Data Contract).

4개 RAG 모듈(technology / ntis / rfp / policy)이 공유하는 스키마.
팀 통합 시 이 파일이 모듈 간 인터페이스가 되므로, 모듈 고유 필드는
`extra` 에 넣고 여기 정의된 필드는 함부로 바꾸지 않는다.

모듈 고유 모델은 여기에 두지 않는다. 예) Technology RAG 의 `TechDocument`·`Chunk`·`SectionCode`
→ `app/technology_rag/schemas.py`. 이 파일의 모델은 모듈 고유 enum 을 import 하지 않고
문자열로 받는다 (공용 → 모듈 역방향 의존 금지).

ID 규칙
-------
doc_id    : "{source}-{year}-{seq:03d}"      예) "pub-2026-001", "pos-2025-001"
element_id: "te-{sha1(normalized_name)[:10]}"
(chunk_id 는 모듈 내부 규칙이다 — A: "{doc_id}#{section_key}#{idx}")
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Enum
# =============================================================================

class SourceType(StrEnum):
    """문서 출처. doc_id 접두어와 1:1 대응."""

    PUBLIC_TECH = "pub"      # 2026 공공기관 기술나눔 (298건)
    POSCO_TECH = "pos"       # 2025 포스코그룹 기술나눔 (293건)
    NTIS = "ntis"            # B 담당
    RFP = "rfp"              # C 담당
    POLICY = "policy"        # C 담당
    COMPANY = "company"      # 사용자 입력 보유기술/특허


class GapLabel(StrEnum):
    """Technology Gap 판정 라벨 (PRD 5. 판정 우선순위)."""

    OWNED = "기존보유"
    EXTERNAL = "외부기술보완"
    PARTIAL = "부분충족"
    RND_NEEDED = "추가R&D검토후보"
    INSUFFICIENT = "근거부족"


# =============================================================================
# 원문 위치 / 근거
# =============================================================================

class BBox(BaseModel):
    """PDF 좌표계 기준 사각형. Streamlit에서 원문 하이라이트에 사용."""

    model_config = ConfigDict(frozen=True)

    x0: float
    y0: float
    x1: float
    y1: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


class Evidence(BaseModel):
    """어떤 주장을 뒷받침하는 원문 근거 1건.

    LLM이 생성한 quote는 반드시 CitationValidator로 원문 대조 후 채택한다.
    (app/technology_rag/generation/validation.py — B/C 도 쓰게 되면 공용으로 옮긴다)
    """

    doc_id: str = Field(description="근거가 있는 문서. 근거는 청크가 아니라 문서 기준이다")
    source: SourceType
    section: str | None = Field(
        default=None, description="모듈 고유 섹션 코드 문자열. A 는 SectionCode 값 (예: 'problem')"
    )
    page: int | None = Field(default=None, description="PDF 물리 페이지 (0-based)")
    bbox: BBox | None = None
    quote: str = Field(description="원문에 실제로 존재하는 문자열")
    verified: bool = Field(
        default=False,
        description="quote가 원문 문서에 실제 존재함을 기계적으로 확인했는지",
    )


# =============================================================================
# 기술분류
# =============================================================================

class TechTaxonomy(BaseModel):
    """기술분류 (대/중/소)."""

    major: str | None = None   # 대분류  예) 기계·소재
    middle: str | None = None  # 중분류  예) 자동차/철도차량
    minor: str | None = None   # 소분류  예) 철도 전력 설비


# =============================================================================
# 기술요소 / 검색 결과 (모듈 간 전달 계약)
# =============================================================================

class TechElement(BaseModel):
    """정규화된 기술요소. Cascade 단계 간 전달과 Gap 정렬의 축."""

    element_id: str
    name: str = Field(description="정규화된 대표 기술명")
    surface_forms: list[str] = Field(
        default_factory=list, description="원문에 등장한 표현들"
    )
    synonyms: list[str] = Field(default_factory=list)
    broader: list[str] = Field(default_factory=list, description="상위 개념")
    narrower: list[str] = Field(default_factory=list, description="하위 개념")
    function: str | None = Field(default=None, description="기능")
    target: str | None = Field(default=None, description="적용 대상/환경")

    origin: SourceType = Field(description="이 요소가 추출된 출처")
    evidences: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RetrievalHit(BaseModel):
    """검색 결과 1건. 단계별 점수를 모두 보존해 ablation 분석에 쓴다."""

    chunk_id: str
    doc_id: str
    source: SourceType
    section_key: str | None = None
    text: str

    dense_score: float | None = None
    dense_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    final_rank: int | None = None

    retriever: Literal["dense", "bm25", "hybrid", "hybrid_rerank"] = "hybrid_rerank"


class ExternalTechCandidate(BaseModel):
    """Technology RAG(A)의 최종 출력 단위.

    === 팀 통합 인터페이스 ===
    B(NTIS) / C(RFP)는 이 객체의 `tech_elements`를 다음 단계 Query 확장에 사용한다.
    필드 변경 시 팀 합의 필요.
    """

    doc_id: str
    title: str
    provider: str | None = None
    taxonomy: TechTaxonomy = Field(default_factory=TechTaxonomy)
    transfer_condition: str = Field(
        default="미상", description="이전조건 문자열. A 는 TransferCondition 값 (통상실시/양도/미상)"
    )

    relevance_score: float
    relation_summary: str = Field(description="기술적 연관성 설명 (LLM 생성)")
    tech_elements: list[TechElement] = Field(default_factory=list)
    evidences: list[Evidence] = Field(default_factory=list)
    hits: list[RetrievalHit] = Field(default_factory=list)


class ModuleResult(BaseModel):
    """각 RAG 모듈이 Orchestrator에 반환하는 공통 봉투(envelope).

    A/B/C 모듈이 독립 개발되어도 이 형태만 지키면 integration에서 합쳐진다.
    """

    module: Literal["technology", "ntis", "rfp", "policy"]
    query: str = Field(description="실제 실행된 최종 query")
    query_expansion: list[str] = Field(
        default_factory=list, description="Cascade로 추가된 기술요소 표현"
    )
    candidates: list[ExternalTechCandidate] = Field(default_factory=list)
    tech_elements: list[TechElement] = Field(
        default_factory=list, description="다음 단계로 넘길 기술요소 집합"
    )
    hits: list[RetrievalHit] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
