"""생성 단계: 검색된 문서를 LLM 에게 주고 답변을 받은 뒤, 인용을 코드로 검증한다.

    pipe.answer("기술문제")  →  GenerationResult     (retrieval/pipeline.py)

`openai` 패키지는 실제로 호출할 때만 필요하다 (이 패키지를 import 해도 불러오지 않는다).
"""

from app.technology_rag.generation.generator import Generator
from app.technology_rag.generation.llm import LLMClient, LLMRefusalError, MissingApiKeyError
from app.technology_rag.generation.schemas import (
    GenerationResult,
    LLMAnswer,
    Reference,
    TechElementOut,
    Usage,
    VerifiedElement,
    VerifiedReference,
)
from app.technology_rag.generation.validation import QuoteCheck, check_quote, locate

__all__ = [
    "Generator", "LLMClient", "MissingApiKeyError", "LLMRefusalError",
    "GenerationResult", "LLMAnswer", "Reference", "TechElementOut", "Usage",
    "VerifiedElement", "VerifiedReference", "QuoteCheck", "check_quote", "locate",
]
