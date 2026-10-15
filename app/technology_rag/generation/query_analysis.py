"""
질의 분해 — 사용자 문장을 '이미 보유한 기술(A)'과 '확보하려는 기술(B)'로 나눈다 (LLM 1회).

왜 필요한가
-----------
"A·A'를 보유하고 있고 X를 개발하려는데, 이를 위해 B 기술을 확보하고 싶다" 형태의 문장을 그대로 검색하면
A 쪽 표현이 순위를 좌우해서 이미 가진 기술과 비슷한 문서가 올라온다. 찾는 것은 B 이므로
검색에는 B 와 그 동의어만 쓰고, A 는 문서 판정 단계에서 "이미 보유한 기술(매칭 근거 아님)"로만 전달한다.

분해에 실패하거나 target 이 비면 `None` 을 돌려주고, 호출한 쪽이 입력 문장 전체로 검색한다.
"""

from __future__ import annotations

import logging

from app.technology_rag.generation.llm import LLMClient, MissingApiKeyError
from app.technology_rag.generation.prompt import build_analysis_messages
from app.technology_rag.generation.schemas import QueryAnalysis, Usage

log = logging.getLogger(__name__)


def analyze_query(llm: LLMClient, query: str) -> tuple[QueryAnalysis | None, Usage | None]:
    try:
        analysis, usage = llm.ask(build_analysis_messages(query), QueryAnalysis, max_output_tokens=800)
    except MissingApiKeyError:
        raise                                   # 키 문제는 생성 단계에서도 막히므로 숨기지 않는다
    except Exception as error:                  # noqa: BLE001 - 분해 실패가 검색 전체를 막지 않게 한다
        log.warning("질의 분해 실패, 입력 문장 전체로 검색합니다: %s", type(error).__name__)
        return None, None
    if not analysis.target.strip():
        log.warning("질의 분해 결과에 확보하려는 기술(target)이 없어 입력 문장 전체로 검색합니다.")
        return None, usage
    return analysis, usage
