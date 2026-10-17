import { Badge, Card } from "react-bootstrap";
import type { GapStatus, RndProject } from "../types/analysis";
import { statusMeta } from "./statusMeta";

interface Props {
  project: RndProject;
  selected: boolean;
  onSelect: () => void;
}

const order: GapStatus[] = ["covered", "partial", "gap", "unknown"];

export default function ProjectCard({ project, selected, onSelect }: Props) {
  return (
    <Card
      as="button"
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={`project-card text-start w-100 ${selected ? "project-card-selected" : ""}`}
    >
      <Card.Body>
        <div className="accent-text small fw-semibold mb-1">{project.field}</div>
        <Card.Title className="fs-6 fw-bold">{project.title}</Card.Title>
        <Card.Text className="text-secondary small">{project.description}</Card.Text>
        <div className="d-flex flex-wrap gap-1">
          {order.map((s) => {
            const n = project.gaps.filter((g) => g.status === s).length;
            if (n === 0) return null;
            return (
              <Badge key={s} bg={statusMeta[s].bg} text={statusMeta[s].text}>
                {statusMeta[s].ko} {n}
              </Badge>
            );
          })}
        </div>
      </Card.Body>
    </Card>
  );
}
