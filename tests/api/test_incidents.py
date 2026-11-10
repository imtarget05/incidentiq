"""Tests for IncidentIQ incident workflow (Slice 1).

Runs locally without Cloudflare bindings by monkeypatching `main._env`.
Covers: create/idempotency, auth, validation, status transitions, optimistic
concurrency, tenant isolation, event + timeline.
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import main  # noqa: E402 (conftest adds api/src to path)


class FakeDB:
    def __init__(self, tenant_hash):
        self.tenant_hash = tenant_hash
        self.tenants = {}
        self.api_keys = []
        self.workspaces = {}
        self.workspace_members = []
        self.incidents = {}
        self.incident_events = []
        self.audit = []
        self.executed = []

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

    def _existing_incident(self):
        ik, tenant_id = self._params[0], self._params[1]
        for inc in self.db.incidents.values():
            if inc["tenant_id"] == tenant_id and inc.get("idempotency_key") == ik:
                return (inc["id"], inc.get("payload_hash"))
        return None

    def _get_incident(self):
        incident_id, tenant_id = self._params[0], self._params[1]
        inc = self.db.incidents.get(incident_id)
        if inc and inc["tenant_id"] == tenant_id:
            return (
                inc["id"], inc["workspace_id"], inc["tenant_id"], inc["title"], inc["severity"],
                inc["service"], inc["environment"], inc["status"], inc["version"],
                inc.get("payload_hash"), inc["created_at"], inc["updated_at"], inc.get("resolved_at"),
            )
        return None

    def _get_incident_workspace(self):
        incident_id, tenant_id = self._params[0], self._params[1]
        inc = self.db.incidents.get(incident_id)
        if inc and inc["tenant_id"] == tenant_id:
            return (inc["id"], inc["workspace_id"])
        return None

    def _workspaces_for_tenant(self):
        tenant_id = self._params[0]
        rows = []
        for m in self.db.workspace_members:
            if m["tenant_id"] == tenant_id:
                w = self.db.workspaces.get(m["workspace_id"])
                if w and w["is_active"]:
                    rows.append([w["id"], w["name"], w["is_active"], m["role"], m["created_at"]])
        return rows

    def _timeline_events(self):
        incident_id = self._params[0]
        out = []
        for ev in self.db.incident_events:
            if ev["incident_id"] == incident_id:
                out.append([
                    ev["id"], ev["event_type"], ev.get("severity"), ev.get("service"),
                    ev.get("environment"), ev["timestamp"], ev.get("logs"),
                    ev.get("deploy_context"), ev["created_at"],
                ])
        out.sort(key=lambda r: (r[8], r[0]))
        return out

    async def first(self):
        sql = self.sql
        if "api_keys" in sql and "tenants" in sql:
            return self._tenant_auth()
        if "idempotency_key" in sql and "incidents" in sql:
            return self._existing_incident()
        if "incidents WHERE id = ? AND tenant_id = ?" in sql:
            return self._get_incident()
        if "workspace_id FROM incidents WHERE id = ?" in sql:
            return self._get_incident_workspace()
        return None

    async def all(self):
        sql = self.sql
        if "workspace_members" in sql:
            return self._workspaces_for_tenant()
        if "incident_events WHERE incident_id = ?" in sql:
            return self._timeline_events()
        return []

    async def run(self):
        self.db.executed.append((self.sql, self._params))
        p = self._params
        if "INSERT INTO incidents" in self.sql:
            # bind: id(0), workspace_id(1), tenant_id(2), title(3), severity(4),
            # service(5), environment(6), payload_hash(7), idempotency_key(8),
            # created_at(9), updated_at(10)
            p = self._params
            self.db.incidents[p[0]] = {
                "id": p[0], "workspace_id": p[1], "tenant_id": p[2], "title": p[3],
                "severity": p[4], "service": p[5], "environment": p[6],
                "status": "OPEN", "version": 1, "payload_hash": p[7],
                "idempotency_key": p[8],
                "created_at": p[9], "updated_at": p[10], "resolved_at": None,
            }
            return SimpleNamespace()
        if "INSERT INTO incident_events" in self.sql:
            p = self._params
            if len(p) == 11:
                # add event: id, incident_id, tenant_id, event_type, severity, service, environment,
                # timestamp, logs, deploy_context, created_at
                self.db.incident_events.append({
                    "id": p[0], "incident_id": p[1], "tenant_id": p[2], "event_type": p[3],
                    "severity": p[4], "service": p[5], "environment": p[6],
                    "timestamp": p[7], "logs": p[8], "deploy_context": p[9], "created_at": p[10],
                })
            elif len(p) == 8:
                # create event: id, incident_id, tenant_id, severity, service, environment, timestamp, created_at
                self.db.incident_events.append({
                    "id": p[0], "incident_id": p[1], "tenant_id": p[2], "event_type": "created",
                    "severity": p[3], "service": p[4], "environment": p[5],
                    "timestamp": p[6], "logs": None, "deploy_context": None, "created_at": p[7],
                })
            elif len(p) == 5:
                # status_changed event: id, incident_id, tenant_id, timestamp, created_at
                self.db.incident_events.append({
                    "id": p[0], "incident_id": p[1], "tenant_id": p[2], "event_type": "status_changed",
                    "severity": None, "service": None, "environment": None,
                    "timestamp": p[3], "logs": None, "deploy_context": None, "created_at": p[4],
                })
            return SimpleNamespace()
        if "UPDATE incidents SET status" in self.sql:
            incident_id, tenant_id = p[4], p[5]
            where_version = p[6]
            inc = self.db.incidents.get(incident_id)
            if inc and inc["tenant_id"] == tenant_id and inc["version"] == where_version:
                inc["status"] = p[0]
                inc["version"] = p[1]
                inc["updated_at"] = p[2]
                inc["resolved_at"] = p[3]
            return SimpleNamespace()
        if "UPDATE incidents SET updated_at" in self.sql:
            inc = self.db.incidents.get(p[1])
            if inc:
                inc["updated_at"] = p[0]
            return SimpleNamespace()
        if "INSERT INTO audit_logs" in self.sql:
            self.db.audit.append({
                "id": p[0], "tenant_id": p[1], "actor": p[2], "action": p[3],
                "resource": p[4], "metadata": p[5], "created_at": p[6],
            })
            return SimpleNamespace()
        return SimpleNamespace()


class FakeVectorize:
    def __init__(self):
        self.upserted = []

    async def upsert(self, points):
        self.upserted = points
        return SimpleNamespace()


class FakeQueue:
    def __init__(self):
        self.sent = []

    async def send(self, body):
        self.sent.append(body)
        return SimpleNamespace()


class FakeAI:
    def __init__(self):
        self.calls = []

    async def run(self, model, inputs):
        self.calls.append((model, inputs))
        if "embedding" in model:
            return {"vectors": [[0.1] * 1024]}
        return {"response": "answer", "usage": {"total_tokens": 5}}


def make_env(tenant_hash, tenant_id):
    db = FakeDB(tenant_hash)
    return SimpleNamespace(
        DB=db,
        VECTORIZE_INDEX=FakeVectorize(),
        ETL_QUEUE=FakeQueue(),
        ETL_DLQ=FakeQueue(),
        ai=FakeAI(),
    )


def _set_env(monkeypatch, env):
    monkeypatch.setattr(main, "_env", lambda request: env)


def _headers(env, idem="ik-1", apikey="sk-test12345678"):
    return {
        "X-Api-Key": apikey,
        "Idempotency-Key": idem,
    }


def _setup_db(db):
    # tenant t1 (key sk-test12345678) + workspace + investigator member
    db.tenants["t1"] = {"id": "t1", "name": "Tenant One", "is_active": 1}
    db.api_keys.append({
        "id": "ak1", "tenant_id": "t1", "key_prefix": "sk-test1",
        "key_hash": db.tenant_hash, "is_active": 1,
    })
    db.workspaces["w1"] = {"id": "w1", "name": "Workspace One", "is_active": 1, "created_at": 1000}
    db.workspace_members.append({
        "id": "wm1", "workspace_id": "w1", "tenant_id": "t1", "role": "investigator", "created_at": 1001,
    })
    # tenant t2 (different key) + workspace, isolated
    db.tenants["t2"] = {"id": "t2", "name": "Tenant Two", "is_active": 1}
    db.api_keys.append({
        "id": "ak2", "tenant_id": "t2", "key_prefix": "sk-test2",
        "key_hash": main._sha256_hex("sk-test22222222"), "is_active": 1,
    })
    db.workspaces["w2"] = {"id": "w2", "name": "Workspace Two", "is_active": 1, "created_at": 1000}
    db.workspace_members.append({
        "id": "wm2", "workspace_id": "w2", "tenant_id": "t2", "role": "investigator", "created_at": 1001,
    })


# --------------------------------------------------------------------------- create

def test_create_incident_success(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-1")
    r = client.post("/api/v1/incidents", json={
        "title": "OOMKilled payment-api", "severity": "CRITICAL",
        "service": "payment-api", "environment": "prod",
    }, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "created"
    inc_id = body["incident_id"]
    assert inc_id in env.DB.incidents
    inc = env.DB.incidents[inc_id]
    assert inc["status"] == "OPEN"
    assert inc["version"] == 1
    assert inc["workspace_id"] == "w1"
    # created event + audit
    assert any(e["event_type"] == "created" for e in env.DB.incident_events if e["incident_id"] == inc_id)
    assert any(a["action"] == "incident.create" for a in env.DB.audit)


def test_create_incident_idempotent_duplicate(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-dup")
    r1 = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h)
    assert r1.status_code == 201
    inc_id = r1.json()["incident_id"]
    r2 = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h)
    assert r2.status_code == 202
    assert r2.json()["status"] == "duplicate"
    assert r2.json()["incident_id"] == inc_id
    assert len(env.DB.incidents) == 1


def test_create_incident_idempotency_conflict(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-conf")
    client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h)
    r = client.post("/api/v1/incidents", json={
        "title": "T2", "severity": "CRITICAL", "service": "svc2", "environment": "staging",
    }, headers=h)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "idempotency_conflict"


def test_create_incident_missing_apikey(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"), "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers={"Idempotency-Key": "ik-x"})
    assert r.status_code == 401


def test_create_incident_invalid_severity(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-sev")
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "INVALID", "service": "svc", "environment": "prod",
    }, headers=h)
    assert r.status_code == 400


# --------------------------------------------------------------------------- get

def test_get_incident(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-get")
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h)
    inc_id = r.json()["incident_id"]
    r2 = client.get(f"/api/v1/incidents/{inc_id}", headers=h)
    assert r2.status_code == 200, r2.text
    inc = r2.json()["incident"]
    assert inc["id"] == inc_id
    assert inc["status"] == "OPEN"
    assert inc["version"] == 1


def test_get_incident_not_found(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env)
    r = client.get("/api/v1/incidents/does-not-exist", headers=h)
    assert r.status_code == 404


def test_get_incident_tenant_isolation(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    # create incident under t1
    client = TestClient(main.app)
    h1 = _headers(env, apikey="sk-test12345678", idem="inc-iso")
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h1)
    inc_id = r.json()["incident_id"]
    # read with tenant t2 key -> not found (isolated)
    h2 = _headers(env, apikey="sk-test22222222", idem="inc-iso-2")
    r2 = client.get(f"/api/v1/incidents/{inc_id}", headers=h2)
    assert r2.status_code == 404


# --------------------------------------------------------------------------- patch / status transition / concurrency

def test_update_incident_status_transition(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-patch")
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h)
    inc_id = r.json()["incident_id"]
    r2 = client.patch(f"/api/v1/incidents/{inc_id}", json={"status": "INVESTIGATING"},
                      headers={**h, "If-Match": "1"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["version"] == 2
    assert env.DB.incidents[inc_id]["status"] == "INVESTIGATING"
    assert any(e["event_type"] == "status_changed" for e in env.DB.incident_events if e["incident_id"] == inc_id)


def test_update_incident_invalid_transition(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-trans")
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h)
    inc_id = r.json()["incident_id"]
    # advance to INVESTIGATING
    client.patch(f"/api/v1/incidents/{inc_id}", json={"status": "INVESTIGATING"},
                 headers={**h, "If-Match": "1"})
    # moving back to OPEN is invalid
    r2 = client.patch(f"/api/v1/incidents/{inc_id}", json={"status": "OPEN"},
                      headers={**h, "If-Match": "2"})
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "invalid_transition"


def test_update_incident_concurrency_stale(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-conc")
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "HIGH", "service": "svc", "environment": "prod",
    }, headers=h)
    inc_id = r.json()["incident_id"]
    # advance version
    client.patch(f"/api/v1/incidents/{inc_id}", json={"status": "INVESTIGATING"},
                 headers={**h, "If-Match": "1"})
    # stale if-match
    r2 = client.patch(f"/api/v1/incidents/{inc_id}", json={"status": "RESOLVED"},
                      headers={**h, "If-Match": "1"})
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "conflict"


# --------------------------------------------------------------------------- events + timeline

def test_add_incident_event_and_timeline(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="inc-ev")
    r = client.post("/api/v1/incidents", json={
        "title": "T", "severity": "CRITICAL", "service": "payment-api", "environment": "prod",
    }, headers=h)
    inc_id = r.json()["incident_id"]
    r2 = client.post(f"/api/v1/incidents/{inc_id}/events", json={
        "event_type": "log_captured",
        "severity": "CRITICAL",
        "service": "payment-api",
        "environment": "prod",
        "timestamp": 1700000000000,
        "logs": "OOMKilled exit 137",
        "deploy_context": "v1.2.3",
    }, headers=h)
    assert r2.status_code == 201, r2.text
    r3 = client.get(f"/api/v1/incidents/{inc_id}/timeline", headers=h)
    assert r3.status_code == 200, r3.text
    tl = r3.json()["events"]
    assert len(tl) >= 2
    types = [e["event_type"] for e in tl]
    assert "created" in types
    assert "log_captured" in types
    # ordering: created before log_captured
    assert types.index("created") < types.index("log_captured")
