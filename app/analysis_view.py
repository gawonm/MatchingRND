"""UI read model projected from one analysis run, without retrieval or LLM calls.

The view mirrors what the final Markdown shows (app/answer_format.py): same candidate
dedup/order, same validated Gap labels and scope. Relations that cannot be verified from
structured data are left empty rather than inferred from report text.

Coupling (refactor risk): reuses private helpers so the view cannot drift from the report:
- app.final_answer: collect_evidence, _validated_report
- app.answer_format: _Presentation, _unique_candidates, _notices, _url, TECH_SOURCES
If those helpers change, tests/test_analysis_view.py compares the view with the Markdown.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.answer_format import TECH_SOURCES, _Presentation, _notices, _unique_candidates, _url
from app.common.schemas import GapLabel, SourceType
from app.final_answer import FinalAnswer, _validated_report, collect_evidence
from app.gap_analysis import GapReport
from app.orchestrator import AnalysisState

TOP_CANDIDATES = 5  # same slice as render_answer


class ProjectionError(RuntimeError):
    """The view could not be shown consistently with the report; `code` is safe to expose."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


class EvidenceItem(BaseModel):
    id: str = Field(description="FinalAnswer.evidence[].evidence_id. 이 응답 안에서만 유효")
    source_type: SourceType
    document_id: str = Field(description="문서 ID (chunk ID 아님)")
    chunk_id: str | None = Field(default=None, description="원 근거에 chunk_id가 기록된 경우에만")
    section: str | None = None
    page: int | None = Field(default=None, description="0-based PDF 페이지")
    quote: str
    source_title: str | None = Field(default=None, description="같은 실행의 후보 제목 또는 RFP 파일명. 없으면 null")
    notice_urls: list[str] = Field(default_factory=list, description="RFP 공고 링크(원문 PDF 링크 아님)")
    claim_indices: list[int] = Field(default_factory=list, description="이 근거를 유효하게 인용한 accepted FinalAnswer.claims 인덱스")


class TechnologyCandidate(BaseModel):
    id: str = Field(description="기술나눔 문서 ID")
    rank: int = Field(description="최종 보고서 추천 순서 (점수·적합도 아님)")
    title: str
    provider: str | None = None
    transfer_condition: str | None = None
    match_level: str | None = Field(default=None, description="Technology RAG 검증 매칭 수준 same|similar")
    rationale: str | None = Field(default=None, description="LLM 매칭 사유. 인용은 검증됐으나 의미 검토는 거치지 않음")
    gap_item_ids: list[str] = Field(default_factory=list, description="같은 응답의 GapItem.id. 그 GapItem.technology_ids에 이 기술이 있음")
    evidence_ids: list[str] = Field(default_factory=list)


class RFPCandidate(BaseModel):
    id: str = Field(description="RFP 과제 ID(task_id). 없으면 문서 ID")
    document_id: str = Field(description="RFP PDF 문서 ID. 여러 과제가 같은 문서를 공유할 수 있음")
    rank: int = Field(description="최종 보고서 추천 순서 (점수·적합도 아님)")
    title: str
    notice_titles: list[str] = Field(default_factory=list)
    notice_urls: list[str] = Field(default_factory=list, description="공고 링크(원문 PDF 링크 아님)")
    gap_analysis_status: Literal["analyzed", "not_analyzed", "unknown"]
    gap_item_ids: list[str] = Field(default_factory=list, description="같은 응답의 GapItem.id. 그 GapItem.rfp_ids에 이 RFP가 있음. analyzed가 아니면 빈 목록")
    evidence_ids: list[str] = Field(default_factory=list)


class GapItem(BaseModel):
    id: str = Field(description="gap-{gap_index}")
    gap_index: int = Field(description="FinalAnswer.claims[].draft.gap_index와 같은 인덱스")
    requirement_id: str = Field(description="RFP 요구기술 element_id (사용자 입력 B 아님)")
    requirement_name: str
    requirement_clear: bool
    label: GapLabel = Field(description="최종 Markdown과 같은 검증 후 판정")
    decision_path: str
    rfp_ids: list[str] = Field(default_factory=list)
    technology_ids: list[str] = Field(default_factory=list, description="검증된 외부기술 매칭 문서 ID")
    owned_technologies: list[str] = Field(
        default_factory=list,
        description="사용자 입력 보유기술과 RFP 요구의 매칭 이름. 기업 보유 사실을 독립 검증한 결과가 아님",
    )
    evidence_ids: list[str] = Field(default_factory=list)
    claim_indices: list[int] = Field(default_factory=list)


class AnalysisOverview(BaseModel):
    primary_technology_id: str | None = None
    primary_rfp_id: str | None = None
    gap_label_counts: dict[str, int] = Field(default_factory=dict, description="gap_items 범위의 판정별 개수")


class AnalysisView(BaseModel):
    technologies: list[TechnologyCandidate]
    rfps: list[RFPCandidate]
    gap_items: list[GapItem]
    evidence_items: list[EvidenceItem]
    overview: AnalysisOverview


def _identity(candidate) -> str:
    return candidate.extra.get("task_id") or candidate.doc_id  # same key as _unique_candidates


def _ids(records) -> list[str]:
    return list(dict.fromkeys(record.evidence_id for record in records))


def _analyzed_count(state: AnalysisState, report: GapReport) -> int | None:
    """select_rfps analyzes a prefix of state.rfp.candidates and records its doc_ids."""
    analyzed = report.stats.get("rfps_analyzed")
    if not isinstance(analyzed, list):
        return None
    prefix = [candidate.doc_id for candidate in state.rfp.candidates[:len(analyzed)]]
    return len(analyzed) if prefix == analyzed else None


def project_analysis_view(state: AnalysisState, report: GapReport, answer: FinalAnswer) -> AnalysisView:
    """`report` is the raw GapReport given to generate_final_answer for this `answer`."""
    if answer.method != report.method:
        raise ProjectionError("method_mismatch", "Gap 리포트와 최종 답변의 분석 방식이 다릅니다.")
    records = collect_evidence(state, report)
    signature = lambda rows: [(r.evidence_id, r.evidence.source, r.evidence.doc_id, r.evidence.quote) for r in rows]
    if signature(records) != signature(answer.evidence):
        raise ProjectionError("evidence_mismatch", "재계산한 근거가 FinalAnswer.evidence와 다릅니다.")
    validated = _validated_report(report, records, [])
    view = _Presentation(state, validated, answer.claims, answer.evidence)
    accepted = [(i, claim) for i, claim in enumerate(answer.claims) if claim.accepted]

    # Gap: same scope and label rule as render_answer section 3.
    rfp_all = _unique_candidates(state.rfp)
    indices_of = {_identity(c): view.gap_indices(c) for c in rfp_all}
    analyzed = _analyzed_count(state, report)
    analyzed_keys = None if analyzed is None else {_identity(c) for c in state.rfp.candidates[:analyzed]}
    scoped = sorted({i for indices in indices_of.values() for i in indices})
    gap_items = []
    for i in scoped:
        item = validated.items[i]
        label = item.label if view.matching_records(item.requirement.evidences) else GapLabel.INSUFFICIENT
        external = [m for m in item.external if m.verified and view.matching_records(m.evidences)]
        company = [m for m in item.company if m.verified and view.matching_records(m.evidences)]
        gap_items.append(GapItem(
            id=f"gap-{i}", gap_index=i, requirement_id=item.requirement.element_id,
            requirement_name=item.requirement.name, requirement_clear=item.requirement_clear,
            label=label, decision_path=item.decision_path,
            rfp_ids=[key for key, indices in indices_of.items()
                     if i in indices and (analyzed_keys is None or key in analyzed_keys)],
            technology_ids=list(dict.fromkeys(m.doc_id for m in external if m.doc_id)),
            owned_technologies=list(dict.fromkeys(m.element_name for m in company)),
            evidence_ids=_ids([*view.matching_records(item.requirement.evidences),
                               *(r for m in (*company, *external) for r in view.matching_records(m.evidences))]),
            claim_indices=[k for k, claim in accepted if claim.draft.section == "gap" and claim.draft.gap_index == i],
        ))
    gap_ids = {item.gap_index: item.id for item in gap_items}

    rfps = []
    for rank, c in enumerate(rfp_all[:TOP_CANDIDATES], 1):
        titles, urls = _notices(c)
        key = _identity(c)
        status = "unknown" if analyzed_keys is None else "analyzed" if key in analyzed_keys else "not_analyzed"
        rfps.append(RFPCandidate(
            id=key, document_id=c.doc_id, rank=rank, title=c.title, notice_titles=titles, notice_urls=urls,
            gap_analysis_status=status,
            # Never show Gap links for an RFP the Gap step did not analyze.
            gap_item_ids=[gap_ids[i] for i in indices_of[key]] if status == "analyzed" else [],
            evidence_ids=_ids(view.candidate_records(c, {SourceType.RFP})),
        ))

    technologies = []
    for rank, c in enumerate(_unique_candidates(state.technology)[:TOP_CANDIDATES], 1):
        technologies.append(TechnologyCandidate(
            id=_identity(c), rank=rank, title=c.title, provider=c.provider, transfer_condition=c.transfer_condition,
            match_level=c.extra.get("match_level"), rationale=c.relation_summary.strip() or None,
            gap_item_ids=[gap.id for gap in gap_items if c.doc_id in gap.technology_ids],
            evidence_ids=_ids(view.candidate_records(c, TECH_SOURCES)),
        ))

    # A PDF shared by several RFP tasks has no single task title.
    shared_docs = {c.doc_id for c in state.rfp.candidates
                   if sum(other.doc_id == c.doc_id for other in state.rfp.candidates) > 1}
    evidence_items = []
    for record in answer.evidence:
        ev = record.evidence
        title = None if ev.source == SourceType.RFP and ev.doc_id in shared_docs else view.names.get((ev.source.value, ev.doc_id))
        evidence_items.append(EvidenceItem(
            id=record.evidence_id, source_type=ev.source, document_id=ev.doc_id,
            chunk_id=ev.extra.get("chunk_id"), section=ev.section, page=ev.page, quote=ev.quote,
            source_title=ev.extra.get("filename") or title,
            notice_urls=[url for raw in ev.extra.get("notice_urls", []) if (url := _url(raw))]
            if ev.source == SourceType.RFP else [],
            claim_indices=[k for k, claim in accepted
                           if any(c.ok and c.evidence_id == record.evidence_id for c in claim.citations)],
        ))

    counts = {label.value: 0 for label in GapLabel}
    for item in gap_items:
        counts[item.label.value] += 1
    return AnalysisView(
        technologies=technologies, rfps=rfps, gap_items=gap_items, evidence_items=evidence_items,
        overview=AnalysisOverview(
            primary_technology_id=technologies[0].id if technologies else None,
            primary_rfp_id=rfps[0].id if rfps else None, gap_label_counts=counts,
        ),
    )
