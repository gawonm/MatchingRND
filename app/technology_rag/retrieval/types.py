"""검색 단계가 주고받는 최소 자료형.

BM25 / Dense / 융합 / 리랭커가 모두 같은 `Hit` 을 돌려주므로 서로 자유롭게 조합할 수 있다.
사용자에게 나가는 풍부한 형태는 `app.common.schemas.RetrievalHit` 이고,
변환은 `retrieval/pipeline.py` 에서 한 번만 한다.
"""

from __future__ import annotations

from typing import NamedTuple


class Hit(NamedTuple):
    """청크 1건의 검색 결과."""

    chunk_id: str
    score: float
    rank: int  # 1-based


class DocHit(NamedTuple):
    """문서(기술) 1건으로 집계한 결과."""

    doc_id: str
    score: float
    best_chunk_id: str  # 그 문서에서 가장 점수가 높았던 청크 = 근거를 보여줄 위치
    rank: int  # 1-based
