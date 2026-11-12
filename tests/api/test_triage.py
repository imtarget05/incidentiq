"""Tests for grounded incident triage (Slice 3)."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import main  # noqa: E402 (conftest adds api/src to path)


class FakeVectorize:
    def __init__(self, matches=None):
        self.matches = matches or []
        self.upserted = []
        self.deleted = []

    async def query(self, vector=None, topK=None, returnMetadata=None, filter=None):
        # tenant isolation: only return matches whose metadata.tenant_id == filter tenant_id
        tenant_id = (filter or {}).get("tenant_id")
        out = []
        for m in self.matches:
            if tenant_id and m.get("metadata", {}).get("tenant_id") != tenant_id:
                continue
            out.append(m)
        return {"matches": out[: topK or len(out)]}

    async def upsert(self, points):
        self.upserted = list(points)
        return SimpleNamespace()

    async def deleteByIds(self, ids=None):
        return await self.delete(ids=ids)

    async def delete(self, ids=None):
        self.deleted = list(ids or [])
        return SimpleNamespace()


class FakeAI:
    def __init__(self, embed_vector=None, llm_response=None):
        self.embed_vector = embed_vector or [0.1] * 1024
        self.llm_response = llm_response or "answer"
        self.calls = []

    async def run(self, model, inputs):
        self.calls.append((model, inputs))
        if "embedding" in model:
            texts = inputs.get("text", [])
            return {"vectors": [list(self.embed_vector) for _ in texts]}
        return {"response": self.llm_response, "usage": {"total_tokens": 10}}


class FakeDB:
    def __init__(self, tenant_hash):
        self.tenant_hash = tenant_hash
        self.tenants = {}
        self.api_keys = []
        self.workspaces = {}
        self.workspace_members = []
        self.incidents = {}
        self.incident_events = []
        self.documents = {}   # id -> doc dict (for FTS5)
        self.audit = []
        self.executed = []
        self.triage_reports = []
        self.fail_triage_report = False

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
            return (
                inc["id"], inc["workspace_id"], inc["tenant_id"], inc["title"],
                inc["severity"], inc["service"], inc["environment"], inc["status"],
                inc["version"],
            )
        return None

    def _events(self):
        iid = self._params[0]
        out = []
        for ev in self.db.incident_events:
            if ev["incident_id"] == iid:
                out.append([ev.get("logs", ""), ev["timestamp"]])
        out.sort(key=lambda r: r[1], reverse=True)
        return out[:3]

    def _fts(self):
        query = self._params[0]
        tid = self._params[1]
        terms = [t for t in query.lower().split() if len(t) > 2]
        out = []
        for doc in self.db.documents.values():
            if doc["tenant_id"] != tid:
                continue
            content = (doc.get("content") or "").lower()
            if not terms or any(term in content for term in terms):
                out.append([doc["id"], doc.get("filename", ""), doc.get("content", ""), 0])
        return out

    def _similar(self):
        tid, service, iid, limit = self._params[0], self._params[1], self._params[2], self._params[3]
        out = []
        for inc in self.db.incidents.values():
            if inc["tenant_id"] == tid and inc["service"] == service and inc["id"] != iid:
                out.append([inc["id"]])
        out.sort(key=lambda r: r[0])
        return out[:limit]

    async def first(self):
        sql = self.sql
        p = self._params
        if "api_keys" in sql and "tenants" in sql:
            return self._tenant_auth()
        if "incidents WHERE id = ? AND tenant_id = ?" in sql and "workspace_id" in sql:
            return self._incident_row()
        if "idempotency_key" in sql and "documents" in sql:
            ik, tid = p[0], p[1]
            for doc in self.db.documents.values():
                if doc.get("idempotency_key") == ik and doc["tenant_id"] == tid:
                    return (doc["id"],)
            return None
        if "triage_reports WHERE incident_id = ?" in sql:
            incident_id, tenant_id = p[0], p[1]
            for report in reversed(self.db.triage_reports):
                if report[1] == incident_id and report[2] == tenant_id:
                    return (report[0], report[3], report[4], report[5], report[6],
                            report[7], report[8], report[9], report[10])
            return None
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
        if "documents_fts" in sql and "MATCH" in sql:
            return self._fts()
        if "SELECT id FROM incidents WHERE tenant_id = ? AND service = ?" in sql:
            return self._similar()
        return []

    async def run(self):
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
                "id": p[0], "incident_id": p[1], "tenant_id": p[2], "event_type": p[3],
                "severity": p[4], "service": p[5], "environment": p[6],
                "timestamp": p[6], "logs": None, "deploy_context": None, "created_at": p[7],
            })
            return SimpleNamespace()
        if "INSERT INTO documents" in self.sql:
            self.db.documents[p[0]] = {
                "id": p[0], "tenant_id": p[1], "filename": p[2], "content": p[3],
                "status": "processed", "idempotency_key": p[4], "uploaded_at": p[5],
                "version": 1,
            }
            return SimpleNamespace()
        if "INSERT INTO audit_logs" in self.sql:
            self.db.audit.append(p)
            return SimpleNamespace()
        if "INSERT INTO triage_reports" in self.sql:
            if self.db.fail_triage_report:
                raise RuntimeError("D1 report write failed")
            self.db.triage_reports.append(p)
            return SimpleNamespace()
        return SimpleNamespace()


def make_env(tenant_hash, tenant_id):
    db = FakeDB(tenant_hash)
    return SimpleNamespace(
        DB=db,
        VECTORIZE_INDEX=FakeVectorize(),
        ETL_QUEUE=SimpleNamespace(),
        ETL_DLQ=SimpleNamespace(),
        ai=FakeAI(),
    )


def _set_env(monkeypatch, env):
    monkeypatch.setattr(main, "_env", lambda request: env)


def _headers(env, idem="ik-1", apikey="sk-test12345678"):
    return {
        "X-Api-Key": apikey,
        "Idempotency-Key": idem,
    }


def _setup_db(env, llm_response):
    db = env.DB
    db.tenants["t1"] = {"id": "t1", "name": "Tenant One", "is_active": 1}
    db.api_keys.append({
        "id": "ak1", "tenant_id": "t1", "key_prefix": "sk-test1",
        "key_hash": db.tenant_hash, "is_active": 1,
    })
    db.workspaces["w1"] = {"id": "w1", "name": "Workspace One", "is_active": 1, "created_at": 1000}
    db.workspace_members.append({
        "id": "wm1", "workspace_id": "w1", "tenant_id": "t1", "role": "investigator", "created_at": 1001,
    })
    env.ai = FakeAI(llm_response=llm_response)
    # tenant t2 isolated
    db.tenants["t2"] = {"id": "t2", "name": "Tenant Two", "is_active": 1}
    db.api_keys.append({
        "id": "ak2", "tenant_id": "t2", "key_prefix": "sk-test2",
        "key_hash": main._sha256_hex("sk-test22222222"), "is_active": 1,
    })
    db.workspaces["w2"] = {"id": "w2", "name": "Workspace Two", "is_active": 1, "created_at": 1000}
    db.workspace_members.append({
        "id": "wm2", "workspace_id": "w2", "tenant_id": "t2", "role": "investigator", "created_at": 1001,
    })


# --------------------------------------------------------------------------- triage

def test_triage_grounded_with_citations(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env, llm_response='{"summary": "OOM kill do lan bo nho.", "hypotheses": [{"text": "Container vuot gioi han bo nho", "confirmed": false}]}')
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="triage-1")
    # create incident
    r = client.post("/api/v1/incidents", json={
        "title": "OOMKilled payment-api", "severity": "CRITICAL",
        "service": "payment-api", "environment": "prod",
    }, headers=h)
    inc_id = r.json()["incident_id"]
    # add a runbook document + vector match
    env.DB.documents["doc-1"] = {
        "id": "doc-1", "tenant_id": "t1", "filename": "oom-runbook.md",
        "content": "OOMKilled exit code 137: check memory limit and usage after deploy.",
        "status": "processed", "idempotency_key": "dk-1", "uploaded_at": 1, "version": 1,
    }
    env.VECTORIZE_INDEX.matches = [{
        "id": "vec-1", "score": 0.9,
        "metadata": {"document_id": "doc-1", "tenant_id": "t1", "chunk_id": "doc-1-v1-0",
                     "content": "OOMKilled exit code 137: check memory limit and usage after deploy.",
                     "version": 1},
    }]
    r2 = client.post(f"/api/v1/incidents/{inc_id}/triage",
                     headers={**h, "Idempotency-Key": "triage-1-2"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "ok"
    assert body["incident_id"] == inc_id
    assert "summary" in body
    assert len(body["citations"]) >= 1
    assert body["citations"][0]["document_id"] == "doc-1"
    assert len(body["read_only_checks"]) >= 1
    # similar incidents: none for t1 payment-api (only one incident)
    assert body["similar_incidents"] == []
    saved = client.get(f"/api/v1/incidents/{inc_id}/report", headers=h)
    assert saved.status_code == 200
    assert saved.json()["summary"] == body["summary"]


def test_triage_insufficient_evidence(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env, llm_response="answer")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="triage-ie")
    r = client.post("/api/v1/incidents", json={
        "title": "Unknown error xyz", "severity": "HIGH",
        "service": "mystery-svc", "environment": "prod",
    }, headers=h)
    inc_id = r.json()["incident_id"]
    # no documents, no vector matches
    r2 = client.post(f"/api/v1/incidents/{inc_id}/triage",
                     headers={**h, "Idempotency-Key": "triage-ie-2"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert body["evidence"] == []


def test_triage_not_found(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env, llm_response="answer")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="triage-nf")
    r = client.post("/api/v1/incidents/does-not-exist/triage",
                    headers={**h, "Idempotency-Key": "tnf-1"})
    assert r.status_code == 404


def test_triage_tenant_isolation(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env, llm_response="answer")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    # create incident under t1
    h1 = _headers(env, apikey="sk-test12345678", idem="triage-iso")
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h1)
    inc_id = r.json()["incident_id"]
    # read triage with tenant t2 key -> not found (isolated)
    h2 = _headers(env, apikey="sk-test22222222", idem="triage-iso-2")
    r2 = client.post(f"/api/v1/incidents/{inc_id}/triage",
                     headers={**h2, "Idempotency-Key": "ti-2"})
    assert r2.status_code == 404


def test_triage_similar_incidents(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env, llm_response="answer")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="triage-sim")
    # create two incidents for same service
    r1 = client.post("/api/v1/incidents", json={
        "title": "First OOM", "severity": "CRITICAL",
        "service": "payment-api", "environment": "prod",
    }, headers={**h, "Idempotency-Key": "sim-1"})
    inc1 = r1.json()["incident_id"]
    r2 = client.post("/api/v1/incidents", json={
        "title": "Second OOM", "severity": "CRITICAL",
        "service": "payment-api", "environment": "prod",
    }, headers={**h, "Idempotency-Key": "sim-2"})
    inc2 = r2.json()["incident_id"]
    # add document + vector so triage returns ok
    env.DB.documents["doc-1"] = {
        "id": "doc-1", "tenant_id": "t1", "filename": "r.md",
        "content": "OOMKilled check memory limit", "status": "processed",
        "idempotency-key": "dk", "uploaded_at": 1, "version": 1,
    }
    env.VECTORIZE_INDEX.matches = [{
        "id": "vec-1", "score": 0.9,
        "metadata": {"document_id": "doc-1", "tenant_id": "t1", "chunk_id": "doc-1-v1-0",
                     "content": "OOMKilled check memory limit", "version": 1},
    }]
    r3 = client.post(f"/api/v1/incidents/{inc1}/triage",
                     headers={**h, "Idempotency-Key": "sim-3"})
    assert r3.status_code == 200, r3.text
    assert inc2 in r3.json()["similar_incidents"]


def test_triage_read_only_no_production_writes(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env, llm_response="answer")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="triage-ro")
    r = client.post("/api/v1/incidents", json={
        "title": "OOMKilled payment-api", "severity": "CRITICAL",
        "service": "payment-api", "environment": "prod",
    }, headers=h)
    inc_id = r.json()["incident_id"]
    env.DB.documents["doc-1"] = {
        "id": "doc-1", "tenant_id": "t1", "filename": "r.md",
        "content": "OOMKilled check memory limit after deploy.", "status": "processed",
        "idempotency_key": "dk", "uploaded_at": 1, "version": 1,
    }
    env.VECTORIZE_INDEX.matches = [{
        "id": "vec-1", "score": 0.9,
        "metadata": {"document_id": "doc-1", "tenant_id": "t1", "chunk_id": "doc-1-v1-0",
                     "content": "OOMKilled check memory limit after deploy.", "version": 1},
    }]
    before_writes = len([e for e in env.DB.executed if e[0].strip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "audit_logs" not in e[0] and "rate_limit_buckets" not in e[0] and "triage_reports" not in e[0] and "triage_metrics" not in e[0] and "token_usage_log" not in e[0]])
    client.post(f"/api/v1/incidents/{inc_id}/triage",
                headers={**h, "Idempotency-Key": "triage-ro-2"})
    # triage should not INSERT/UPDATE/DELETE incidents or documents (only audit + rate-limit bookkeeping)
    writes_after = [e for e in env.DB.executed if e[0].strip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "audit_logs" not in e[0] and "rate_limit_buckets" not in e[0] and "triage_reports" not in e[0] and "triage_metrics" not in e[0] and "token_usage_log" not in e[0]]
    assert len(writes_after) == before_writes, writes_after


def test_triage_report_no_report(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env, llm_response="answer")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="triage-rep")
    r = client.get("/api/v1/incidents/does-not-exist/report", headers=h)
    assert r.status_code == 404


def test_triage_returns_service_unavailable_when_report_cannot_be_saved(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env, llm_response="answer")
    env.DB.fail_triage_report = True
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    headers = _headers(env, idem="triage-persist-fail")
    created = client.post("/api/v1/incidents", json={
        "title": "Unknown error", "severity": "HIGH",
        "service": "api", "environment": "staging",
    }, headers=headers)
    incident_id = created.json()["incident_id"]

    response = client.post(f"/api/v1/incidents/{incident_id}/triage",
                           headers={**headers, "Idempotency-Key": "triage-persist-fail-2"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "report_persist_failed"
