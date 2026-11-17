import json

from eval.run_live_benchmark import run, score_case, summarize


def test_score_case_uses_uploaded_document_ids_and_actual_rank():
    case = {"id": "gc-01", "expected_status": "ok", "expected_hypothesis_contains": "memory limit"}
    body = {
        "status": "ok",
        "citations": [{"document_id": "unrelated"}, {"document_id": "uploaded-1"}],
        "hypotheses": [{"text": "Container exceeded memory limit"}],
    }
    scored = score_case(case, body, {"uploaded-1"}, 123)
    assert scored["retrieval_recall_at_5"] == 1.0
    assert scored["reciprocal_rank_at_5"] == 0.5
    assert scored["hypothesis_substring_match"] is True


def test_missing_evidence_cannot_score_as_success():
    case = {"id": "gc-01", "expected_status": "ok", "expected_hypothesis_contains": "memory limit"}
    scored = score_case(case, {"status": "insufficient_evidence", "citations": []}, {"uploaded-1"}, 100)
    assert scored["retrieval_recall_at_5"] == 0.0
    assert scored["reciprocal_rank_at_5"] == 0.0
    assert scored["status_match"] is False


def test_summary_reports_insufficient_evidence_separately():
    sufficient = score_case(
        {"id": "gc-01", "expected_status": "ok", "expected_hypothesis_contains": "memory limit"},
        {"status": "ok", "citations": [{"document_id": "uploaded-1"}],
         "hypotheses": [{"text": "memory limit"}]}, {"uploaded-1"}, 100,
    )
    insufficient = score_case(
        {"id": "gc-21", "expected_status": "insufficient_evidence", "expected_hypothesis_contains": None},
        {"status": "insufficient_evidence", "citations": [], "hypotheses": []}, set(), 200,
    )
    result = summarize([sufficient, insufficient])
    assert result["retrieval_recall_at_5"] == 1.0
    assert result["abstention_rate"] == 1.0
    assert result["hypothesis_substring_match"] == 1.0
    assert result["p95_latency_ms"] == 200


def test_live_runner_uploads_waits_and_scores_actual_citation(monkeypatch, tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps([{
        "id": "gc-01", "incident": {"title": "OOM payment", "severity": "HIGH",
                                   "service": "payment", "environment": "preview"},
        "docs": [{"content": "OOM payment runbook"}], "expected_status": "ok",
        "expected_hypothesis_contains": "memory limit",
    }]), encoding="utf-8")

    class Response:
        status_code = 200
        text = ""

        def __init__(self, status, payload):
            self.status_code, self.payload = status, payload

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.headers = {}

        def post(self, url, **kwargs):
            if url.endswith("/documents"):
                assert kwargs["files"]["file"][1] == b"OOM payment runbook"
                return Response(202, {"document_id": "uploaded-1"})
            if url.endswith("/incidents"):
                return Response(201, {"incident_id": "incident-1"})
            if url.endswith("/triage"):
                return Response(200, {"status": "ok", "citations": [{"document_id": "uploaded-1"}],
                                      "hypotheses": [{"text": "memory limit"}]})
            raise AssertionError(url)

        def get(self, url, **kwargs):
            assert url.endswith("/documents")
            return Response(200, {"documents": [{"id": "uploaded-1", "status": "processed"}]})

    monkeypatch.setattr("eval.run_live_benchmark.requests.Session", Session)
    output = tmp_path / "result.json"
    report = run("https://incidentiq-preview.example.workers.dev", dataset, output, "test-key")
    assert report["complete"] is True
    assert report["summary"]["retrieval_recall_at_5"] == 1.0
    assert json.loads(output.read_text())["dataset_sha256"]
