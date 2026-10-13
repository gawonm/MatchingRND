import type { Evidence, GapStatus } from "../types/analysis";

export const statusMeta: Record<GapStatus, { label: string; ko: string; bg: string; text?: string }> = {
  covered: { label: "Covered", ko: "충족", bg: "status-covered" },
  partial: { label: "Partial", ko: "부분 충족", bg: "status-partial" },
  gap: { label: "Gap", ko: "미충족", bg: "status-gap" },
  unknown: { label: "Unknown", ko: "판단 보류", bg: "status-unknown" },
};

export const sourceLabel: Record<Evidence["source"], string> = {
  user_input: "사용자 입력",
  technology: "기술나눔",
  ntis: "NTIS",
  rfp: "RFP",
};

