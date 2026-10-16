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
