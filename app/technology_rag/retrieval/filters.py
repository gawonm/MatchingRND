"""
메타데이터 필터.

왜 필요한가
-----------
Chroma 는 `where` 를 네이티브로 지원하지만 **BM25 는 지원하지 않는다.**
Dense 쪽에만 필터를 걸면 BM25 결과가 필터를 통과해 버려서, 융합 후 조건에 맞지 않는
문서가 섞인다 (예: `transfer_condition="통상실시"` 로 검색했는데 `미상` 이 나옴).
그래서 같은 조건을 파이썬에서도 평가할 수 있어야 한다.

Chroma 의 where 문법 중 실제로 쓰는 부분만 지원하고, **모르는 연산자는 조용히 무시하지 않고
예외를 던진다** (필터가 안 먹은 결과를 맞다고 착각하는 것이 가장 위험하다).
"""

from __future__ import annotations

from typing import Any, Mapping

_OPS = {
    "$eq": lambda a, b: a == b,
    "$ne": lambda a, b: a != b,
    "$gt": lambda a, b: a is not None and a > b,
    "$gte": lambda a, b: a is not None and a >= b,
    "$lt": lambda a, b: a is not None and a < b,
    "$lte": lambda a, b: a is not None and a <= b,
    "$in": lambda a, b: a in b,
    "$nin": lambda a, b: a not in b,
}


def matches(metadata: Mapping[str, Any], where: Mapping[str, Any] | None) -> bool:
    """Chroma where 절을 메타데이터 한 건에 대해 평가한다."""
    if not where:
        return True
    for key, cond in where.items():
        if key == "$and":
            if not all(matches(metadata, c) for c in cond):
                return False
        elif key == "$or":
            if not any(matches(metadata, c) for c in cond):
                return False
        elif isinstance(cond, Mapping):
            for op, expected in cond.items():
                if op not in _OPS:
                    raise ValueError(f"지원하지 않는 필터 연산자: {op!r} (지원: {sorted(_OPS)}, $and, $or)")
                if not _OPS[op](metadata.get(key), expected):
                    return False
        else:
            # Chroma 에서 메타데이터에 없는 키는 매칭되지 않는다. 같은 규칙을 따른다.
            if key not in metadata or metadata[key] != cond:
                return False
    return True
