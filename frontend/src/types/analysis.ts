// 분석 결과 타입. 화면은 이 타입만 알고, 백엔드 응답은 나중에 이 타입으로 변환해서 넘긴다.

// export type GapStatus = "covered" | "partial" | "gap" | "unknown";

// export type EvidenceSource = "user" | "tech_share" | "ntis" | "rfp";

// export interface TechnologyInput {
//   ownedTech: string; // 보유 기술
//   problem: string; // 해결하려는 기술 문제
// }

// export interface Evidence {
//   source: EvidenceSource;
//   docTitle: string; // 문서명 또는 문서 ID
//   quote: string; // 인용문
//   supports: string; // 이 근거가 뒷받침하는 내용
// }

// export interface GapItem {
//   id: string;
//   requirement: string; // RFP 요구 기술
//   ownedTech: string | null; // 대응하는 보유 기술 (없으면 null)
//   status: GapStatus;
//   reason: string; // 판정 이유
//   evidences: Evidence[];
// }

// export interface Project {
//   id: string;
//   title: string;
//   summary: string;
//   field: string; // 관련 기술 분야
//   gapSummary: Record<GapStatus, number>; // 상태별 항목 수 (분석 결과에 포함된 값)
//   gaps: GapItem[];
// }

// export interface AnalysisResult {
//   projects: Project[];
// }


export type GapStatus =
  | "covered"
  | "partial"
  | "gap"
  | "unknown";

export type Evidence = {
  id: string;
  source: "user_input" | "technology" | "ntis" | "rfp";
  documentTitle: string;
  quote: string;
  section?: string | null;
  page?: number | null;
  pageEnd?: number | null;
  sourcePath?: string | null;
  locations?: Record<string, unknown>[];
};

export type GapItem = {
  id: string;
  requirement: string;
  ownedTechnology: string | null;
  status: GapStatus;
  reason: string;
  evidenceIds: string[];
};

export type RndProject = {
  id: string;
  title: string;
  description: string;
  field: string;
  gaps: GapItem[];
};

export type AnalysisResult = {
  projects: RndProject[];
  evidences: Evidence[];
};
