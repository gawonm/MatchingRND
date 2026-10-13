"""
청킹 전략.

TechDocument(기술 1건) → Chunk 목록. 전략을 교체 가능한 클래스로 구현해
"청킹 방식에 따른 검색 성능 비교" 실험(plan.md)을 코드 수정 없이 돌릴 수 있게 한다.

    doc            기술당 1청크                         (591건)
    section        섹션당 1청크                         (3,546건)
    section_group  의미가 가까운 섹션 2개씩 묶어 1청크   (1,773건)

모든 전략 공통 규칙
-------------------
- 청크 텍스트 맨 앞에 `기술명 (부제)` 와 `[섹션명]` 을 붙인다.
  공공기관 `application` 섹션은 평균 41자라 단독으로는 맥락이 없다. 이를 보강하는 안이며,
  `include_title_prefix=False` 로 끄고 효과를 비교할 수 있다.
- 빈 섹션은 건너뛴다. 청크가 하나도 안 나오면 오류가 아니라 빈 리스트를 돌려준다.
- 청크는 포함한 섹션의 TextBlock(page, bbox)을 그대로 들고 있다 → Evidence 복원용.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from pathlib import Path

from app.technology_rag.schemas import Chunk, SectionCode, TechDocument
from app.technology_rag import constants as C

S = SectionCode

#: section_group 전략의 묶음. 길이 실측(공공기관 problem 96자, application 41자)을 근거로
#: 짧은 섹션을 의미가 가까운 섹션과 묶었다.
#:   개요+문제 = 이 기술이 무엇이고 어떤 문제를 푸는가
#:   강점+구성 = 어떻게 구현되며 무엇이 차별적인가
#:   적용+시장 = 어디에 쓰이고 시장성은 어떤가
DEFAULT_GROUPS: tuple[tuple[SectionCode, ...], ...] = (
    (S.OVERVIEW, S.PROBLEM),
    (S.STRENGTH, S.COMPOSITION),
    (S.APPLICATION, S.MARKET),
)


def _head(doc: TechDocument) -> str:
    return doc.title + (f" ({doc.subtitle})" if doc.subtitle else "")


def doc_metadata(doc: TechDocument) -> dict:
    """Chroma where 필터용 평탄 메타데이터. 스칼라만, None 은 넣지 않는다."""
    p = doc.patent
    meta = {
        "doc_id": doc.doc_id,
        "source": doc.source.value,
        "title": doc.title,
        "provider": doc.provider,
        "major": doc.taxonomy.major,
        "middle": doc.taxonomy.middle,
        "minor": doc.taxonomy.minor,
        "transfer_condition": doc.transfer_condition.value,
        "application_number": p.application_number,
        "expiry_year": p.expiry_date.year if p.expiry_date else None,
    }
    return {k: v for k, v in meta.items() if v is not None}


class Chunker(ABC):
    """청킹 전략의 공통 인터페이스."""

    name: str

    def __init__(self, *, include_title_prefix: bool = True) -> None:
        self.include_title_prefix = include_title_prefix

    @property
    def strategy_tag(self) -> str:
        """Chunk.strategy 와 컬렉션 이름에 쓰는 식별자. 설정이 다르면 이름도 달라진다."""
        return self.name if self.include_title_prefix else f"{self.name}+noprefix"

    @abstractmethod
    def groups(self) -> list[tuple[SectionCode, ...]]:
        """이 전략이 한 청크로 묶는 섹션 그룹들."""

    # ------------------------------------------------------------------
    def chunk(self, doc: TechDocument) -> list[Chunk]:
        out: list[Chunk] = []
        for group in self.groups():
            secs = [s for c in group if (s := doc.section(c)) is not None and not s.is_empty]
            if not secs:
                continue
            body = "\n".join(f"[{s.title}]\n{s.text}" for s in secs)
            text = f"{_head(doc)}\n{body}" if self.include_title_prefix else body

            blocks = [b for s in secs for b in s.blocks]
            key = self.section_key(group)
            meta = {
                **doc_metadata(doc),
                "section_key": key,
                "strategy": self.strategy_tag,
                "page_start": min(b.page for b in blocks) if blocks else doc.page_start,
                "page_end": max(b.page for b in blocks) if blocks else doc.page_end,
            }
            out.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}#{key}#0",
                    parent_doc_id=doc.doc_id,
                    source=doc.source,
                    section_key=key,
                    sections=[s.code for s in secs],
                    text=text,
                    page_start=meta["page_start"],
                    page_end=meta["page_end"],
                    blocks=blocks,
                    strategy=self.strategy_tag,
                    metadata=meta,
                )
            )
        return out

    def chunk_all(self, docs: Iterable[TechDocument]) -> list[Chunk]:
        return [c for d in docs for c in self.chunk(d)]

    def section_key(self, group: tuple[SectionCode, ...]) -> str:
        return "+".join(c.value for c in group)


class DocChunker(Chunker):
    """기술 1건 = 청크 1개."""

    name = "doc"

    def groups(self):
        return [tuple(C.SECTION_ORDER)]

    def section_key(self, group):
        return "doc"


class SectionChunker(Chunker):
    """섹션 1개 = 청크 1개."""

    name = "section"

    def groups(self):
        return [(c,) for c in C.SECTION_ORDER]


class SectionGroupChunker(Chunker):
    """의미가 가까운 섹션 묶음 = 청크 1개."""

    name = "section_group"

    def __init__(self, *, groups=DEFAULT_GROUPS, include_title_prefix: bool = True) -> None:
        super().__init__(include_title_prefix=include_title_prefix)
        flat = [c for g in groups for c in g]
        if len(flat) != len(set(flat)):
            raise ValueError("section_group: 한 섹션이 두 그룹에 들어 있다")
        self._groups = [tuple(g) for g in groups]

    def groups(self):
        return self._groups


_REGISTRY: dict[str, type[Chunker]] = {
    c.name: c for c in (DocChunker, SectionChunker, SectionGroupChunker)
}


def get_chunker(name: str, **kwargs) -> Chunker:
    try:
        return _REGISTRY[name](**kwargs)
    except KeyError:
        raise ValueError(f"알 수 없는 청킹 전략 {name!r}. 선택: {sorted(_REGISTRY)}") from None


def available_strategies() -> list[str]:
    return list(_REGISTRY)


def load_chunks(path: Path | str) -> list[Chunk]:
    """python -m app.technology_rag.scripts.build_chunks 가 만든 chunks_*.jsonl 을 읽는다."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} 가 없습니다. python -m app.technology_rag.scripts.build_chunks 를 먼저 실행하세요.")
    with path.open(encoding="utf-8") as f:
        return [Chunk.model_validate_json(line) for line in f if line.strip()]
