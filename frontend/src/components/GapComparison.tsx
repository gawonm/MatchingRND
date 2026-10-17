import { Badge, Button, Card } from "react-bootstrap";
import type { GapItem, GapStatus } from "../types/analysis";
import { statusMeta } from "./statusMeta";

export type GapFilter = "all" | GapStatus;

interface Props {
  gaps: GapItem[];
  selectedId: string | null;
  filter: GapFilter;
  onFilterChange: (filter: GapFilter) => void;
  onSelect: (id: string) => void;
}

const filters: GapFilter[] = ["all", "covered", "partial", "gap", "unknown"];

export default function GapComparison({ gaps, selectedId, filter, onFilterChange, onSelect }: Props) {
  const shown = filter === "all" ? gaps : gaps.filter((g) => g.status === filter);

  return (
    <Card className="app-card">
      <Card.Body>
        <div className="d-flex flex-wrap gap-2 mb-3">
          {filters.map((f) => (
            <Button
              key={f}
              size="sm"
              className={filter === f ? "status-filter status-filter-selected" : "status-filter"}
              onClick={() => onFilterChange(f)}
              aria-pressed={filter === f}
            >
              {f === "all" ? "전체" : statusMeta[f].ko}
            </Button>
          ))}
        </div>

        {shown.length === 0 ? (
          <div className="empty-state text-center text-secondary py-4">
            <i className="bi bi-inbox fs-3 d-block mb-2" />
            <div>
              <strong>{filter === "all" ? "" : statusMeta[filter as GapStatus].ko}</strong> 상태의 기술요소가 없습니다.
            </div>
            <Button variant="link" size="sm" onClick={() => onFilterChange("all")}>
              전체 보기
            </Button>
          </div>
        ) : (
          <div className="d-flex flex-column gap-3">
            {shown.map((g) => (
              <button
                key={g.id}
                type="button"
                className={`gap-item text-start ${g.id === selectedId ? "gap-item-selected" : ""}`}
                onClick={() => onSelect(g.id)}
                aria-pressed={g.id === selectedId}
              >
                <div className="d-flex justify-content-between align-items-start gap-2">
                  <div className="fw-semibold">{g.requirement}</div>
                  <Badge bg={statusMeta[g.status].bg} text={statusMeta[g.status].text}>
                    {statusMeta[g.status].ko}
                  </Badge>
                </div>
                <div className="small mt-2">
                  <span className="text-secondary">데모 보유 기술 </span>
                  {g.ownedTechnology ?? "확인된 기술 없음"}
                </div>
              </button>
            ))}
          </div>
        )}
      </Card.Body>
    </Card>
  );
}


