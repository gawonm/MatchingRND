import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import app


class FakeRepository:
    def __init__(self, snapshots=None, error=None):
        self.snapshots = snapshots or {}
        self.error = error
        self.calls = []

    def snapshot(self, source):
        self.calls.append(source)
        if self.error:
            raise self.error
        return self.snapshots[source]


def snapshot(source, documents, chunks, payload=None):
    return documents, [dict(chunk, corpus_id=source) for chunk in chunks], payload or {}


class DiscoveryApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.snapshots = {
            "technology": snapshot("technology", [{
                "document_id": "POSCO-113", "title": "폐열 회수 발전 기술", "institution": "포스코",
                "year": 2024, "source_path": "technology.xlsx", "full_text": "ORC 폐열 발전",
            }], [{
                "chunk_id": "tech-c1", "document_id": "POSCO-113", "content": "ORC를 이용한 폐열 회수 발전 기술",
                "section": "기술개요", "page_start": None, "page_end": None, "metadata": {},
            }]),
            "ntis": snapshot("ntis", [{
                "document_id": "ntis-001", "title": "제설 로봇 선행 연구", "institution": "한국연구원",
                "year": 2023, "source_path": "ntis.xlsx", "full_text": "자율 제설 로봇",
            }], [{
                "chunk_id": "ntis-c1", "document_id": "ntis-001", "content": "센서 융합 기반 자율 제설 로봇 연구",
                "section": None, "page_start": None, "page_end": None, "metadata": {"project_id": "001"},
            }]),
            "rfp": snapshot("rfp", [{
                "document_id": "rfp.pdf", "title": "2026 사업 공고", "institution": "산업부",
                "year": 2026, "source_path": "rfp/2026.pdf", "full_text": "제설 로봇과 배터리 과제",
            }], [{
                "chunk_id": "rfp-c1", "document_id": "rfp.pdf", "content": "센서 융합 제설 로봇을 개발한다.",
                "section": "개발내용", "page_start": 3, "page_end": 4,
                "metadata": {"task_id": "1273377-04", "item": "개발내용", "sources": [{"page": 3, "bbox": [1, 2, 3, 4]}]},
            }, {
                "chunk_id": "rfp-c2", "document_id": "rfp.pdf", "content": "제설 로봇의 정량 성능을 검증한다.",
                "section": "성능지표", "page_start": 5, "page_end": 5,
                "metadata": {"task_id": "1273377-04"},
            }, {
                "chunk_id": "rfp-c3", "document_id": "rfp.pdf", "content": "배터리 재활용 기술을 개발한다.",
                "section": "개발내용", "page_start": 8, "page_end": 8,
                "metadata": {"task_id": "1273377-05"},
            }], {"tasks": [
                {"task_id": "1273377-04", "document_id": "rfp.pdf", "title": "제설 로봇 개발"},
                {"task_id": "1273377-05", "document_id": "rfp.pdf", "title": "배터리 재활용"},
            ]}),
        }

    def get(self, source, q, **params):
        repository = FakeRepository(self.snapshots)
        with patch("app.api.discovery.get_discovery_repository", return_value=repository):
            response = self.client.get("/api/discovery/search", params={"source": source, "q": q, **params})
        return response, repository

    def test_searches_each_source_as_its_domain_unit(self):
        cases = [
            ("technology", "폐열", "POSCO-113"),
            ("ntis", "센서 융합", "ntis-001"),
            ("rfp", "제설", "rfp.pdf"),
        ]
        for source, query, original_id in cases:
            with self.subTest(source=source):
                response, repository = self.get(source, query)
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["status"], "success")
                self.assertEqual(body["items"][0]["originalId"], original_id)
                self.assertEqual(repository.calls, [source])

    def test_empty_result_is_successful_empty_state(self):
        response, _ = self.get("technology", "없는검색어")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "items": [], "total": 0, "page": 1, "page_size": 20,
            "has_next": False, "status": "empty",
        })

    def test_query_and_pagination_validation(self):
        for params in [
            {"source": "bad", "q": "검색"},
            {"source": "rfp", "q": "검색", "page": 0},
            {"source": "rfp", "q": "검색", "page_size": 0},
            {"source": "rfp", "q": "   "},
        ]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/api/discovery/search", params=params).status_code, 422)

    def test_paginates_after_document_deduplication(self):
        documents = []
        chunks = []
        for number in range(3):
            document_id = f"tech-{number}"
            documents.append({"document_id": document_id, "title": f"센서 기술 {number}", "full_text": "센서", "institution": None})
            chunks.extend([
                {"chunk_id": f"{document_id}-a", "document_id": document_id, "content": "센서 원문", "metadata": {}},
                {"chunk_id": f"{document_id}-b", "document_id": document_id, "content": "센서 추가 원문", "metadata": {}},
            ])
        self.snapshots["technology"] = snapshot("technology", documents, chunks)
        response, _ = self.get("technology", "센서", page=2, page_size=1)
        body = response.json()
        self.assertEqual((body["total"], len(body["items"]), body["page"], body["has_next"]), (3, 1, 2, True))

    def test_rfp_preserves_task_id_and_collapses_its_chunks(self):
        response, _ = self.get("rfp", "제설")
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["taskId"], "1273377-04")
        self.assertEqual(body["items"][0]["key"], "real:rfp:rfp.pdf:1273377-04")
        self.assertEqual(len(body["items"][0]["evidence"]), 1)

    def test_korean_term_does_not_match_across_unrelated_morphemes(self):
        documents, chunks, payload = self.snapshots["rfp"]
        payload["tasks"].append({"task_id": "drug", "document_id": "rfp.pdf", "title": "의약품 제형 개발"})
        chunks.append({
            "chunk_id": "drug-c1", "document_id": "rfp.pdf", "content": "AI 기반 다중 의약품 제제설계 시스템",
            "metadata": {"task_id": "drug"},
        })
        response, _ = self.get("rfp", "제설")
        self.assertNotIn("drug", {item["taskId"] for item in response.json()["items"]})

    def test_passes_through_source_metadata_and_exact_excerpt(self):
        response, _ = self.get("rfp", "센서")
        item = response.json()["items"][0]
        evidence = item["evidence"][0]
        self.assertEqual((item["provider"], item["year"]), ("산업부", 2026))
        self.assertEqual((evidence["section"], evidence["page"], evidence["pageEnd"]), ("개발내용", 3, 4))
        self.assertEqual(evidence["sourcePath"], "2026.pdf")
        self.assertEqual(evidence["locations"], [{"page": 3, "bbox": [1, 2, 3, 4]}])
        self.assertEqual(evidence["quote"], "센서 융합 제설 로봇을 개발한다.")

    def test_source_paths_and_nested_locations_are_safe_in_http_response(self):
        document = self.snapshots["rfp"][0][0]
        location = self.snapshots["rfp"][1][0]["metadata"]["sources"][0]
        location.update({"document_id": "rfp.pdf", "source": r"C:\private\rfp.pdf",
                         "nested": {"path": "/srv/private/report.pdf"},
                         "source_locations": [{"page": 4, "bbox": [5, 6, 7, 8],
                                               "filename": r"\\server\share\secret.pdf", "task_id": "1273377-04"}]})
        for path in (r"C:\private\rfp.pdf", r"C:private\rfp.pdf", r"\\server\share\rfp.pdf",
                     "/srv/private/rfp.pdf", "../private/rfp.pdf", "http://localhost/private.pdf"):
            with self.subTest(path=path):
                document["source_path"] = path
                response, _ = self.get("rfp", "제설")
                self.assertEqual(response.status_code, 200)
                evidence = response.json()["items"][0]["evidence"][0]
                self.assertIsNone(evidence["sourcePath"])
                self.assertEqual(evidence["locations"], [{"page": 3, "bbox": [1, 2, 3, 4],
                    "document_id": "rfp.pdf", "source_locations": [{"page": 4, "bbox": [5, 6, 7, 8],
                    "task_id": "1273377-04"}]}])
                self.assertNotIn("private", response.text)
                self.assertNotIn("secret.pdf", response.text)
        for path, expected in (("rfp/2026.pdf", "2026.pdf"),
                               ("https://example.org/notice/2026.pdf", "https://example.org/notice/2026.pdf")):
            with self.subTest(path=path):
                document["source_path"] = path
                response, _ = self.get("rfp", "제설")
                self.assertEqual(response.json()["items"][0]["evidence"][0]["sourcePath"], expected)

    def test_db_failure_is_explicit_and_does_not_leak_details(self):
        repository = FakeRepository(error=RuntimeError("password=secret"))
        with patch("app.api.discovery.get_discovery_repository", return_value=repository):
            response = self.client.get("/api/discovery/search", params={"source": "ntis", "q": "센서"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["error"], "discovery_unavailable")
        self.assertEqual(response.json()["detail"]["source"], "ntis")
        self.assertNotIn("secret", response.text)

    def test_existing_analysis_route_remains_registered(self):
        self.assertIn("/api/analysis", {route.path for route in app.routes if hasattr(route, "path")})


if __name__ == "__main__":
    unittest.main()
