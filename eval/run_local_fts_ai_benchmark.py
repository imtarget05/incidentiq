#!/usr/bin/env python3
"""Run the real triage route with local SQLite FTS5 and live Workers AI.

Vectorize and ETL are deliberately absent. This measures keyword retrieval plus
LLM synthesis, not hybrid retrieval, hosted preview, or production readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api" / "src"))
import main as api  # noqa: E402
from eval.run_live_benchmark import score_case, summarize  # noqa: E402


class LocalStatement:
    def __init__(self, db: LocalDB, sql: str):
        self.db, self.sql, self.params = db, sql, ()

    def bind(self, *params: Any) -> LocalStatement:
        self.params = params
        return self

    async def first(self) -> sqlite3.Row | None:
        return self.db.conn.execute(self.sql, self.params).fetchone()

    async def all(self) -> list[sqlite3.Row]:
        return self.db.conn.execute(self.sql, self.params).fetchall()

    async def run(self) -> SimpleNamespace:
        self.db.conn.execute(self.sql, self.params)
        self.db.conn.commit()
        return SimpleNamespace()


class LocalDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        for name in ("001_initial.sql", "002_incident.sql", "003_datamart.sql", "004_v2_tokens.sql"):
            self.conn.executescript((ROOT / "migrations" / name).read_text(encoding="utf-8"))

    def prepare(self, sql: str) -> LocalStatement:
        return LocalStatement(self, sql)


class NoVectorize:
    async def query(self, *_args: Any, **_kwargs: Any) -> dict[str, list]:
        return {"matches": []}


class WorkersAI:
    def __init__(self, account_id: str, token: str):
        self.account_id, self.token = account_id, token
        self.usage: list[dict[str, int]] = []

    async def run(self, model: str, inputs: dict[str, Any]) -> dict[str, Any]:
        if "embedding" in model:
            return {"vectors": []}  # Keyword-only run; no Vectorize index is seeded.
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{model}"
        request = urllib.request.Request(
            url, data=json.dumps(inputs).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
        if not payload.get("success"):
            raise RuntimeError("Workers AI returned an unsuccessful response")
        result = payload["result"]
        usage = result.get("usage", {})
        self.usage.append({
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        })
        return result


def seed(db: LocalDB, cases: list[dict[str, Any]], api_key: str) -> None:
    now = int(time.time() * 1000)
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    db.conn.execute("INSERT INTO tenants VALUES (?, ?, ?, 1)", ("local", "Local benchmark", now))
    db.conn.execute(
        "INSERT INTO api_keys(id, tenant_id, key_prefix, key_hash, created_at, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)", ("local-key", "local", api_key[:8], key_hash, now),
    )
    db.conn.execute("INSERT INTO workspaces VALUES (?, ?, ?, 1)", ("local-workspace", "Local benchmark", now))
    db.conn.execute(
        "INSERT INTO workspace_members VALUES (?, ?, ?, ?, ?)",
        ("local-member", "local-workspace", "local", "investigator", now),
    )
    for index, case in enumerate(cases):
        for document in case.get("docs", []):
            db.conn.execute(
                "INSERT INTO documents(id, tenant_id, filename, content, status, uploaded_at, version) "
                "VALUES (?, ?, ?, ?, 'processed', ?, 1)",
                (document["id"], "local", document["filename"], document["content"], now + index),
            )
    db.conn.commit()


def run(account_id: str, token: str, dataset: Path, output: Path, limit: int | None = None,
        case_id: str | None = None) -> dict[str, Any]:
    cases = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must contain at least one case")
    selected = [case for case in cases if case["id"] == case_id] if case_id else (cases[:limit] if limit else cases)
    if not selected:
        raise ValueError(f"No case matches {case_id}")
    db = LocalDB()
    api_key = "sk-local-benchmark-" + os.urandom(12).hex()
    seed(db, cases, api_key)
    ai = WorkersAI(account_id, token)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=NoVectorize(), ai=ai,
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace())
    api._env = lambda request: env
    client = TestClient(api.app)
    headers = {"X-Api-Key": api_key}
    report: dict[str, Any] = {
        "benchmark_type": "local_sqlite_fts5_live_workers_ai_keyword_only",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset.relative_to(ROOT)),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "model": "@cf/openai/gpt-oss-20b", "max_tokens": 1536,
        "scope": "Real FastAPI triage route, in-memory SQLite migrations and FTS5, live Cloudflare Workers AI. "
                 "All dataset documents preseeded; Vectorize and ETL excluded. Synthetic cases only.",
        "results": [], "errors": [], "complete": False,
    }
    try:
        for case in selected:
            case_id = case["id"]
            created = client.post("/api/v1/incidents", json=case["incident"],
                                  headers={**headers, "Idempotency-Key": f"local-{case_id}"})
            if created.status_code != 201:
                raise RuntimeError(f"{case_id}: create HTTP {created.status_code}")
            incident_id = created.json()["incident_id"]
            started = time.monotonic()
            response = client.post(f"/api/v1/incidents/{incident_id}/triage",
                                   headers={**headers, "Idempotency-Key": f"local-triage-{case_id}"})
            elapsed_ms = round((time.monotonic() - started) * 1000)
            body = response.json()
            expected_ids = {doc["id"] for doc in case.get("docs", [])}
            result = score_case(case, body, expected_ids, elapsed_ms, response.status_code)
            report["results"].append(result)
            if response.status_code != 200:
                report["errors"].append(f"{case_id}: triage HTTP {response.status_code}")
            print(f"{case_id}: HTTP {response.status_code}, {body.get('status')}, "
                  f"citations={result['citation_count']}, latency={elapsed_ms}ms", flush=True)
        report["complete"] = True
    finally:
        prompt_tokens = sum(row["prompt_tokens"] for row in ai.usage)
        completion_tokens = sum(row["completion_tokens"] for row in ai.usage)
        report["usage"] = {
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "estimated_inference_usd": round(prompt_tokens * 0.20 / 1_000_000 +
                                             completion_tokens * 0.30 / 1_000_000, 6),
            "pricing_source": "https://developers.cloudflare.com/workers-ai/models/gpt-oss-20b/",
            "pricing_note": "Estimate from token counts and listed unit prices; not a billing export.",
        }
        report["summary"] = summarize(report["results"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        db.conn.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/rag_eval_dataset.json")
    parser.add_argument("--output", type=Path, default=ROOT / "eval/results/local_fts_ai_benchmark.json")
    parser.add_argument("--account-id", default=os.getenv("CLOUDFLARE_ACCOUNT_ID", ""))
    parser.add_argument("--wrangler-oauth-config", type=Path,
                        help="Optional local Wrangler config; its token is read but never included in the report")
    parser.add_argument("--limit", type=int, help="Run only the first N cases for a smoke test")
    parser.add_argument("--case-id", help="Run one case while keeping the full corpus seeded")
    args = parser.parse_args()
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    if args.wrangler_oauth_config:
        token = tomllib.loads(args.wrangler_oauth_config.read_text(encoding="utf-8"))["oauth_token"]
    if not args.account_id or not token:
        parser.error("Cloudflare account ID and API token (or Wrangler OAuth config) are required")
    report = run(args.account_id, token, args.dataset, args.output, args.limit, args.case_id)
    print(json.dumps(report["summary"], indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
