#!/usr/bin/env python3
"""Measure IncidentIQ triage against a deployed API and a seeded synthetic corpus.

Unlike the deterministic fake-backed harness, this script uploads documents,
waits for ETL, creates incidents, and scores citations returned by real triage.
It deliberately fails on HTTP/ETL errors instead of converting them to zeroes.

Usage: EVAL_API_KEY=... python eval/run_live_benchmark.py \
  --base-url https://incidentiq-preview.example.workers.dev
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


HERE = Path(__file__).resolve().parent
DEFAULT_DATASET = HERE.parent / "data" / "rag_eval_dataset.json"
DEFAULT_OUTPUT = HERE / "results" / "live_benchmark.json"


def score_case(case: dict[str, Any], body: dict[str, Any], expected_doc_ids: set[str], latency_ms: int,
               http_status: int = 200) -> dict[str, Any]:
    citations = body.get("citations") or []
    observed = [str(c.get("document_id")) for c in citations[:5] if isinstance(c, dict)]
    matched = expected_doc_ids.intersection(observed)
    rank = next((i for i, doc_id in enumerate(observed, 1) if doc_id in expected_doc_ids), None)
    hypothesis_text = " ".join(str(h.get("text", "")) for h in body.get("hypotheses", []) if isinstance(h, dict))
    expected_text = case.get("expected_hypothesis_contains")
    return {
        "id": case["id"],
        "http_status": http_status,
        "expected_status": case["expected_status"],
        "actual_status": body.get("status"),
        "status_match": body.get("status") == case["expected_status"],
        "expected_document_count": len(expected_doc_ids),
        "citation_count": len(citations),
        "retrieval_recall_at_5": len(matched) / len(expected_doc_ids) if expected_doc_ids else 0.0,
        "reciprocal_rank_at_5": 1.0 / rank if rank else 0.0,
        "hypothesis_substring_match": (expected_text.lower() in hypothesis_text.lower()) if expected_text else None,
        "hypothesis_excerpt": hypothesis_text[:160],
        "latency_ms": latency_ms,
        "tokens_used": body.get("tokens_used"),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    sufficient = [r for r in results if r["expected_status"] == "ok"]
    insufficient = [r for r in results if r["expected_status"] == "insufficient_evidence"]
    latencies = sorted(r["latency_ms"] for r in results)
    rate = lambda xs, field: sum(float(r[field]) for r in xs) / len(xs) if xs else None
    return {
        "completed_cases": len(results),
        "http_error_rate": sum(r.get("http_status") != 200 for r in results) / len(results) if results else None,
        "sufficient_cases": len(sufficient),
        "insufficient_cases": len(insufficient),
        "retrieval_recall_at_5": rate(sufficient, "retrieval_recall_at_5"),
        "citation_mrr_at_5": rate(sufficient, "reciprocal_rank_at_5"),
        "hypothesis_substring_match": rate(sufficient, "hypothesis_substring_match"),
        "abstention_rate": sum(r["actual_status"] == "insufficient_evidence" for r in insufficient) / len(insufficient) if insufficient else None,
        "status_accuracy": sum(r["status_match"] for r in results) / len(results) if results else None,
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "p95_latency_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
    }


def require_response(response: requests.Response, expected_status: int, label: str) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise RuntimeError(f"{label}: HTTP {response.status_code}; expected {expected_status}; body={response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"{label}: non-JSON response") from exc


def wait_for_documents(session: requests.Session, base_url: str, ids: set[str], timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = session.get(f"{base_url}/api/v1/documents", timeout=30)
        docs = require_response(response, 200, "list documents").get("documents", [])
        status_by_id = {str(doc.get("id")): doc for doc in docs}
        failed = {doc_id: status_by_id[doc_id].get("error") for doc_id in ids
                  if doc_id in status_by_id and status_by_id[doc_id].get("status") == "failed"}
        if failed:
            raise RuntimeError(f"ETL failed for uploaded documents: {failed}")
        if all(status_by_id.get(doc_id, {}).get("status") == "processed" for doc_id in ids):
            return
        time.sleep(5)
    raise TimeoutError(f"ETL did not process all {len(ids)} uploaded documents within {timeout_seconds}s")


def run(base_url: str, dataset_path: Path, output: Path, api_key: str, wait_seconds: int = 180,
        inter_case_delay: float = 2.0) -> dict[str, Any]:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        raise ValueError("Use HTTPS for remote APIs; HTTP is allowed only on localhost")
    if not api_key:
        raise ValueError("EVAL_API_KEY is required for authenticated live evaluation")
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must contain at least one case")
    dataset_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    run_id = f"livebench-{uuid.uuid4().hex[:12]}"
    session = requests.Session()
    session.headers.update({"X-Api-Key": api_key})
    base_url = base_url.rstrip("/")
    result: dict[str, Any] = {
        "benchmark_type": "live_preview_triage", "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url, "dataset": str(dataset_path), "dataset_sha256": dataset_hash,
        "git_sha": os.getenv("GITHUB_SHA", "local-unrecorded"),
        "method": "Upload synthetic documents, wait for ETL, create incidents, call triage; score citations by uploaded document ID. Hypothesis score is substring matching, not semantic grading. HTTP errors are counted, not silently scored as retrieval misses.",
        "inter_case_delay_seconds": inter_case_delay,
        "results": [], "errors": [], "complete": False,
    }
    uploaded: dict[str, set[str]] = {}
    try:
        all_ids: set[str] = set()
        for case in cases:
            case_ids: set[str] = set()
            for index, doc in enumerate(case.get("docs", [])):
                filename = f"{run_id}-{case['id']}-{index}.txt"
                response = session.post(
                    f"{base_url}/api/v1/documents",
                    headers={"Idempotency-Key": f"{run_id}-doc-{case['id']}-{index}"},
                    files={"file": (filename, doc["content"].encode("utf-8"), "text/plain")},
                    timeout=60,
                )
                payload = require_response(response, 202, f"upload {case['id']}")
                doc_id = str(payload.get("document_id", ""))
                if not doc_id:
                    raise RuntimeError(f"upload {case['id']}: missing document_id")
                case_ids.add(doc_id)
                all_ids.add(doc_id)
            uploaded[case["id"]] = case_ids
        if all_ids:
            wait_for_documents(session, base_url, all_ids, wait_seconds)

        for case_index, case in enumerate(cases):
            incident = dict(case["incident"])
            response = session.post(
                f"{base_url}/api/v1/incidents", json=incident,
                headers={"Idempotency-Key": f"{run_id}-incident-{case['id']}"}, timeout=30,
            )
            payload = require_response(response, 201, f"create incident {case['id']}")
            incident_id = payload.get("incident_id")
            if not incident_id:
                raise RuntimeError(f"create incident {case['id']}: missing incident_id")
            start = time.monotonic()
            response = None
            try:
                response = session.post(f"{base_url}/api/v1/incidents/{incident_id}/triage", json={}, timeout=90)
                latency_ms = round((time.monotonic() - start) * 1000)
                body = require_response(response, 200, f"triage {case['id']}")
                result["results"].append(score_case(case, body, uploaded[case["id"]], latency_ms))
            except (requests.RequestException, RuntimeError) as exc:
                latency_ms = round((time.monotonic() - start) * 1000)
                status_code = response.status_code if response is not None else 0
                result["errors"].append(str(exc))
                result["results"].append(score_case(case, {"status": "http_error"}, uploaded[case["id"]],
                                                    latency_ms, http_status=status_code))
            if case_index + 1 < len(cases) and inter_case_delay > 0:
                time.sleep(inter_case_delay)
        result["complete"] = True
    except (requests.RequestException, RuntimeError, TimeoutError, ValueError) as exc:
        result["errors"].append(str(exc))
    finally:
        result["summary"] = summarize(result["results"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if not result["complete"]:
        raise RuntimeError(f"Live benchmark incomplete: {result['errors']}; report={output}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--inter-case-delay", type=float, default=2.0)
    args = parser.parse_args()
    report = run(args.base_url, args.dataset, args.output, os.getenv("EVAL_API_KEY", ""),
                 args.wait_seconds, args.inter_case_delay)
    print(json.dumps(report["summary"], indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
