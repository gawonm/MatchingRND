"""
OpenAI 호출 래퍼.

- **Structured Outputs**(`chat.completions.parse`)로 `LLMAnswer` 스키마를 강제한다.
  자유 텍스트를 파싱하지 않으므로 인용 검증과 참고문헌 집계가 가능하다.
- `openai` 패키지는 **호출할 때 import** 한다. 이 모듈을 import 하는 것만으로는 필요하지 않다.
- 키는 환경변수 `OPENAI_API_KEY` 또는 프로젝트 루트의 `.env` 에서 읽는다 (`.env.example` 참고).
  **키 값은 로그·예외·결과 어디에도 남기지 않는다.**
- 테스트에서는 `client=` 로 가짜 클라이언트(httpx.MockTransport 를 쓴 OpenAI)를 주입한다.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.technology_rag.paths import PROJECT_ROOT
from app.technology_rag.config import LLMConfig
from app.technology_rag.generation.schemas import LLMAnswer, Usage

log = logging.getLogger(__name__)


class MissingApiKeyError(RuntimeError):
    """OPENAI_API_KEY 가 없다. 호출 전에 알려서 헛된 요청과 모호한 401 을 막는다."""


class LLMRefusalError(RuntimeError):
    """모델이 응답을 거부했다."""


class LLMClient:
    def __init__(self, config: LLMConfig, client: Any = None) -> None:
        self.config = config
        self._client = client

    # ------------------------------------------------------------------
    def _get_client(self):
        if self._client is None:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env")        # 이미 설정된 환경변수는 덮어쓰지 않는다
            if not os.environ.get("OPENAI_API_KEY"):
                raise MissingApiKeyError(
                    "OPENAI_API_KEY 가 없습니다. 프로젝트 루트의 .env 에 `OPENAI_API_KEY=...` 를 넣으세요 "
                    "(양식: .env.example). 키 없이 프롬프트만 보려면 answer(..., dry_run=True)."
                )
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        c = self.config
        return prompt_tokens / 1e6 * c.price_per_1m_input + completion_tokens / 1e6 * c.price_per_1m_output

    # ------------------------------------------------------------------
    def ask(self, messages: list[dict]) -> tuple[LLMAnswer, Usage]:
        client = self._get_client()
        kwargs: dict[str, Any] = dict(
            model=self.config.model,
            messages=messages,
            response_format=LLMAnswer,
            temperature=self.config.temperature,
            max_completion_tokens=self.config.max_output_tokens,
        )
        if self.config.seed is not None:
            kwargs["seed"] = self.config.seed

        t = time.perf_counter()
        completion = client.chat.completions.parse(**kwargs)
        seconds = time.perf_counter() - t

        message = completion.choices[0].message
        if getattr(message, "refusal", None):
            raise LLMRefusalError(f"모델이 응답을 거부했습니다: {message.refusal}")
        if message.parsed is None:
            raise RuntimeError("응답을 LLMAnswer 로 해석하지 못했습니다 (finish_reason="
                               f"{completion.choices[0].finish_reason})")

        u = completion.usage
        pt, ct = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
        usage = Usage(model=self.config.model, prompt_tokens=pt, completion_tokens=ct,
                      seconds=round(seconds, 3), cost_usd=round(self.cost(pt, ct), 6))
        log.info("LLM 호출: %s 입력 %d + 출력 %d 토큰, %.1f초, $%.5f", usage.model, pt, ct, seconds, usage.cost_usd)
        return message.parsed, usage
