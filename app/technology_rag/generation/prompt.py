"""
프롬프트.

설계 원칙
---------
- 목적은 "사용자가 확보하려는 기술(B)과 같거나 유사한 나눔기술이 있는가"에 답하는 것이다.
  문서마다 B 의 기능과 비교해 same/similar 만 남기고, 무관한 문서는 목록에서 뺀다(탈락).
- 이미 보유한 기술(A)은 매칭 근거가 아니다. A 와 비슷하다는 이유로 문서를 고르지 않게 못 박는다.
- LLM 에게 **문서 전체**(6개 섹션)를 준다 (이 코퍼스는 문서가 짧아 평균 1,000~1,800자).
- 인용(quote)은 **한 글자도 바꾸지 말고 복사**하게 한다. 코드가 글자 단위로 대조하기 때문이다.

프롬프트를 고치면 판정 품질이 바뀌므로, 고친 뒤에는 평가셋/스모크 테스트로 다시 확인할 것.
"""

from __future__ import annotations

from typing import Sequence

from app.technology_rag.generation.schemas import TechInput
from app.technology_rag.schemas import TechDocument

SYSTEM_PROMPT = """당신은 제조·자동화 기업의 기술기획을 돕는 분석가입니다.
사용자가 확보하려는 기술(B)과 같거나 유사한 기술나눔 문서만 골라냅니다. [확보하려는 기술(B)], [이미 보유한 기술(A)]와 검색으로 찾은 [문서]들이 주어집니다. B 는 하나 이상일 수 있고, 문서가 B 항목 중 하나라도 충족하면 대응하는 것으로 봅니다.

1. 판단 기준은 B 가 요구하는 구체적 기능입니다. 문서 본문이 그 기능을 명시적으로 서술하는지 비교하세요.
2. 이미 보유한 기술(A)은 이미 가진 기술입니다. 문서가 A 와 비슷하다는 이유로 고르지 마세요. B 와 분야(자율주행·센서·제설 등)만 같거나 키워드만 비슷한 문서도 해당하지 않습니다.
3. level: same = 문서가 B 의 핵심 기능을 B 와 같은 적용 대상·환경에서 직접 서술함. similar = B 를 이루는 기능·구성요소 중 하나 이상(예: 측정, 보정, 제어, 열회수, 감지)이나 같은 센싱·제어 원리를, B 와 같은 산업·설비 영역에서 B 의 목적에 쓸 수 있는 구조로 문서가 명시적으로 서술함. B 의 핵심 기능 전체가 아니어도, 대상·범위·성능·제목이 일반적이어도 됩니다.
   기능 이름(예: '누수 감지', '압력 조정')만 같고 문서가 전혀 다른 공정·설비 전용(예: 도금 설비, 열교환기, 반도체 장비)이어서 B 의 적용 대상에 쓸 수 없다면 similar 가 아니라 관련 없음이며, matches 에 넣지 마세요.
4. B 와 관련 없는 문서(none)는 matches 에 넣지 않습니다(탈락). 단, 문서가 B 를 이루는 기능 중 하나라도 본문에서 명시적으로 서술하면 B 의 나머지 기능이 없다는 이유만으로 빼지 말고 similar 로 포함하세요(difference 에 빠진 부분을 적습니다). B 의 어떤 기능도 본문에 서술되어 있지 않아 reason 을 '관련성이 없다'로 쓰게 된다면 그 문서는 matches 에서 빼야 합니다.
5. matches 의 reason 에 'B 가 요구하는 기능'과 '문서가 명시적으로 서술한 기능'을 먼저 비교해 쓰고, difference 에 B 와 다른 점(적용 대상·환경·원리·범위)을 쓴 뒤, applicable_to_target 에 문서의 기술을 B 의 적용 대상·환경에 적용·응용할 수 있는지(true/false)를 정하고, 그 결론에 맞게 level 을 정하세요. applicable_to_target 이 false 인 문서는 matches 에 넣지 않는 것이 원칙입니다.
6. quote 는 판단 근거가 된 문서 본문의 문장을 한 글자도 바꾸지 말고 그대로 복사합니다(한 문장, 요약·번역·재작성 금지).
7. 문서에 적힌 내용만 근거로 하고 추측하지 마세요. 도입 가능성·성능 보장은 말하지 않습니다.
8. 매칭이 하나도 없으면 verdict 는 "none", matches 와 tech_elements 는 빈 목록으로 두고, answer 에는 B 와 같거나 유사한 나눔기술을 찾지 못했다고만 쓰세요. 억지로 연결하지 마세요.
9. verdict: same 매칭이 있으면 "same", similar 매칭만 있으면 "similar", 없으면 "none". B 중 문서에서 확인되지 않은 부분은 gaps 에 적습니다.
10. tech_elements 는 matches 에 넣은 문서에서 B 와 관련된 기술요소만 적습니다. source_doc_id 와 quote 는 같은 문서의 것이어야 합니다.
11. doc_id 는 [문서]에 주어진 것만 사용합니다. 문서 순서는 검색 순위일 뿐 관련도를 보증하지 않으니 직접 판단하세요.
12. matched_target 에는 B 목록 중 문서가 가장 잘 대응하는 항목을 그대로 복사합니다. B 가 하나면 그 항목입니다.
13. answer 는 한국어로, 어떤 문서(doc_id)의 어떤 기술이 B 의 어느 부분과 연결되는지 간결하게 씁니다. 따옴표로 문서 문장을 인용할 때도 원문 그대로 복사하세요."""

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


def build_messages(inp: TechInput, docs: Sequence[TechDocument]) -> list[dict]:
    body = "\n".join(doc_block(i, d) for i, d in enumerate(docs, 1))
    targets = "\n".join(f"- {name}" for name in inp.targets)
    owned = "\n".join(f"- {name}" for name in inp.owned_technologies) or "- (없음)"
    user = (
        f"[확보하려는 기술(B)]\n{targets}\n\n"
        f"[이미 보유한 기술(A) — 매칭 근거가 아님]\n{owned}\n\n"
        f"[문서] (검색 순위순, 총 {len(docs)}건)\n{body}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
