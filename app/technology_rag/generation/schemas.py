"""
생성 단계의 자료형.

두 종류가 있다.
  1. LLM 이 돌려주는 형식  : `LLMAnswer` 와 그 하위 모델  (OpenAI Structured Outputs 스키마가 된다)
  2. 코드가 검증한 뒤의 결과: `GenerationResult`            (`pipe.answer()` 의 반환)

팀 공용 계약(`app/common/schemas.py`)은 바꾸지 않는다. 검증된 근거·기술요소는
`ModuleResult.candidates[]` 의 기존 필드(`evidences`, `tech_elements`, `relation_summary`)를 채우고,
답변 본문·판정·비용처럼 공용 계약에 없는 것은 `GenerationResult` 가 들고 있다.

주의 (Structured Outputs strict 모드): LLM 출력 모델은 **모든 필드가 필수**여야 하고 기본값을 둘 수 없다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.common.schemas import ModuleResult

Verdict = Literal["same", "similar", "none"]      # 문서 전체 중 가장 높은 등급 (same > similar > none)
MatchLevel = Literal["same", "similar"]           # 문서별 등급. 매칭 안 됨(none)은 목록에서 빠진다


# =============================================================================
# 1. LLM 이 돌려주는 형식
# =============================================================================

def _as_list(value) -> list[str]:
    """문자열 하나 또는 목록을 받아 공백을 정리하고 중복·빈 항목을 뺀 목록으로 만든다."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else list(value)
    return list(dict.fromkeys(s.strip() for s in items if isinstance(s, str) and s.strip()))


class TechInput(BaseModel):
    """Technology RAG 입력. 상류에서 이미 나뉘어 온 '보유기술(A)'과 '원하는 기술(B)'.

    검색과 매칭 판정은 B 에 대해서만 한다. A 는 '이미 가진 기술(매칭 근거가 아님)'로 판정 단계에만 전달한다.
    """

    owned_technologies: list[str] = Field(default_factory=list, description="이미 보유한 기술들 (A)")
    targets: list[str] = Field(description="새로 확보하려는 기술들 (B). 하나 이상")
    search_terms: list[str] = Field(default_factory=list, description="B 의 동의어·상하위 표현 (선택). 보유기술명 제외")

    @field_validator("owned_technologies", "targets", "search_terms", mode="before")
    @classmethod
    def _clean(cls, value):
        return _as_list(value)

    @field_validator("targets")
    @classmethod
    def _targets_required(cls, value):
        if not value:
            raise ValueError("원하는 기술(B)이 비어 있습니다. 하나 이상 입력하세요.")
        return value

    def retrieval_query(self) -> str:
        """검색에 쓰는 질의. 보유기술(A)은 넣지 않는다."""
        return "\n".join(part for part in (" / ".join(self.targets), " / ".join(self.search_terms)) if part)


class DocMatch(BaseModel):
    """B와 같거나 유사하다고 판정한 문서 1건. 무관한 문서는 목록에 넣지 않는다."""

    doc_id: str = Field(description="제공된 문서의 doc_id. 제공되지 않은 것은 쓰지 말 것")
    matched_target: str = Field(description="B 목록 중 이 문서가 가장 잘 대응하는 항목을 한 글자도 바꾸지 말고 그대로 복사")
    # 필드 순서가 생성 순서다. 이유를 먼저 쓰게 해서 이유와 모순되는 level을 줄인다.
    reason: str = Field(description="B가 요구하는 기능과 문서가 서술한 기능을 비교한 한두 문장")
    difference: str = Field(description="B와 다른 점 (적용 대상·설치 환경·센싱 원리·범위). 없으면 '없음'")
    applicable_to_target: bool = Field(
        description="문서의 기술이 B의 적용 대상·환경(예: 지중 매설 배관)에 적용하거나 응용할 수 있는 구조인가. "
                    "기능 이름만 같고 대상이 다른 공정·설비 전용 기술이면 false"
    )
    level: MatchLevel = Field(description="same=B의 핵심 기능을 직접 서술 / similar=B의 일부·인접 기능을 명시적으로 서술")
    quote: str = Field(description="판단 근거가 된, 문서 본문의 문장을 한 글자도 바꾸지 말고 그대로 복사 (한 문장, 최소 8자 이상)")


class TechElementOut(BaseModel):
    name: str = Field(description="기술요소 명칭 (짧은 명사구)")
    function: str = Field(description="그 기술요소가 하는 일")
    source_doc_id: str
    quote: str = Field(description="문서 본문의 문장을 그대로 복사")


class DocJudgment(BaseModel):
    """제공된 문서 1건마다 빠짐없이 내리는 판정. none 도 이유를 남겨 조용한 누락을 막는다."""

    doc_id: str = Field(description="제공된 문서의 doc_id. 제공된 문서마다 정확히 하나씩")
    reason: str = Field(description="문서가 서술한 기능과 B의 구성 기능을 비교한 한 문장. none 이면 왜 B의 어떤 기능도 서술하지 않는지")
    level: Verdict = Field(description="same | similar | none. same/similar 이면 matches 에도 반드시 넣는다")


class LLMAnswer(BaseModel):
    verdict: Verdict = Field(
        description="same=same 매칭 있음 / similar=similar 매칭만 있음 / none=매칭 없음"
    )
    answer: str = Field(description="기술기획 담당자에게 주는 한국어 답변. 문서에 적힌 내용만 사용")
    # 필드 순서가 생성 순서다. 모든 문서를 먼저 판정하게 한 뒤 matches 를 쓴다.
    judgments: list[DocJudgment] = Field(description="제공된 모든 문서에 대한 판정 (문서 수와 같아야 한다)")
    matches: list[DocMatch]
    tech_elements: list[TechElementOut]
    gaps: list[str] = Field(description="B 중 제공된 문서에서 확인되지 않은 부분")


# =============================================================================
# 2. 코드가 검증한 뒤의 결과
# =============================================================================

class Usage(BaseModel):
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0   # 설정의 단가로 계산한 추정치


class VerifiedReference(BaseModel):
    """LLM 이 낸 참고문헌 1건 + 코드의 검증 결과."""

    doc_id: str
    role: str
    why: str
    quote: str
    ok: bool
    reason: str                         # 일치 | 제공 안 한 문서 | 본문에 없음 | 너무 짧음 | 분야 고유 표현 불일치
    level: str | None = None            # same | similar
    matched_target: str | None = None   # 이 문서가 대응하는 B 항목 (B 가 하나면 그 항목)
    difference: str = ""                # B와 다른 점 (LLM 서술)
    section: str | None = None
    page: int | None = None             # 0-based
    bbox: tuple[float, float, float, float] | None = None
    search_rank: int | None = None      # 검색 결과에서 몇 위였는지


class VerifiedElement(BaseModel):
    name: str
    function: str
    source_doc_id: str
    quote: str
    ok: bool
    reason: str
    section: str | None = None
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None


class AnswerQuote(BaseModel):
    """답변 본문 속 따옴표 문장의 검증 결과 (본문에 숨은 환각 탐지용)."""

    text: str
    ok: bool
    doc_id: str | None = None           # 찾은 문서


class GenerationResult(BaseModel):
    """`TechnologyRagPipeline.answer()` 의 반환."""

    #: 검증을 통과한 근거·기술요소가 채워진 ModuleResult. 팀 통합 계약은 이것이다.
    result: ModuleResult

    answer: str
    llm_verdict: Verdict                # LLM 이 말한 판정
    verdict: Verdict                    # 코드 검증 후 최종 판정 (근거가 없으면 none 으로 강등)
    downgrade_note: str = ""
    gaps: list[str] = Field(default_factory=list)

    references: list[VerifiedReference] = Field(default_factory=list)
    tech_elements: list[VerifiedElement] = Field(default_factory=list)
    answer_quotes: list[AnswerQuote] = Field(default_factory=list)

    provided_doc_ids: list[str] = Field(default_factory=list)   # LLM 에게 문서 전체를 준 기술들
    n_verified: int = 0
    unsupported_rate: float = 0.0       # 검증 실패한 참고문헌 비율 (PRD: Unsupported Claim Rate)
    usage: Usage = Field(default_factory=Usage)

    #: 검증을 통과한 same/similar 매칭이 하나라도 있는가 ("B와 같거나 유사한 나눔기술이 있는가"의 답)
    has_match: bool = False
    tech_input: TechInput | None = None           # 입력으로 받은 보유기술(A)·원하는 기술(B)·검색어
    retrieval_query: str = ""                     # 실제로 검색에 쓴 질의
    dropped_doc_ids: list[str] = Field(default_factory=list)   # LLM 에게 줬지만 매칭에서 탈락한 문서

    #: True 면 API 를 호출하지 않았다 (프롬프트 확인용). answer 는 비어 있다.
    dry_run: bool = False
    messages: list[dict] | None = None  # dry_run 일 때 LLM 에 보냈을 프롬프트
