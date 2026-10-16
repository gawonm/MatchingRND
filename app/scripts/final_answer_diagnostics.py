"""Read FinalAnswer JSON from stdin and print a redacted aggregate diagnostic."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from app.answer_format import HEADINGS
from app.final_answer import FinalAnswer


_LATENCY_KEYS = ("latency_ms", "latency_seconds", "elapsed_ms", "elapsed_seconds")
_USAGE_KEYS = ("calls", "api_calls", "prompt_tokens", "completion_tokens", "total_tokens", "cache_hits")


def summarize(answer: FinalAnswer, latency_ms: float | None = None) -> dict:
    lines = answer.markdown.splitlines()
    found = [line[3:] for line in lines if line.startswith("## ")]
    stats = answer.stats
    usage = stats.get("generation_usage", {})
    return {
        "markdown_length": len(answer.markdown),
        "section_headers_present": {heading: heading in found for heading in HEADINGS},
        "section_headers_in_order": found == list(HEADINGS),
        "evidence_source_counts": dict(sorted(Counter(record.evidence.source.value for record in answer.evidence).items())),
        "accepted_claim_count": sum(claim.accepted for claim in answer.claims),
        "latency": ({"latency_ms": latency_ms} if latency_ms is not None else
                    {key: stats[key] for key in _LATENCY_KEYS if isinstance(stats.get(key), (int, float))}),
        "usage": {key: usage[key] for key in _USAGE_KEYS if isinstance(usage, dict) and isinstance(usage.get(key), (int, float))},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latency-ms", type=float, help="HTTP elapsed time measured by the caller")
    args = parser.parse_args()
    answer = FinalAnswer.model_validate_json(sys.stdin.read())
    print(json.dumps(summarize(answer, args.latency_ms), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
