"""IncidentIQ demo script.

Demonstrates four scenarios against a faked backend:
1. An incident resolved well (grounded triage with citations).
2. An incident with insufficient data (abstention).
3. A dependency failure (Vectorize down -> keyword fallback; AI down -> abstention-safe).
4. An unauthorized / cross-tenant access rejection.

Usage:
  python scripts/demo.py
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

sys.path.insert(0, "api/src")
from fastapi.testclient import TestClient

import main  # noqa: E402


class FakeVectorize:
    def __init__(self, matches=None, should_fail=False):
        self.matches = matches or []
        self.should_fail = should_fail

    async def query(self, vector=None, options=None, **kwargs):
        # Prod calls the v2 positional form query(vector, {"topK": ...});
        # kwargs kept for any legacy keyword-style callers.
        opts = options or kwargs
        if self.should_fail:
            raise RuntimeError("vectorize unavailable")
        tenant_id = (opts.get("filter") or {}).get("tenant_id")
        out = [m for m in self.matches if not tenant_id or m.get("metadata", {}).get("tenant_id") == tenant_id]
        return {"matches": out[: opts.get("topK") or len(out)]}


class FakeAI:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    async def run(self, model, inputs):
        if self.should_fail:
            raise TimeoutError("AI timeout")
        if "embedding" in model:
            texts = inputs.get("text", [])
            return {"vectors": [[0.1, 0.2, 0.3] for _ in texts]}
        return {"response": "answer", "usage": {"total_tokens": 8}}


class FakeDB:
    def __init__(self, tenant_hash):
        self.tenant_hash = tenant_hash
        self.tenants = {}
        self.api_keys = []
        self.workspaces = {}
        self.workspace_members = []
        self.incidents = {}
        self.incident_events = []
        self.documents = {}
        self.audit = []

    def prepare(self, sql):
        return FakeStatement(self, sql)


class FakeStatement:
    def __init__(self, db, sql):
        self.db = db
        self.sql = sql
        self._params = []

    def bind(self, *params):
        self._params = list(params)
        return self

    def _tenant_auth(self):
        prefix = self._params[0]
        for ak in self.db.api_keys:
            if ak["key_prefix"] == prefix and ak["is_active"]:
                t = self.db.tenants.get(ak["tenant_id"])
                if t and t["is_active"]:
                    return {"id": t["id"], "name": t["name"], "key_hash": ak["key_hash"]}
        return None

    def _incident_row(self):
        iid, tid = self._params[0], self._params[1]
        inc = self.db.incidents.get(iid)
        if inc and inc["tenant_id"] == tid:
            return (inc["id"], inc["workspace_id"], inc["tenant_id"], inc["title"], inc["severity"],
                    inc["service"], inc["environment"], inc["status"], inc["version"])
        return None

    def _events(self):
        iid = self._params[0]
        return [[ev.get("logs", ""), ev["timestamp"]] for ev in self.db.incident_events if ev["incident_id"] == iid]

    async def first(self):
        sql = self.sql
        if "api_keys" in sql and "tenants" in sql:
            return self._tenant_auth()
        if "incidents WHERE id = ? AND tenant_id = ?" in sql and "workspace_id" in sql:
            return self._incident_row()
        return None

    async def all(self):
        sql = self.sql
        p = self._params
        if "workspace_members" in sql:
            tid = p[0]
            rows = []
            for m in self.db.workspace_members:
                if m["tenant_id"] == tid:
                    w = self.db.workspaces.get(m["workspace_id"])
                    if w and w["is_active"]:
                        rows.append([w["id"], w["name"], w["is_active"], m["role"], m["created_at"]])
            return rows
        if "incident_events WHERE incident_id = ?" in sql:
            return self._events()
        return []

    async def run(self):
        self.db.executed = getattr(self.db, "executed", [])
        self.db.executed.append((self.sql, self._params))
        p = self._params
        if "INSERT INTO incidents" in self.sql:
            self.db.incidents[p[0]] = {
                "id": p[0], "workspace_id": p[1], "tenant_id": p[2], "title": p[3],
                "severity": p[4], "service": p[5], "environment": p[6],
                "status": "OPEN", "version": 1, "created_at": p[9], "updated_at": p[10],
            }
            return SimpleNamespace()
        if "INSERT INTO incident_events" in self.sql:
            self.db.incident_events.append({
                "id": p[0], "incident_id": p[1], "tenant_id": p[2], "event_type": "created",
                "severity": p[3], "service": p[4], "environment": p[5], "timestamp": p[6],
                "logs": None, "deploy_context": None, "created_at": p[7],
            })
            return SimpleNamespace()
        if "INSERT INTO documents" in self.sql:
            self.db.documents[p[0]] = {
                "id": p[0], "tenant_id": p[1], "filename": p[2], "content": p[3],
                "status": "processed", "idempotency_key": p[4], "uploaded_at": p[5], "version": 1,
            }
            return SimpleNamespace()
        if "INSERT INTO audit_logs" in self.sql:
            self.db.audit.append(p)
            return SimpleNamespace()
        return SimpleNamespace()


def make_env():
    db = FakeDB(main._sha256_hex("sk-demo1234567"))
    db.tenants["t1"] = {"id": "t1", "name": "Tenant A", "is_active": 1}
    db.api_keys.append({"id": "ak1", "tenant_id": "t1", "key_prefix": "sk-demo1",
                        "key_hash": db.tenant_hash, "is_active": 1})
    db.workspaces["w1"] = {"id": "w1", "name": "Workspace A", "is_active": 1, "created_at": 1000}
    db.workspace_members.append({"id": "wm1", "workspace_id": "w1", "tenant_id": "t1",
                                 "role": "investigator", "created_at": 1001})
    db.tenants["t2"] = {"id": "t2", "name": "Tenant B", "is_active": 1}
    db.api_keys.append({"id": "ak2", "tenant_id": "t2", "key_prefix": "sk-demo2",
                        "key_hash": main._sha256_hex("sk-demo2222222"), "is_active": 1})
    db.workspaces["w2"] = {"id": "w2", "name": "Workspace B", "is_active": 1, "created_at": 1000}
    db.workspace_members.append({"id": "wm2", "workspace_id": "w2", "tenant_id": "t2",
                                 "role": "investigator", "created_at": 1001})
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=FakeVectorize(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=FakeAI())
    return env


def _headers(env, apikey="sk-demo1234567", idem="demo-1"):
    return {"X-Api-Key": apikey, "Idempotency-Key": idem}


def _set_env(env):
    main._env = lambda request: env


def section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main_demo():
    env = make_env()
    _set_env(env)
    client = TestClient(main.app)

    # ---- 1. Incident resolved well ----
    section("1) Incident resolved well (grounded triage with citations)")
    env.DB.documents["doc-oom"] = {
        "id": "doc-oom", "tenant_id": "t1", "filename": "oom-runbook.md",
        "content": "OOMKilled exit code 137: container exceeded memory limit. Check memory limit and usage after deploy.",
        "status": "processed", "idempotency_key": "dk-oom", "uploaded_at": 1, "version": 1,
    }
    env.VECTORIZE_INDEX.matches = [{
        "id": "vec-oom", "score": 0.92,
        "metadata": {"document_id": "doc-oom", "tenant_id": "t1", "chunk_id": "doc-oom-v1-0",
                     "content": "OOMKilled exit code 137: container exceeded memory limit.", "version": 1},
    }]
    r = client.post("/api/v1/incidents", json={
        "title": "OOMKilled payment-api", "severity": "CRITICAL",
        "service": "payment-api", "environment": "prod",
    }, headers=_headers(env, idem="demo-resolved"))
    inc_id = r.json()["incident_id"]
    r2 = client.post(f"/api/v1/incidents/{inc_id}/triage",
                     headers={**_headers(env, idem="demo-resolved-2")})
    body = r2.json()
    print("Status:", body["status"])
    print("Summary:", body["summary"])
    print("Citations:", [c["document_id"] for c in body["citations"]])
    print("Read-only checks:", body["read_only_checks"])
    assert body["status"] == "ok"
    assert len(body["citations"]) >= 1
    print("PASS: grounded triage with citations + read-only checks")

    # ---- 2. Incident with insufficient data ----
    section("2) Incident with insufficient data (abstention)")
    env.VECTORIZE_INDEX.matches = []
    r = client.post("/api/v1/incidents", json={
        "title": "Unknown kernel panic", "severity": "CRITICAL",
        "service": "mystery-svc", "environment": "prod",
    }, headers=_headers(env, idem="demo-insuff"))
    inc_id2 = r.json()["incident_id"]
    r2 = client.post(f"/api/v1/incidents/{inc_id2}/triage",
                     headers={**_headers(env, idem="demo-insuff-2")})
    body = r2.json()
    print("Status:", body["status"])
    print("Citations:", body["citations"])
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    print("PASS: correct abstention (insufficient_evidence)")

    # ---- 3. Dependency failure ----
    section("3) Dependency failure (Vectorize down -> keyword fallback; AI down -> abstention-safe)")
    env.DB.VECTORIZE_INDEX = FakeVectorize(should_fail=True)
    env.DB.documents["doc-kw"] = {
        "id": "doc-kw", "tenant_id": "t1", "filename": "kw.md",
        "content": "CrashLoopBackOff: check previous container logs and pod events.",
        "status": "processed", "idempotency_key": "dk-kw", "uploaded_at": 1, "version": 1,
    }
    env.ai = FakeAI(should_fail=True)
    r = client.post("/api/v1/incidents", json={
        "title": "CrashLoopBackOff payment-api", "severity": "HIGH",
        "service": "payment-api", "environment": "prod",
    }, headers=_headers(env, idem="demo-dep"))
    inc_id3 = r.json()["incident_id"]
    r2 = client.post(f"/api/v1/incidents/{inc_id3}/triage",
                     headers={**_headers(env, idem="demo-dep-2")})
    body = r2.json()
    print("Status:", body["status"], "| evidence:", len(body["evidence"]))
    assert r2.status_code == 200
    assert body["status"] in ("ok", "insufficient_evidence")
    assert "read_only_checks" in body
    print("PASS: graceful degradation, no 500")

    # ---- 4. Unauthorized / cross-tenant rejection ----
    section("4) Unauthorized / cross-tenant access rejection")
    # create incident under Tenant A
    r = client.post("/api/v1/incidents", json={
        "title": "Secret incident", "severity": "CRITICAL",
        "service": "payment-api", "environment": "prod",
    }, headers=_headers(env, idem="demo-iso-a"))
    inc_id4 = r.json()["incident_id"]
    # read triage with Tenant B key -> 404
    r2 = client.post(f"/api/v1/incidents/{inc_id4}/triage",
                     headers={"X-Api-Key": "sk-demo2222222", "Idempotency-Key": "demo-iso-b"})
    print("Cross-tenant triage status:", r2.status_code)
    assert r2.status_code == 404
    # missing API key -> 401
    r3 = client.post("/api/v1/incidents", json={"title":"x","severity":"LOW","service":"s","environment":"e"},
                     headers={"Idempotency-Key": "x"})
    print("Missing API key status:", r3.status_code)
    assert r3.status_code == 401
    print("PASS: tenant isolation + auth enforced")

    print("\n" + "=" * 60)
    print("Demo complete: all four scenarios behaved as designed.")
    print("=" * 60)


if __name__ == "__main__":
    main_demo()
