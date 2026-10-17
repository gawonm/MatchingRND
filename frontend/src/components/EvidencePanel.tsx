import { Alert, Badge, Card } from "react-bootstrap";
import type { Evidence, GapItem } from "../types/analysis";
import { sourceLabel, statusMeta } from "./statusMeta";

interface Props {
  gap: GapItem | null;
  evidences: Evidence[]; // gap.evidenceIds에 해당하는 근거
}

export default function EvidencePanel({ gap, evidences }: Props) {
  const rfp = evidences.filter((e) => e.source === "rfp");
  const others = evidences.filter((e) => e.source !== "rfp");

  return (
    <Card className="app-card">
      <Card.Body>
        <Card.Title className="fs-6 fw-bold">
          <i className="bi bi-stars accent-text me-2" />
          분석 근거
        </Card.Title>
        <Alert variant="light" className="evidence-notice py-2 small">
          데모 데이터입니다. 아래 판정과 문서는 모두 가상이며 입력 내용과 무관하게 고정된 예시입니다.
        </Alert>

        {!gap ? (
          <p className="text-secondary mb-0">가운데 목록에서 기술요소를 선택하면 판정 이유와 근거 원문이 표시됩니다.</p>
        ) : (
          <>
            <div className="mb-3">
              <div className="fw-bold mb-1">{gap.requirement}</div>
              <Badge bg={statusMeta[gap.status].bg} text={statusMeta[gap.status].text}>
                {statusMeta[gap.status].label} · {statusMeta[gap.status].ko}
              </Badge>
            </div>

            <Section title="판정 이유">{gap.reason}</Section>
            <Section title="대응하는 보유 기술">{gap.ownedTechnology ?? "확인된 기술 없음"}</Section>

            <Section title="관련 RFP 요구사항">
              {rfp.length === 0 ? (
                <span className="text-secondary">확인된 근거 없음</span>
              ) : (
                rfp.map((e) => <EvidenceBlock key={e.id} e={e} />)
              )}
            </Section>

            <Section title="근거 원문">
              {others.length === 0 ? (
                <span className="text-secondary">확인된 근거 없음</span>
              ) : (
                others.map((e) => <EvidenceBlock key={e.id} e={e} />)
              )}
            </Section>
          </>
        )}
      </Card.Body>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="small fw-semibold text-secondary mb-1">{title}</div>
      <div>{children}</div>
    </div>
  );
}

function EvidenceBlock({ e }: { e: Evidence }) {
  return (
    <div className="evidence-block mb-2">
      <div className="small mb-1">
        <Badge className="badge-accent me-2">{sourceLabel[e.source]}</Badge>
        <span className="text-secondary">{e.documentTitle}</span>
      </div>
      <blockquote className="mb-0 small">“{e.quote}”</blockquote>
    </div>
  );
}
