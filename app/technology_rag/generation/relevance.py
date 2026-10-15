"""
분야 고유 표현 겹침 검사 — LLM 이 similar/full 을 줘도 B 와 말만 비슷한 문서를 코드로 한 번 더 거른다.

"진단·제어·시스템" 같은 일반 공정 용어는 거의 모든 설비 기술 설명에 나오므로, 이를 지우고 남는
분야 고유 표현(예: '접지압', '제설', '작업부')의 글자쌍이 B(및 검색어)와 근거 문장 사이에 몇 개 겹치는지 센다.
추가 LLM 호출이 없다. 한계: 동의어를 못 잡을 수 있으므로 검색어(search_terms)를 함께 비교하고,
하한(`min_term_overlap`)은 설정으로 조절한다.
"""

from __future__ import annotations

import re
from typing import Iterable

GENERIC_WORDS = (
    "기술", "시스템", "장치", "설비", "플랫폼", "솔루션", "체계", "구조",
    "진단", "감시", "모니터링", "관리", "평가", "측정", "시험", "검사", "분석",
    "제어", "운영", "자동", "실시간", "최적화", "통합", "구축", "개발", "확보",
    "적용", "활용", "구현", "제공", "지원", "성능", "데이터", "설계", "제작",
)
_GENERIC = re.compile("|".join(re.escape(w) for w in GENERIC_WORDS))
_NON_WORD = re.compile(r"[^0-9A-Za-z가-힣]")


def domain_bigrams(texts: Iterable[str | None]) -> set[str]:
    """일반 용어를 지우고 남는 단어별 글자 bigram. 단어 경계를 넘는 글자쌍은 만들지 않는다."""
    grams: set[str] = set()
    for text in texts:
        if not text:
            continue
        for word in _GENERIC.sub(" ", text).split():
            word = _NON_WORD.sub("", word).casefold()
            grams.update(word[i:i + 2] for i in range(len(word) - 1))
    return grams


def term_overlap(terms: Iterable[str | None], texts: Iterable[str | None]) -> int:
    """B·검색어(terms)와 근거 문장(texts)이 공유하는 분야 고유 글자쌍 수."""
    return len(domain_bigrams(terms) & domain_bigrams(texts))
