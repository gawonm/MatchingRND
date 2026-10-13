"""
인용 검증 — LLM 이 낸 인용문이 **실제로 원문에 있는지** 코드가 확인한다.

왜 필요한가
-----------
LLM 은 없는 문장을 그럴듯하게 만들어 인용할 수 있다. 이 서비스의 핵심 약속은
"문서에 없는 내용을 근거처럼 제시하지 않는다"(PRD)이므로, 근거로 내보내기 전에
**LLM 이 아닌 코드가** 검증해야 한다. 검증에 실패한 인용은 근거로 채택하지 않고,
검증된 근거가 하나도 없으면 답을 `근거부족`으로 내린다 (generator.py).

이 파일은 다른 모듈에 의존하지 않는 순수 함수다 (TechDocument 만 읽는다).
B(NTIS)·C(RFP)가 같은 검증을 쓰게 되면 `app/common/` 으로 옮기면 된다.

규칙
----
- 비교는 `compact()`(모든 공백 제거). PDF 줄바꿈 복원이 완벽하지 않으므로 공백 차이는 무시한다.
- 공백 제외 8자 미만의 인용은 우연히 일치하기 쉬워 **인정하지 않는다**.
- 인용이 어느 섹션·블록·페이지에 있는지 함께 돌려준다 (원문 하이라이트용).

한계: "그 문장이 원문에 있다"만 보장한다. 문장을 문제와 **잘못 연결**한 것은 잡지 못한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from app.technology_rag.schemas import TechDocument
from app.technology_rag.text import compact

MIN_QUOTE_CHARS = 8

REASON_OK = "일치"
REASON_NOT_PROVIDED = "제공 안 한 문서"
REASON_NOT_FOUND = "본문에 없음"
REASON_TOO_SHORT = "너무 짧음"


@dataclass(frozen=True)
class QuoteCheck:
    """인용 1건의 검증 결과."""

    ok: bool
    reason: str
    section: str | None = None   # SectionCode 값. 블록 경계를 넘는 인용이면 None
    block: int | None = None
    page: int | None = None      # 0-based
    bbox: tuple[float, float, float, float] | None = None


def locate(doc: TechDocument, quote: str) -> QuoteCheck:
    """인용문이 문서의 어느 블록에 있는지."""
    q = compact(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return QuoteCheck(False, REASON_TOO_SHORT)
    for section in doc.sections:
        for i, block in enumerate(section.blocks):
            if q in compact(block.text):
                return QuoteCheck(True, REASON_OK, section.code.value, i, block.page, block.bbox.as_tuple())
    if q in compact(doc.full_text):  # 여러 블록에 걸친 인용: 일치는 인정하되 위치는 모른다
        return QuoteCheck(True, REASON_OK)
    return QuoteCheck(False, REASON_NOT_FOUND)


def check_quote(provided: Mapping[str, TechDocument], doc_id: str, quote: str) -> QuoteCheck:
    """`doc_id` 가 실제로 LLM 에게 준 문서이고, 그 문서에 `quote` 가 있는가."""
    doc = provided.get(doc_id)
    if doc is None:
        return QuoteCheck(False, REASON_NOT_PROVIDED)
    return locate(doc, quote)


def check_anywhere(provided: Mapping[str, TechDocument], quote: str) -> tuple[QuoteCheck, str | None]:
    """어느 문서에든 있는가 (답변 본문 속 따옴표 문장 검증용). (결과, 찾은 doc_id)"""
    last = QuoteCheck(False, REASON_NOT_FOUND)
    for doc_id, doc in provided.items():
        res = locate(doc, quote)
        if res.ok:
            return res, doc_id
        last = res
    return last, None


# 답변 본문의 따옴표 문장: "…", “…”, '…', ‘…’
_QUOTE_RES = (
    re.compile(r'"([^"\n]+)"'),
    re.compile(r"“([^”\n]+)”"),
    re.compile(r"'([^'\n]+)'"),
    re.compile(r"‘([^’\n]+)’"),
)


def find_prose_quotes(text: str) -> list[str]:
    """답변 본문에서 따옴표로 묶인 문장을 찾는다 (공백 제외 8자 이상, 중복 제거, 등장 순서)."""
    found: list[tuple[int, str]] = []
    for rx in _QUOTE_RES:
        for m in rx.finditer(text):
            seg = m.group(1).strip()
            if len(compact(seg)) >= MIN_QUOTE_CHARS:
                found.append((m.start(), seg))
    seen: set[str] = set()
    out: list[str] = []
    for _, seg in sorted(found):
        if seg not in seen:
            seen.add(seg)
            out.append(seg)
    return out
