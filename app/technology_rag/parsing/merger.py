"""
PDF 파싱 결과(TechDocument)에 엑셀 메타데이터를 병합한다.

병합 규칙 (plan.md 확정 사항)
-----------------------------
- 조인 키: 정규화한 출원번호(숫자 13자리).
- 본문(sections)은 PDF가 유일한 소스다. 엑셀로 덮어쓰지 않는다.
- 제목/분류/발명자/날짜 등 PDF에 이미 있는 값은 PDF 우선, 엑셀은 비어 있는 곳만 채운다.
- PDF에 없는 값(이전조건, 나눔기간, 관리기관, IPC, 출원인 ...)은 엑셀 값을 넣는다.

병합 중 두 소스가 어긋나는 곳(제목/분류/기관/만료일/일련번호)은 MergeReport에 기록한다.
어긋나더라도 PDF 값을 유지하며, 기록은 검증용이다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.common.schemas import SourceType
from app.technology_rag.schemas import TechDocument
from app.technology_rag.text import normalize_application_number
from app.technology_rag.parsing.excel_loader import ExcelRecord


def _key(s: str | None) -> str:
    """비교용 정규화: 한글/영숫자만 남기고 소문자. ('기계ㆍ소재' == '기계·소재')"""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s or "").lower()


def _same(a: str | None, b: str | None) -> bool:
    ka, kb = _key(a), _key(b)
    return bool(ka) and bool(kb) and (ka == kb or ka in kb or kb in ka)


@dataclass
class MergeReport:
    total_docs: int = 0
    joined: int = 0
    unjoined_docs: list[str] = field(default_factory=list)
    unused_excel: list[str] = field(default_factory=list)
    #: 항목명 -> [(doc_id, PDF값, 엑셀값), ...]
    mismatches: dict[str, list[tuple[str, str, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @property
    def ok(self) -> bool:
        return not self.unjoined_docs and not self.unused_excel


def _merge_one(doc: TechDocument, rec: ExcelRecord, report: MergeReport) -> None:
    p = doc.patent
    tag = doc.doc_id

    # --- 교차검증 (PDF 값은 바꾸지 않는다) ---
    if rec.title and not _same(doc.title, rec.title):
        report.mismatches["title"].append((tag, doc.title, rec.title))
    if rec.source == SourceType.PUBLIC_TECH:
        if rec.row_id != doc.seq_no:
            report.mismatches["seq_no"].append((tag, doc.seq_no, rec.row_id))
        if rec.provider and not _same(doc.provider, rec.provider):
            report.mismatches["provider"].append((tag, str(doc.provider), rec.provider))
        for lv, pdf_v, xl_v in (
            ("major", doc.taxonomy.major, rec.major),
            ("middle", doc.taxonomy.middle, rec.middle),
            ("minor", doc.taxonomy.minor, rec.minor),
        ):
            if xl_v and not _same(pdf_v, xl_v):
                report.mismatches[f"taxonomy.{lv}"].append((tag, str(pdf_v), xl_v))
    if rec.expiry_date and p.expiry_date and rec.expiry_date != p.expiry_date:
        report.mismatches["expiry_date"].append((tag, str(p.expiry_date), str(rec.expiry_date)))
    if rec.registration_number and p.registration_number:
        if rec.registration_number != normalize_application_number(p.registration_number):
            report.mismatches["registration_number"].append(
                (tag, str(p.registration_number), rec.registration_number)
            )

    # --- 빈 곳 채우기 (PDF 우선) ---
    doc.provider = doc.provider or rec.provider
    doc.taxonomy.major = doc.taxonomy.major or rec.major
    doc.taxonomy.middle = doc.taxonomy.middle or rec.middle
    doc.taxonomy.minor = doc.taxonomy.minor or rec.minor

    p.application_date = p.application_date or rec.application_date
    p.registration_date = p.registration_date or rec.registration_date
    p.expiry_date = p.expiry_date or rec.expiry_date
    if not p.registration_number and rec.registration_number:
        p.registration_number = rec.registration_number
    if rec.country:
        p.country = rec.country
    if rec.ipc:
        p.ipc = rec.ipc

    # --- PDF에 없는 값은 엑셀에서 ---
    doc.transfer_condition = rec.transfer_condition
    doc.sharing_start = rec.sharing_start
    doc.sharing_end = rec.sharing_end
    doc.manager_org = rec.manager_org
    doc.applicant = rec.applicant

    doc.excel_joined = True
    doc.extra["excel"] = {"row_id": rec.row_id, **{k: v for k, v in rec.extra.items() if v is not None}}


def merge_documents(
    docs: list[TechDocument],
    records: dict[SourceType, dict[str, ExcelRecord]],
) -> MergeReport:
    """docs 를 제자리에서 갱신하고 MergeReport 를 반환한다."""
    report = MergeReport(total_docs=len(docs))
    used: dict[SourceType, set[str]] = defaultdict(set)

    for doc in docs:
        app = normalize_application_number(doc.patent.application_number)
        rec = records.get(doc.source, {}).get(app) if app else None
        if rec is None:
            report.unjoined_docs.append(doc.doc_id)
            doc.excel_joined = False
            continue
        _merge_one(doc, rec, report)
        used[doc.source].add(rec.application_number)
        report.joined += 1

    for src, recs in records.items():
        for app, rec in recs.items():
            if app not in used[src]:
                report.unused_excel.append(f"{src.value}:{rec.row_id}:{app}")
    return report
