import { useState } from "react";
import { Badge, Button, Col, Row } from "react-bootstrap";
import ProjectCard from "./ProjectCard";
import GapComparison, { type GapFilter } from "./GapComparison";
import EvidencePanel from "./EvidencePanel";
import { mockAnalysis } from "../data/mockAnalysis";

interface Props {
  ownedTechnology: string;
  technicalProblem: string;
  onBack: () => void;
}

// 결과 화면의 선택 상태(과제, Gap 항목, 필터)를 관리한다.
export default function ResultsWorkspace({ ownedTechnology, technicalProblem, onBack }: Props) {
  // 실제 API 연동 시 이 mockAnalysis를 API 응답(변환 후)으로 교체한다.
  const result = mockAnalysis;

  const [projectId, setProjectId] = useState(result.projects[0].id);
  const [gapId, setGapId] = useState<string | null>(null);
  const [filter, setFilter] = useState<GapFilter>("all");

  const project = result.projects.find((p) => p.id === projectId) ?? result.projects[0];
  const gap = project.gaps.find((g) => g.id === gapId) ?? null;
  const evidences = gap ? result.evidences.filter((e) => gap.evidenceIds.includes(e.id)) : [];

  // 다른 과제로 이동하면 이전 과제의 Gap 선택과 필터를 초기화한다.
  const selectProject = (id: string) => {
    setProjectId(id);
    setGapId(null);
    setFilter("all");
  };

  return (
    <section>
      <div className="d-flex flex-wrap justify-content-between align-items-start gap-3 mb-3">
        <div>
          <h2 className="fw-bold mb-1">
            기술 매칭 분석 <Badge className="badge-accent align-middle fs-6">데모 데이터</Badge>
          </h2>
          <p className="text-secondary small mb-0">
            분석 결과는 실제 RAG 결과가 아닌 고정된 예시이며, 입력 내용에 따라 달라지지 않습니다.
          </p>
        </div>
        <Button className="btn-accent-outline" onClick={onBack}>
          <i className="bi bi-arrow-left me-2" />
          홈으로
        </Button>
      </div>

      <div className="app-card p-3 mb-4 small">
        <div>
          <span className="text-secondary">보유 기술 </span>
          {ownedTechnology}
        </div>
        <div className="mt-1">
          <span className="text-secondary">해결하려는 기술 문제 </span>
          {technicalProblem}
        </div>
      </div>

      <Row className="g-4">
        <Col xl={3} lg={4}>
          <h3 className="h6 fw-bold mb-3">추천 R&D 과제</h3>
          <div className="d-flex flex-column gap-3">
            {result.projects.map((p) => (
              <ProjectCard key={p.id} project={p} selected={p.id === project.id} onSelect={() => selectProject(p.id)} />
            ))}
          </div>
        </Col>

        <Col xl={5} lg={8}>
          <h3 className="h6 fw-bold mb-3">기술 Gap 비교 · {project.title}</h3>
          <GapComparison
            gaps={project.gaps}
            selectedId={gapId}
            filter={filter}
            onFilterChange={setFilter}
            onSelect={setGapId}
          />
        </Col>

        <Col xl={4} lg={12}>
          <h3 className="h6 fw-bold mb-3">AI 분석 · Evidence</h3>
          <EvidencePanel gap={gap} evidences={evidences} />
        </Col>
      </Row>
    </section>
  );
}
