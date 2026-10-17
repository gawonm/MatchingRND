import json
import unittest

from app.answer_format import HEADINGS
from app.common.schemas import Evidence, SourceType
from app.final_answer import EvidenceRecord, FinalAnswer
from app.scripts.final_answer_diagnostics import summarize


class FinalAnswerDiagnosticsTests(unittest.TestCase):
    def test_only_reports_safe_aggregate_fields(self):
        answer = FinalAnswer(
            method="llm",
            status="ok",
            markdown="\n".join(f"## {heading}" for heading in HEADINGS),
            evidence=[EvidenceRecord(
                evidence_id="secret-document-id",
                evidence=Evidence(doc_id="private-id", source=SourceType.RFP, quote="PII source quote"),
            )],
            stats={
                "latency_ms": 1234,
                "generation_usage": {"calls": 2, "prompt_tokens": 10, "api_key": "secret"},
                "raw_response": "PII full response",
            },
        )

        result = summarize(answer, latency_ms=987.5)

        self.assertEqual(result["markdown_length"], len(answer.markdown))
        self.assertTrue(result["section_headers_in_order"])
        self.assertTrue(all(result["section_headers_present"].values()))
        self.assertEqual(result["evidence_source_counts"], {"rfp": 1})
        self.assertEqual(result["accepted_claim_count"], 0)
        self.assertEqual(result["latency"], {"latency_ms": 987.5})
        self.assertEqual(result["usage"], {"calls": 2, "prompt_tokens": 10})
        serialized = json.dumps(result)
        for secret in ("secret-document-id", "private-id", "PII source quote", "api_key", "PII full response"):
            self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
