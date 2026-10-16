export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export type SourceType = 'pub' | 'pos' | 'ntis' | 'rfp' | 'policy' | 'company';

export type Evidence = {
  doc_id: string;
  source: SourceType;
  section: string | null;
  page: number | null;
  bbox: { x0: number; y0: number; x1: number; y1: number } | null;
  quote: string;
  verified: boolean;
  extra: Record<string, JsonValue>;
};

export type CitationCheck = { evidence_id: string; quote: string; ok: boolean; reason: string };

export type ClaimCheck = {
  draft: {
    section: 'external' | 'ntis' | 'rfp' | 'gap' | 'policy' | 'next_steps';
    gap_index: number | null;
    text: string;
    citations: { evidence_id: string; quote: string | null }[];
  };
  accepted: boolean;
  reason: string;
  citations: CitationCheck[];
};

// app.final_answer.FinalAnswer의 JSON 계약. 7개 공개 섹션은 markdown에 담긴다.
export type AnalysisReport = {
  method: string;
  status: 'ok' | 'partial' | 'insufficient' | 'template';
  markdown: string;
  claims: ClaimCheck[];
  evidence: { evidence_id: string; evidence: Evidence }[];
  warnings: string[];
  stats: Record<string, JsonValue>;
};

// app/analysis_view.py AnalysisView. ID·인덱스는 같은 응답 안에서만 유효하다.
export type GapLabel = '기존보유' | '외부기술보완' | '부분충족' | '추가R&D검토후보' | '근거부족';

export type EvidenceItem = {
  id: string;
  source_type: SourceType;
  document_id: string;
  chunk_id: string | null;
  section: string | null;
  page: number | null; // 0-based
  quote: string;
  source_title: string | null;
  notice_urls: string[]; // RFP 공고 링크 (원문 PDF 아님)
  claim_indices: number[]; // AnalysisReport.claims 인덱스
};

export type TechnologyCandidate = {
  id: string; rank: number; title: string; provider: string | null; transfer_condition: string | null;
  match_level: string | null; rationale: string | null; matched_requirement_ids: string[]; evidence_ids: string[];
};

export type RFPCandidate = {
  id: string; document_id: string; rank: number; title: string; notice_titles: string[]; notice_urls: string[];
  gap_analysis_status: 'analyzed' | 'not_analyzed' | 'unknown'; matched_requirement_ids: string[]; evidence_ids: string[];
};

export type GapItem = {
  id: string; gap_index: number; requirement_id: string; requirement_name: string; requirement_clear: boolean;
  label: GapLabel; decision_path: string; rfp_ids: string[]; technology_ids: string[]; owned_technologies: string[];
  evidence_ids: string[]; claim_indices: number[];
};

export type AnalysisView = {
  technologies: TechnologyCandidate[];
  rfps: RFPCandidate[];
  gap_items: GapItem[];
  evidence_items: EvidenceItem[];
  overview: { primary_technology_id: string | null; primary_rfp_id: string | null; gap_label_counts: Record<string, number> };
};

// POST /api/analysis/report-view. view_status=failed는 Projection 실패이며 보고서 실패가 아니다.
export type ReportViewResponse = {
  report: AnalysisReport;
  view: AnalysisView | null;
  view_status: 'ok' | 'failed';
  view_error: string | null;
};
