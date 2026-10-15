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

from pydantic import BaseModel, Field

from app.common.schemas import ModuleResult

Verdict = Literal["answerable", "partial", "no_answer"]
MatchLevel = Literal["full", "similar"]


# =============================================================================
# 1. LLM 이 돌려주는 형식
# =============================================================================

class QueryAnalysis(BaseModel):
    """사용자 문장을 '이미 보유한 기술(A)'과 '확보하려는 기술(B)'로 나눈 결과 (질의 분해 LLM 응답)."""

    owned_technologies: list[str] = Field(description="이미 보유하고 있다고 말한 기술들")
    goal: str = Field(description="개발하려는 제품·프로젝트")
    target: str = Field(description="새로 확보하려는 기술(B). 기능과 적용대상을 포함한 하나의 명사구")
    search_terms: list[str] = Field(description="B를 나눔기술 문서에서 찾기 위한 검색어 (동의어·상하위 표현). 보유기술명 제외")

    def retrieval_query(self) -> str:
        """검색에 쓰는 질의. 보유기술(A)과 최종 제품은 넣지 않는다."""
        terms = [t.strip() for t in self.search_terms if t.strip()]
        return "\n".join(part for part in (self.target.strip(), " / ".join(terms)) if part)


class DocMatch(BaseModel):
    """B와 같거나 유사하다고 판정한 문서 1건. 무관한 문서는 목록에 넣지 않는다."""

    doc_id: str = Field(description="제공된 문서의 doc_id. 제공되지 않은 것은 쓰지 말 것")
    # 필드 순서가 생성 순서다. 이유를 먼저 쓰게 해서 이유와 모순되는 level을 줄인다.
    reason: str = Field(description="B가 요구하는 기능과 문서가 서술한 기능을 비교한 한두 문장")
    difference: str = Field(description="B와 다른 점 (적용 대상·설치 환경·센싱 원리·범위). 없으면 '없음'")
    applicable_to_target: bool = Field(
        description="문서의 기술이 B의 적용 대상·환경(예: 지중 매설 배관)에 적용하거나 응용할 수 있는 구조인가. "
                    "기능 이름만 같고 대상이 다른 공정·설비 전용 기술이면 false"
    )
    level: MatchLevel = Field(description="full=B의 핵심 기능을 직접 서술 / similar=B의 일부·인접 기능을 명시적으로 서술")
    quote: str = Field(description="판단 근거가 된, 문서 본문의 문장을 한 글자도 바꾸지 말고 그대로 복사 (한 문장)")


class TechElementOut(BaseModel):
    name: str = Field(description="기술요소 명칭 (짧은 명사구)")
    function: str = Field(description="그 기술요소가 하는 일")
    source_doc_id: str
    quote: str = Field(description="문서 본문의 문장을 그대로 복사")


class LLMAnswer(BaseModel):
    verdict: Verdict = Field(
        description="answerable=full 매칭 있음 / partial=similar 매칭만 있음 / no_answer=매칭 없음"
    )
    answer: str = Field(description="기술기획 담당자에게 주는 한국어 답변. 문서에 적힌 내용만 사용")
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
    level: str | None = None            # full | similar
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
    verdict: Verdict                    # 코드 검증 후 최종 판정 (근거가 없으면 no_answer 로 강등)
    downgrade_note: str = ""
    gaps: list[str] = Field(default_factory=list)

    references: list[VerifiedReference] = Field(default_factory=list)
    tech_elements: list[VerifiedElement] = Field(default_factory=list)
    answer_quotes: list[AnswerQuote] = Field(default_factory=list)

    provided_doc_ids: list[str] = Field(default_factory=list)   # LLM 에게 문서 전체를 준 기술들
    n_verified: int = 0
    unsupported_rate: float = 0.0       # 검증 실패한 참고문헌 비율 (PRD: Unsupported Claim Rate)
    usage: Usage = Field(default_factory=Usage)

    #: 검증을 통과한 full/similar 매칭이 하나라도 있는가 ("B와 같거나 유사한 나눔기술이 있는가"의 답)
    has_match: bool = False
    query_analysis: QueryAnalysis | None = None   # 질의 분해 결과 (실패·비활성이면 None → 원문 질의로 검색)
    retrieval_query: str = ""                     # 실제로 검색에 쓴 질의
    dropped_doc_ids: list[str] = Field(default_factory=list)   # LLM 에게 줬지만 매칭에서 탈락한 문서

    #: True 면 API 를 호출하지 않았다 (프롬프트 확인용). answer 는 비어 있다.
    dry_run: bool = False
    messages: list[dict] | None = None  # dry_run 일 때 LLM 에 보냈을 프롬프트
