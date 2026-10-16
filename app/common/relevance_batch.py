"""Batch independent relevance requests without mixing technologies or evidence.

No dependency on the shared Gap LLM implementation. Gates retain responsibility
for semantic rules and source-quote validation.
"""
import json
from functools import lru_cache

from pydantic import ValidationError, create_model


@lru_cache(maxsize=16)
def _batch_model(model):
    row = create_model(f'{model.__name__}BatchRow', job_index=(int, ...), judgment=(model, ...))
    return create_model(f'{model.__name__}Batch', results=(list[row], ...))


BATCH_PROMPT = """다음 jobs는 서로 독립적인 후보 원문에 대한 동일한 기술의 관련성 검증입니다.
각 jobs[i].input에 위 규칙을 독립적으로 적용하고 job_index별 판단을 results에 하나씩 반환하세요.
다른 job의 원문을 현재 job의 근거로 인용하지 마세요. 후보끼리 비교하거나 순위를 다시 정하지 마세요.
모든 job_index를 정확히 한 번 포함하세요. judgment는 단일 입력에 대한 원래 응답 형식입니다.
각 job의 모든 원문을 새로 읽고 개별 판정하세요. 앞 job의 판정이나 reason을 복제하지 마세요.
원문이 없다고 판단하기 전에 동의어와 다른 구현 방식으로 같은 기능·적용대상을 요구하는지 확인하세요.
원문 표현이 다르면 reason에서도 그 job의 실제 표현과 기능의 대응 여부를 구체적으로 설명하세요.
"""


class BatchedRelevanceLLM:
    def __init__(self, llm_factory, *, batch_size=5, max_chars=24000):
        if batch_size < 1 or max_chars < 1:
            raise ValueError('관련성 검증 batch_size와 max_chars는 1 이상이어야 합니다.')
        self.factory = llm_factory
        self.client = None
        self.batch_size, self.max_chars = batch_size, max_chars
        self.requests = self.batches = self.singles = self.fallbacks = 0
        self.api_calls = self.cache_hits = 0

    def _call(self, messages, model, *, batch=False, fallback=False):
        self.client = self.factory()
        self.requests += 1
        self.batches += int(batch)
        self.singles += int(not batch)
        self.fallbacks += int(fallback)
        usage = getattr(self.client, 'usage', None)
        usage = usage if isinstance(usage, dict) else None
        before_calls = usage.get('calls', 0) if usage is not None else 0
        before_hits = usage.get('cache_hits', 0) if usage is not None else 0
        try:
            return self.client(messages, model)
        finally:
            calls = usage.get('calls', 0) - before_calls if usage is not None else 0
            hits = usage.get('cache_hits', 0) - before_hits if usage is not None else 0
            # Some clients update usage only after parsing succeeds. Count a
            # failed non-cache attempt too, without hiding it behind fallback.
            self.api_calls += calls or int(not hits)
            self.cache_hits += hits

    @property
    def stats(self):
        return {'llm_requests': self.requests, 'api_calls': self.api_calls,
                'cache_hits': self.cache_hits, 'batch_requests': self.batches,
                'single_requests': self.singles, 'fallback_requests': self.fallbacks,
                'batch_size': self.batch_size, 'max_chars': self.max_chars}

    def map(self, requests, model):
        """Requests in one map must concern one technology and the same system prompt."""
        results, group, size = [], [], 0

        def flush():
            nonlocal group, size
            if not group:
                return
            if len(group) == 1:
                results.append(self._call(group[0], model))
            else:
                messages = [
                    {'role': 'system', 'content': group[0][0]['content'] + '\n' + BATCH_PROMPT},
                    {'role': 'user', 'content': json.dumps({'jobs': [
                        {'job_index': i, 'input': json.loads(request[-1]['content'])}
                        for i, request in enumerate(group)
                    ]}, ensure_ascii=False)},
                ]
                batch_model = _batch_model(model)
                try:
                    raw = self._call(messages, batch_model, batch=True)
                    answer = batch_model.model_validate(raw)
                    ids = [row.job_index for row in answer.results]
                    if len(ids) != len(group) or set(ids) != set(range(len(group))):
                        raise ValueError('배치 응답에 누락·중복·범위 밖의 후보 인덱스가 있습니다.')
                    rows = {row.job_index: row.judgment for row in answer.results}
                    results.extend(rows[i] for i in range(len(group)))
                except (ValidationError, ValueError):
                    # A bad batch is never silently treated as unrelated candidates.
                    results.extend(self._call(request, model, fallback=True) for request in group)
            group, size = [], 0

        for request in requests:
            length = len(request[-1]['content'])
            if group and (len(group) == self.batch_size or size + length > self.max_chars):
                flush()
            group.append(request)
            size += length
        flush()
        return results
