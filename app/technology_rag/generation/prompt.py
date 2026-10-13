"""
프롬프트.

설계 원칙
---------
- LLM 에게 **문서 전체**(6개 섹션)를 준다. 검색은 청크로 정확히 찾지만, 기술요소를 빠뜨리지 않으려면
  문서 전체를 읽혀야 한다 (이 코퍼스는 문서가 짧아 평균 1,000~1,800자라 가능하다).
- "문서에 없는 것은 쓰지 말라", "관련 문서가 없으면 없다고 하라"를 가장 먼저 못 박는다.
  검색은 항상 상위 N건을 돌려주므로, 코퍼스에 없는 주제에도 엉뚱한 문서가 입력된다.
- 인용(quote)은 **한 글자도 바꾸지 말고 복사**하게 한다. 코드가 글자 단위로 대조하기 때문이다.

프롬프트를 고치면 답변 품질이 바뀌므로, 고친 뒤에는 평가셋으로 다시 확인할 것.
"""

from __future__ import annotations

from typing import Sequence

from app.technology_rag.schemas import TechDocument

SYSTEM_PROMPT = """당신은 제조·자동화 기업의 기술기획을 돕는 분석가입니다.
사용자의 [기술문제]와, 검색으로 찾은 [문서]들이 주어집니다. 반드시 아래 규칙을 지키세요.

1. [문서]에 적힌 내용만 근거로 답합니다. 문서에 없는 내용은 추측하지 말고 gaps 에 적습니다.
2. 문서가 문제를 해결한다고 단정하지 마세요. 문서에 적힌 효과와 적용 범위만 서술하고, 도입 가능성·성능 보장은 말하지 않습니다.
3. 관련 있는 문서가 하나도 없으면 verdict 는 "no_answer", references 와 tech_elements 는 빈 목록으로 두고,
   answer 에는 관련 기술을 찾지 못했다고만 씁니다. 억지로 연결하지 마세요.
4. 문서가 문제의 일부만 다루면 verdict 는 "partial" 로 하고, 다루지 못한 부분을 gaps 에 적습니다.
5. quote 는 문서 본문에 있는 문장을 한 글자도 바꾸지 말고 그대로 복사합니다. 요약·번역·재작성 금지.
   여러 문장을 합치지 말고 한 문장만 고르세요.
6. doc_id 는 [문서]에 주어진 것만 사용합니다. 주어진 순서는 검색 순위일 뿐 관련도를 보증하지 않으니 직접 판단하세요.
7. answer 는 한국어로, 어떤 문서(doc_id)의 어떤 기술이 문제의 어느 부분과 연결되는지 중심으로 간결하게 씁니다.
   answer 안에서 문서 문장을 큰따옴표로 인용할 때도 원문 그대로 복사하세요."""


def doc_block(index: int, doc: TechDocument) -> str:
    """문서 1건을 프롬프트 블록으로. 본문은 6개 섹션 전체(`full_text`)."""
    p = doc.patent
    return (
        f"=== 문서 {index} ===\n"
        f"doc_id: {doc.doc_id}\n"
        f"제공기관: {doc.provider} | 분류: {doc.taxonomy.major} > {doc.taxonomy.middle} > {doc.taxonomy.minor}\n"
        f"이전조건: {doc.transfer_condition.value} | 권리만료: {p.expiry_date}\n"
        f"본문:\n{doc.full_text}\n"
    )


def build_messages(query: str, docs: Sequence[TechDocument]) -> list[dict]:
    body = "\n".join(doc_block(i, d) for i, d in enumerate(docs, 1))
    user = f"[기술문제]\n{query}\n\n[문서] (검색 순위순, 총 {len(docs)}건)\n{body}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
