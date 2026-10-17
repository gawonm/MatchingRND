"""Read-only discovery search over published Supabase corpus snapshots."""
from collections import defaultdict
from collections.abc import Mapping
from functools import lru_cache
import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.common.supabase_store import SupabaseRepository


router = APIRouter(prefix="/api/discovery", tags=["discovery"])
Source = Literal["technology", "rfp", "ntis"]


class DiscoveryEvidence(BaseModel):
    id: str
    source: Source
    documentTitle: str
    quote: str
    section: str | None = None
    page: int | None = None
    pageEnd: int | None = None
    sourcePath: str | None = None
    locations: list[dict] = Field(default_factory=list)


class DiscoveryItem(BaseModel):
    key: str
    mode: Literal["real"] = "real"
    source: Source
    title: str
    originalId: str
    taskId: str | None = None
    summary: str | None = None
    provider: str | None = None
    year: int | None = None
    evidence: list[DiscoveryEvidence]


class DiscoveryResponse(BaseModel):
    items: list[DiscoveryItem]
    total: int
    page: int
    page_size: int
    has_next: bool
    status: Literal["success", "empty"]


def get_discovery_repository() -> SupabaseRepository:
    return SupabaseRepository()


@lru_cache(maxsize=1)
def _kiwi():
    from kiwipiepy import Kiwi
    return Kiwi()


def _terms(query: str) -> list[str]:
    return [token.form.casefold() for token in _kiwi().tokenize(query) if token.form.strip()]


def _score(text: str, terms: list[str]) -> int:
    folded = text.casefold()
    if not any(term in folded for term in terms):
        return 0
    tokens = [token.form.casefold() for token in _kiwi().tokenize(text)]
    return sum(tokens.count(term) for term in terms)


def _excerpt(text: str, terms: list[str], limit: int = 600) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    folded = text.casefold()
    positions = [folded.find(term) for term in terms if folded.find(term) >= 0]
    start = max(0, (min(positions) if positions else 0) - limit // 4)
    return text[start:start + limit].strip()


def _safe_source_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        return None
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"}:
        host = parsed.hostname or ""
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not host:
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if "." not in host or host.endswith((".local", ".localhost", ".internal", ".test", ".invalid")):
                return None
        return value
    if parsed.scheme or value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value):
        return None
    parts = re.split(r"[/\\]", value)
    return parts[-1] if all(part not in {"", ".", ".."} for part in parts) else None


def _safe_location(value: Mapping) -> dict:
    result = {}
    for key in ("page", "page_start", "page_end"):
        if type(value.get(key)) is int and value[key] >= 0:
            result[key] = value[key]
    bbox = value.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4 and all(type(n) in (int, float) for n in bbox):
        result["bbox"] = list(bbox)
    for key in ("document_id", "doc_id", "task_id", "block_id", "source_kind"):
        identifier = value.get(key)
        if isinstance(identifier, str) and re.fullmatch(r"[\w.\-]+", identifier):
            result[key] = identifier
    for key in ("sources", "source_locations"):
        nested = value.get(key)
        if isinstance(nested, list):
            result[key] = [_safe_location(row) for row in nested if isinstance(row, Mapping)]
    return result


def _chunk_evidence(source: Source, title: str, document: Mapping, chunk: Mapping, terms: list[str]) -> DiscoveryEvidence:
    metadata = chunk.get("metadata") or {}
    locations = metadata.get("sources") or metadata.get("source_locations") or []
    return DiscoveryEvidence(
        id=str(chunk["chunk_id"]), source=source, documentTitle=title,
        quote=_excerpt(str(chunk.get("content") or ""), terms),
        section=chunk.get("section") or metadata.get("item"),
        page=chunk.get("page_start"), pageEnd=chunk.get("page_end"),
        sourcePath=_safe_source_path(document.get("source_path") or metadata.get("filename") or metadata.get("source")),
        locations=[_safe_location(row) for row in locations if isinstance(row, Mapping)],
    )


def search_snapshot(repository: SupabaseRepository, source: Source, query: str, page: int, page_size: int) -> DiscoveryResponse:
    documents, chunks, payload = repository.snapshot(source)
    terms = _terms(query)
    docs = {str(row["document_id"]): row for row in documents}
    grouped: dict[str, list[Mapping]] = defaultdict(list)
    for chunk in chunks:
        group_id = str((chunk.get("metadata") or {}).get("task_id") or chunk["document_id"]) if source == "rfp" else str(chunk["document_id"])
        grouped[group_id].append(chunk)

    if source == "rfp":
        raw_tasks = (payload or {}).get("tasks", []) if isinstance(payload, Mapping) else []
        units = [(str(task["task_id"]), task) for task in raw_tasks if task.get("task_id") and task.get("document_id")]
    else:
        units = [(document_id, document) for document_id, document in docs.items()]

    ranked = []
    for unit_id, unit in units:
        document_id = str(unit.get("document_id") or unit_id)
        document = docs.get(document_id, {})
        title = str(unit.get("title") or document.get("title") or "")
        candidates = grouped.get(unit_id, [])
        best = max(candidates, key=lambda row: _score(str(row.get("content") or ""), terms), default=None)
        title_score = _score(title, terms)
        content_score = _score(str(best.get("content") or ""), terms) if best else 0
        # A shared RFP PDF contains multiple tasks, so document text cannot score one task.
        full_score = 0 if source == "rfp" else _score(str(document.get("full_text") or ""), terms)
        score = title_score * 5 + content_score + full_score
        if not score or best is None:
            continue
        evidence = _chunk_evidence(source, title, document, best, terms)
        ranked.append((score, title.casefold(), DiscoveryItem(
            key=":".join(("real", source, document_id, unit_id)) if source == "rfp" else ":".join(("real", source, document_id)),
            source=source, title=title, originalId=document_id,
            taskId=unit_id if source == "rfp" else None,
            summary=evidence.quote or None,
            provider=document.get("institution"), year=document.get("year"), evidence=[evidence],
        )))

    ranked.sort(key=lambda row: (-row[0], row[1], row[2].key))
    total = len(ranked)
    start = (page - 1) * page_size
    items = [row[2] for row in ranked[start:start + page_size]]
    return DiscoveryResponse(
        items=items, total=total, page=page, page_size=page_size,
        has_next=start + page_size < total, status="success" if items else "empty",
    )


@router.get("/search", response_model=DiscoveryResponse)
async def search_discovery(
    source: Source,
    q: str = Query(min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    if not _terms(q):
        raise HTTPException(status_code=422, detail={"error": "invalid_query", "message": "검색어를 입력해 주세요."})
    try:
        return await run_in_threadpool(search_snapshot, get_discovery_repository(), source, q, page, page_size)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={
            "error": "discovery_unavailable", "source": source,
            "message": f"{source} 검색 자료를 불러오지 못했습니다.",
        }) from exc
