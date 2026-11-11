"""Production-hardening tests (Phase 2 BE / Phase 4 Backend).

Covers: health endpoints, binding gate, unified error format (request_id),
pydantic request validation (422), D1-backed AI rate limiting, /api/v2 aliases,
audit_logs coverage via the SqliteD1 adapter, and the ETL retry circuit breaker.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

import etl  # noqa: E402 (conftest adds api/src to path)
import main  # noqa: E402 (conftest adds api/src to path)
from sqlite_d1 import SqliteD1  # noqa: E402

API_KEY = "sk-test12345678"
KEY_HASH = main._sha256_hex(API_KEY)
AUTH = {"X-Api-Key": API_KEY}


# --------------------------------------------------------------------------- env helpers

def _seed_sqlite(db: SqliteD1) -> None:
    """Seed t1 auth + workspace + investigator member for /api/v1/incidents."""
    db.connection.execute(
        "INSERT INTO api_keys (id, tenant_id, key_prefix, key_hash, created_at, last_used_at, is_active) "
        "VALUES ('ak1', 't1', 'sk-test1', ?, 1, NULL, 1)", (KEY_HASH,))
    db.connection.execute("INSERT INTO workspaces (id, name, created_at, is_active) VALUES ('w1','W1',1,1)")
    db.connection.execute(
        "INSERT INTO workspace_members (id, workspace_id, tenant_id, role, created_at) "
        "VALUES ('wm1','w1','t1','investigator',1)")
    db.connection.commit()


def _sqlite_env(mode="inline"):
    return SimpleNamespace(
        DB=SqliteD1(),
        VECTORIZE_INDEX=SimpleNamespace(),
        ETL_QUEUE=SimpleNamespace(send=lambda p: None),
        ETL_DLQ=SimpleNamespace(send=lambda p: None),
        ai=SimpleNamespace(run=lambda *a, **k: None),
        ETL_MODE=mode,
    )


def _seeded_sqlite_env(mode="inline"):
    """SqliteD1 env with t1 auth + workspace seeded; returns (env, db)."""
    env = _sqlite_env(mode)
    _seed_sqlite(env.DB)
    return env, env.DB


def _fake_ai_request(path="/api/v1/question"):
    return SimpleNamespace(state=SimpleNamespace(request_id="test-rid"),
                           url=SimpleNamespace(path=path))


def _set_env(monkeypatch, env):
    monkeypatch.setattr(main, "_env", lambda request: env)


# --------------------------------------------------------------------------- health

def test_health_live_ok(monkeypatch):
    _set_env(monkeypatch, _sqlite_env())
    client = TestClient(main.app)
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "checks" not in r.json()  # liveness does no dependency checks


def test_health_full_env_ok(monkeypatch):
    env = _sqlite_env()
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert all(v == "ok" for v in body["checks"].values()), body["checks"]
    # readiness performs a real D1 round-trip through SqliteD1
    r2 = client.get("/health/ready")
    assert r2.status_code == 200
    assert r2.json()["status"] == "ok"
    assert r2.json()["checks"]["db"] == "ok"


def test_health_missing_env_degraded(monkeypatch):
    _set_env(monkeypatch, None)
    client = TestClient(main.app)
    r = client.get("/health")
    assert r.status_code == 200  # liveness/health never 503 on missing bindings
    body = r.json()
    assert body["status"] == "degraded"
    assert all(v == "missing" for v in body["checks"].values())
    r2 = client.get("/health/ready")
    assert r2.status_code == 503
    assert r2.json()["status"] == "degraded"
    assert r2.json()["checks"]["db"] == "missing"


def test_health_partial_env_ready_degraded(monkeypatch):
    env = _sqlite_env()
    env.ETL_QUEUE = None
    env.ETL_DLQ = None
    env.ai = None
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.get("/health/ready")
    assert r.status_code == 503
    checks = r.json()["checks"]
    assert checks["db"] == "ok"
    assert checks["vectorize"] == "ok"
    assert checks["etl_queue"] == "missing"
    assert checks["etl_dlq"] == "missing"
    assert checks["ai"] == "missing"


def test_health_ready_db_error(monkeypatch):
    class BrokenDB:
        def prepare(self, sql):
            raise RuntimeError("d1 down")

    env = SimpleNamespace(DB=BrokenDB(), VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["db"] == "error"


# --------------------------------------------------------------------------- binding gate

def test_validate_bindings_full_env():
    env = _sqlite_env()
    assert main.validate_bindings(env) == []


def test_validate_bindings_missing_all():
    missing = main.validate_bindings(None)
    assert set(missing) == {"DB", "VECTORIZE_INDEX", "ETL_QUEUE", "ETL_DLQ", "ai"}


def test_validate_bindings_partial():
    env = _sqlite_env()
    env.ETL_QUEUE = None
    assert main.validate_bindings(env) == ["ETL_QUEUE"]


# --------------------------------------------------------------------------- unified errors + request_id

def test_error_body_has_request_id(monkeypatch):
    _set_env(monkeypatch, _seeded_sqlite_env()[0])
    client = TestClient(main.app)
    r = client.get("/api/v1/incidents/does-not-exist", headers=AUTH)
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found"
    assert err["status"] == 404
    assert err["request_id"]
    uuid.UUID(err["request_id"])  # parses


def test_unauthorized_error_body_has_request_id(monkeypatch):
    _set_env(monkeypatch, _sqlite_env())
    client = TestClient(main.app)
    r = client.get("/api/v1/incidents/x")  # no X-Api-Key
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "unauthorized"
    assert err["request_id"]


# --------------------------------------------------------------------------- pydantic validation (422)

def _incident_payload(**over):
    base = {"title": "T", "severity": "HIGH", "service": "svc", "environment": "prod"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


def test_incident_lowercase_severity_422(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents", json=_incident_payload(severity="high"),
                    headers={**AUTH, "Idempotency-Key": "v-low"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"
    assert r.json()["error"]["request_id"]


def test_incident_extra_field_422(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents", json=_incident_payload(hacker="x"),
                    headers={**AUTH, "Idempotency-Key": "v-extra"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


def test_incident_missing_title_422(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents", json={"severity": "HIGH", "service": "svc",
                                               "environment": "prod"},
                    headers={**AUTH, "Idempotency-Key": "v-title"})
    assert r.status_code == 422, r.text


def test_question_too_long_422(monkeypatch):
    _set_env(monkeypatch, _seeded_sqlite_env()[0])
    client = TestClient(main.app)
    r = client.post("/api/v1/question", json={"question": "x" * 1001},
                    headers={**AUTH, "Idempotency-Key": "v-long"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"


def test_validation_error_lists_details(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)

    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents", json={"severity": "WRONG", "service": "svc",
                                               "environment": "prod"},
                    headers={**AUTH, "Idempotency-Key": "v-det"})
    assert r.status_code == 422, r.text
    details = r.json()["error"]["details"]
    assert isinstance(details, list) and len(details) >= 1
    locs = [str(d.get("loc", [])) for d in details]
    assert any("title" in loc for loc in locs)
    assert any("severity" in loc for loc in locs)


# --------------------------------------------------------------------------- AI rate limit (D1-backed)

def test_ai_rate_limit_unit_allow_and_deny():
    db = SqliteD1()
    ok = asyncio.run(main._ai_rate_limit(_fake_ai_request(), SimpleNamespace(DB=db), "t1"))
    assert ok is True
    row = db.connection.execute(
        "SELECT count, window_start FROM rate_limit_buckets WHERE tenant_id='t1' AND bucket_key='ai:daily'"
    ).fetchone()
    assert row["count"] == 1
    # second call within the same window increments
    ok2 = asyncio.run(main._ai_rate_limit(_fake_ai_request(), SimpleNamespace(DB=db), "t1"))
    assert ok2 is True
    row = db.connection.execute(
        "SELECT count FROM rate_limit_buckets WHERE tenant_id='t1' AND bucket_key='ai:daily'"
    ).fetchone()
    assert row["count"] == 2
    # deny at the limit
    db.connection.execute(
        "UPDATE rate_limit_buckets SET count = 100 WHERE tenant_id='t1' AND bucket_key='ai:daily'")
    db.connection.commit()
    ok3 = asyncio.run(main._ai_rate_limit(_fake_ai_request(), SimpleNamespace(DB=db), "t1"))
    assert ok3 is False


def test_ai_rate_limit_fail_open_on_db_error():
    class BrokenDB:
        def prepare(self, sql):
            raise RuntimeError("down")

    ok = asyncio.run(main._ai_rate_limit(_fake_ai_request(), SimpleNamespace(DB=BrokenDB()), "t1"))
    assert ok is True


def test_ai_path_middleware_returns_429(monkeypatch):
    env, db = _seeded_sqlite_env()
    db.connection.execute(
        "INSERT INTO rate_limit_buckets (id, tenant_id, bucket_key, count, window_start) "
        "VALUES ('rl1','t1','ai:daily',100,?)", (main._utc_day_window(main._now_ms()),))
    db.connection.commit()
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    for path in ("/api/v1/question", "/api/v2/question"):
        r = client.post(path, json={"question": "why?"}, headers=AUTH)
        assert r.status_code == 429, (path, r.text)
        err = r.json()["error"]
        assert err["code"] == "ai_quota_exceeded"
        assert err["request_id"]


def test_non_ai_path_skips_rate_limit(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents", json=_incident_payload(),
                    headers={**AUTH, "Idempotency-Key": "rl-none"})
    assert r.status_code == 201, r.text
    rows = db.connection.execute("SELECT count FROM rate_limit_buckets").fetchall()
    assert rows == []  # no bucket written for non-AI paths


# --------------------------------------------------------------------------- /api/v2 aliases

def test_v2_documents_same_shape(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r1 = client.get("/api/v1/documents", headers={**AUTH, "X-Workspace-Id": "w1"})
    r2 = client.get("/api/v2/documents", headers={**AUTH, "X-Workspace-Id": "w1"})
    assert r1.status_code == r2.status_code == 200, (r1.text, r2.text)
    assert list(r1.json().keys()) == list(r2.json().keys())


def test_v2_incident_create_and_idempotent(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = {**AUTH, "Idempotency-Key": "v2-inc"}
    r = client.post("/api/v2/incidents", json=_incident_payload(), headers=h)
    assert r.status_code == 201, r.text
    inc_id = r.json()["incident_id"]
    r2 = client.post("/api/v2/incidents", json=_incident_payload(), headers=h)
    assert r2.status_code == 202
    assert r2.json()["incident_id"] == inc_id
    # v1 and v2 share the same idempotency namespace
    r3 = client.post("/api/v1/incidents", json=_incident_payload(), headers=h)
    assert r3.status_code == 202
    assert r3.json()["incident_id"] == inc_id


def test_v2_validation_and_errors_share_format(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v2/incidents", json=_incident_payload(severity="bogus"),
                    headers={**AUTH, "Idempotency-Key": "v2-bad"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    r2 = client.get("/api/v2/incidents/nope", headers=AUTH)
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "not_found"
    assert r2.json()["error"]["request_id"]


def test_health_endpoints_not_aliased_to_v2():
    v2_paths = {getattr(r, "path", "") for r in main.app.routes
                if str(getattr(r, "path", "")).startswith("/api/v2/")}
    assert not any(p.startswith("/api/v2/health") for p in v2_paths)


# --------------------------------------------------------------------------- audit coverage (SqliteD1)

def test_audit_rows_written_for_incident_lifecycle(monkeypatch):
    db = SqliteD1()
    _seed_sqlite(db)
    env = SimpleNamespace(DB=db, VECTORIZE_INDEX=SimpleNamespace(),
                          ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(),
                          ai=SimpleNamespace(), ETL_MODE="inline")
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = {**AUTH, "Idempotency-Key": "audit-inc"}
    r = client.post("/api/v1/incidents", json=_incident_payload(), headers=h)
    assert r.status_code == 201, r.text
    inc_id = r.json()["incident_id"]
    rows = db.connection.execute(
        "SELECT action, resource FROM audit_logs WHERE tenant_id='t1' ORDER BY created_at"
    ).fetchall()
    actions = [row["action"] for row in rows]
    assert "incident.create" in actions
    create_row = next(row for row in rows if row["action"] == "incident.create")
    assert create_row["resource"] == inc_id

    r2 = client.patch(f"/api/v1/incidents/{inc_id}", json={"status": "INVESTIGATING"},
                      headers={**h, "If-Match": "1"})
    assert r2.status_code == 200, r2.text
    actions = [row["action"] for row in db.connection.execute(
        "SELECT action FROM audit_logs WHERE tenant_id='t1'").fetchall()]
    assert "incident.update" in actions
    assert "incident.status_changed" not in actions  # renamed to incident.update


# --------------------------------------------------------------------------- ETL circuit breaker

class _CircuitQueue:
    def __init__(self):
        self.sent = []

    async def send(self, body):
        self.sent.append(body)
        return SimpleNamespace()


class _CircuitMessage:
    def __init__(self, body):
        self.body = body
        self.acked = False
        self.retried = False

    def ack(self):
        self.acked = True

    def retry(self):
        self.retried = True


def _circuit_env():
    class _CircuitVectorize:
        def __init__(self):
            self.upserted = []

        async def upsert(self, points):
            self.upserted.extend(points)
            return SimpleNamespace()

        async def delete(self, ids=None):
            return SimpleNamespace()

    env = _sqlite_env()
    env.VECTORIZE_INDEX = _CircuitVectorize()
    env.ETL_QUEUE = _CircuitQueue()
    env.ETL_DLQ = _CircuitQueue()
    return env


def _seed_document(db: SqliteD1, doc_id="doc1", tenant="t1", status="uploaded"):
    db.connection.execute(
        "INSERT INTO documents (id, tenant_id, filename, content, status, uploaded_at) "
        "VALUES (?, ?, 'f.txt', 'hello world', ?, 1)", (doc_id, tenant, status))
    db.connection.commit()


def _trip_circuit(db: SqliteD1, key="etl:t1", failures=etl.CB_THRESHOLD):
    env = SimpleNamespace(DB=db)
    for _ in range(failures):
        asyncio.run(etl._circuit_record_failure(env, key))


def test_circuit_closed_then_open_after_5_failures():
    env = _circuit_env()

    def check():
        return asyncio.run(etl._circuit_check(env, "etl:t1"))

    assert check() == "closed"
    for _ in range(etl.CB_THRESHOLD - 1):
        asyncio.run(etl._circuit_record_failure(env, "etl:t1"))
        assert check() == "closed"
    asyncio.run(etl._circuit_record_failure(env, "etl:t1"))
    assert check() == "open"


def test_circuit_half_open_after_cooldown():
    env = _circuit_env()
    db = env.DB
    _trip_circuit(db)
    assert asyncio.run(etl._circuit_check(env, "etl:t1")) == "open"
    # Rewind opened_at past the cooldown -> half open (one probe allowed).
    db.connection.execute(
        "UPDATE etl_circuit_state SET opened_at = ? WHERE key = 'etl:t1'",
        (etl._now_ms() - etl.CB_COOLDOWN_MS - 1,))
    db.connection.commit()
    assert asyncio.run(etl._circuit_check(env, "etl:t1")) == "half_open"


def test_circuit_success_resets():
    env = _circuit_env()
    _trip_circuit(env.DB)
    assert asyncio.run(etl._circuit_check(env, "etl:t1")) == "open"
    asyncio.run(etl._circuit_record_success(env, "etl:t1"))
    assert asyncio.run(etl._circuit_check(env, "etl:t1")) == "closed"
    row = env.DB.connection.execute(
        "SELECT * FROM etl_circuit_state WHERE key = 'etl:t1'").fetchone()
    assert row is None


def test_circuit_check_fails_open_on_db_error():
    class BrokenDB:
        def prepare(self, sql):
            raise RuntimeError("d1 down")

    env = SimpleNamespace(DB=BrokenDB())
    assert asyncio.run(etl._circuit_check(env, "etl:t1")) == "closed"


def test_circuit_open_message_dlqd_not_retried():
    env = _circuit_env()
    db = env.DB
    _seed_document(db)
    _trip_circuit(db)
    msg = _CircuitMessage({"job": "etl.process", "document_id": "doc1",
                           "tenant_id": "t1", "attempt": 0, "version": 1})
    asyncio.run(etl.handle_queue_message(env, msg))
    assert msg.acked is True
    assert msg.retried is False
    assert len(env.ETL_DLQ.sent) == 1
    assert len(env.ETL_QUEUE.sent) == 0
    payload = json.loads(env.ETL_DLQ.sent[0])
    assert payload["reason"] == "circuit_open"
    assert payload["document_id"] == "doc1"
    assert payload["tenant_id"] == "t1"
    # document marked failed with the breaker reason
    row = db.connection.execute(
        "SELECT status, error FROM documents WHERE id = 'doc1'").fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "circuit_open"


def test_circuit_half_open_probe_failure_reopens_with_fresh_cooldown():
    env = _circuit_env()
    db = env.DB
    _trip_circuit(db)
    # Enter half-open by rewinding opened_at.
    db.connection.execute(
        "UPDATE etl_circuit_state SET opened_at = ? WHERE key = 'etl:t1'",
        (etl._now_ms() - etl.CB_COOLDOWN_MS - 1,))
    db.connection.commit()
    _seed_document(db)
    # Embedding fails -> retry path -> records a fresh failure.
    env.ai = SimpleNamespace(run=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ai down")))
    msg = _CircuitMessage({"job": "etl.process", "document_id": "doc1",
                           "tenant_id": "t1", "attempt": 0, "version": 1})
    asyncio.run(etl.handle_queue_message(env, msg))
    # Probe failed -> circuit re-opened with a fresh cooldown.
    state = asyncio.run(etl._circuit_check(env, "etl:t1"))
    assert state == "open"
    row = db.connection.execute(
        "SELECT consecutive_failures, opened_at FROM etl_circuit_state WHERE key = 'etl:t1'"
    ).fetchone()
    assert row["consecutive_failures"] == etl.CB_THRESHOLD + 1
    assert row["opened_at"] >= etl._now_ms() - 2000


def test_circuit_half_open_probe_success_closes():
    env = _circuit_env()
    db = env.DB
    _trip_circuit(db)
    db.connection.execute(
        "UPDATE etl_circuit_state SET opened_at = ? WHERE key = 'etl:t1'",
        (etl._now_ms() - etl.CB_COOLDOWN_MS - 1,))
    db.connection.commit()
    _seed_document(db)

    async def _ok_ai(model, inputs):
        return {"vectors": [[0.1] * 1024 for _ in inputs.get("text", [])]}

    env.ai = SimpleNamespace(run=_ok_ai)
    msg = _CircuitMessage({"job": "etl.process", "document_id": "doc1",
                           "tenant_id": "t1", "attempt": 0, "version": 1})
    asyncio.run(etl.handle_queue_message(env, msg))
    assert msg.acked is True
    assert asyncio.run(etl._circuit_check(env, "etl:t1")) == "closed"
    row = db.connection.execute(
        "SELECT status FROM documents WHERE id = 'doc1'").fetchone()
    assert row["status"] == "processed"


# --------------------------------------------------------------------------- Phase 6: AI/RAG (strict prompts, token quota, AI-unavailable fallback)

def _stub_ai(llm_response=None, llm_error=None, tokens=25):
    """Fake env.ai: embeddings always succeed; LLM returns llm_response or raises llm_error."""
    calls = {"llm": 0}

    async def run(model, inputs):
        if "qwen3-embedding" in model:
            return {"vectors": [[0.1] * 1024]}
        calls["llm"] += 1
        if llm_error is not None:
            raise llm_error
        if llm_response is not None:
            return llm_response
        return {"response": "ok", "usage": {"total_tokens": tokens}}

    ns = SimpleNamespace(run=run)
    ns.calls = calls
    return ns


def _vectorize(matches):
    async def query(**kwargs):
        return {"matches": matches}
    return SimpleNamespace(query=query)


def _seed_doc(db, doc_id, content, tenant_id="t1"):
    db.connection.execute(
        "INSERT INTO documents (id, tenant_id, filename, content, status, idempotency_key, "
        "uploaded_at, processed_at, error, version) VALUES (?, ?, ?, ?, 'processed', ?, 1, 1, NULL, 1)",
        (doc_id, tenant_id, doc_id + ".md", content, "ik-" + doc_id))
    db.connection.commit()


_DOC_CONTENT = "OOMKilled api prod runbook: check pod memory limits and previous logs."
_MATCH = {"id": "vec-doc1", "score": 0.9,
          "metadata": {"document_id": "doc1", "tenant_id": "t1", "chunk_id": "doc1-v1-0",
                       "content": _DOC_CONTENT, "version": 1}}


def test_prompts_strict_contract():
    """TRIAGE_SYSTEM_PROMPT must stay strict/read-only; slice5 asserts the
    'triage assistant' substring and tests below assert the JSON contract."""
    p = main.TRIAGE_SYSTEM_PROMPT.lower()
    assert "triage assistant" in p
    assert "strict json" in p
    assert "read-only" in p
    assert "[n]" in main.TRIAGE_SYSTEM_PROMPT.lower()
    q = main.QUESTION_SYSTEM_PROMPT.lower()
    assert "cite" in q and "abstain" in q


def test_triage_parses_strict_json_and_normalizes_hypotheses(monkeypatch):
    env, db = _seeded_sqlite_env()
    _seed_doc(db, "doc1", _DOC_CONTENT)
    env.ai = _stub_ai(llm_response={
        "response": '```json\n{"summary": "Memory limit hit [1]", '
                    '"hypotheses": [{"text": "Pod OOMKilled", "confirmed": true, '
                    '"evidence": [1]}], "read_only_checks": ["kubectl top pod api"]}\n```',
        "usage": {"total_tokens": 30}})
    env.VECTORIZE_INDEX = _vectorize([_MATCH])
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents",
                    json={"title": "OOMKilled api", "severity": "HIGH",
                          "service": "api", "environment": "prod"},
                    headers={**AUTH, "Idempotency-Key": "idem-p6-json-create"})
    assert r.status_code == 201, r.text
    inc_id = r.json()["incident_id"]
    r2 = client.post(f"/api/v1/incidents/{inc_id}/triage",
                     headers={**AUTH, "Idempotency-Key": "idem-p6-json"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "ok"
    assert body["summary"] == "Memory limit hit [1]"
    # API contract: hypotheses keep only {text, confirmed}; model's per-item
    # "evidence" key is dropped.
    assert body["hypotheses"] == [{"text": "Pod OOMKilled", "confirmed": True}]
    # Model read_only_checks override the computed defaults.
    assert body["read_only_checks"] == ["kubectl top pod api"]
    assert body["tokens_used"] == 30
    assert body.get("ai") != "unavailable"


def test_triage_ai_unavailable_uses_extractive_fallback(monkeypatch):
    env, db = _seeded_sqlite_env()
    _seed_doc(db, "doc1", _DOC_CONTENT)
    env.ai = _stub_ai(llm_error=RuntimeError("gateway down"))
    env.VECTORIZE_INDEX = _vectorize([_MATCH])
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents",
                    json={"title": "OOMKilled api", "severity": "HIGH",
                          "service": "api", "environment": "prod"},
                    headers={**AUTH, "Idempotency-Key": "idem-p6-fb-create"})
    inc_id = r.json()["incident_id"]
    r2 = client.post(f"/api/v1/incidents/{inc_id}/triage",
                     headers={**AUTH, "Idempotency-Key": "idem-p6-fb"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "ok"
    assert body["ai"] == "unavailable"
    assert body["hypotheses"] == []
    assert body["summary"].startswith("(fallback khong LLM)")
    assert "[1]" in body["summary"]
    # Retry once before degrading: 2 LLM calls total.
    assert env.ai.calls["llm"] == 2


def test_question_ai_unavailable_uses_extractive_fallback(monkeypatch):
    env, db = _seeded_sqlite_env()
    _seed_doc(db, "doc1", _DOC_CONTENT)
    env.ai = _stub_ai(llm_error=RuntimeError("gateway down"))
    env.VECTORIZE_INDEX = _vectorize([_MATCH])
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/question", json={"question": "OOMKilled api prod"},
                    headers={**AUTH, "Idempotency-Key": "idem-p6-qfb"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai"] == "unavailable"
    assert body["answer"].startswith("(fallback without LLM)")
    assert "[1]" in body["answer"]
    assert body["citations"][0]["document_id"] == "doc1"
    assert body["tokens_used"] == 0
    # Unavailable runs do not accumulate tokens.
    row = db.connection.execute(
        "SELECT count FROM rate_limit_buckets WHERE tenant_id = 't1' AND bucket_key = 'tokens:daily'"
    ).fetchone()
    assert row is None


def test_question_accumulates_tokens_in_daily_bucket(monkeypatch):
    env, db = _seeded_sqlite_env()
    _seed_doc(db, "doc1", _DOC_CONTENT)
    env.ai = _stub_ai(tokens=25)
    env.VECTORIZE_INDEX = _vectorize([_MATCH])
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/question", json={"question": "OOMKilled api prod"},
                    headers={**AUTH, "Idempotency-Key": "idem-p6-tok"})
    assert r.status_code == 200, r.text
    row = db.connection.execute(
        "SELECT count, window_start FROM rate_limit_buckets WHERE tenant_id = 't1' "
        "AND bucket_key = 'tokens:daily'").fetchone()
    assert row is not None
    assert row["count"] == 25
    assert row["window_start"] == main._utc_day_window(main._now_ms())


def test_token_quota_blocks_ai_paths_with_429(monkeypatch):
    env, db = _seeded_sqlite_env()
    env.ai = _stub_ai(tokens=25)
    env.VECTORIZE_INDEX = _vectorize([])
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.post("/api/v1/incidents",
                    json={"title": "OOMKilled api", "severity": "HIGH",
                          "service": "api", "environment": "prod"},
                    headers={**AUTH, "Idempotency-Key": "idem-p6-429-create"})
    assert r.status_code == 201, r.text
    inc_id = r.json()["incident_id"]
    # Exhaust today's token quota for t1.
    db.connection.execute(
        "INSERT INTO rate_limit_buckets (id, tenant_id, bucket_key, count, window_start) "
        "VALUES ('bq1', 't1', 'tokens:daily', ?, ?)",
        (main.TOKEN_DAILY_LIMIT, main._utc_day_window(main._now_ms())))
    db.connection.commit()
    r2 = client.post(f"/api/v1/incidents/{inc_id}/triage",
                     headers={**AUTH, "Idempotency-Key": "idem-p6-429"})
    assert r2.status_code == 429, r2.text
    body = r2.json()
    assert body["error"]["code"] == "token_quota_exceeded"
    assert int(r2.headers["Retry-After"]) >= 1
    r3 = client.post("/api/v1/question", json={"question": "OOMKilled api prod"},
                     headers={**AUTH, "Idempotency-Key": "idem-p6-429q"})
    assert r3.status_code == 429
    assert r3.json()["error"]["code"] == "token_quota_exceeded"


def test_metrics_quota_reports_tokens_daily(monkeypatch):
    env, db = _seeded_sqlite_env()
    env.ai = _stub_ai()
    _set_env(monkeypatch, env)
    db.connection.execute(
        "INSERT INTO rate_limit_buckets (id, tenant_id, bucket_key, count, window_start) "
        "VALUES ('bq2', 't1', 'tokens:daily', 1234, ?)",
        (main._utc_day_window(main._now_ms()),))
    db.connection.commit()
    client = TestClient(main.app)
    r = client.get("/api/v1/metrics/quota", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tokens_daily"] == 1234
    assert body["daily_token_limit"] == main.TOKEN_DAILY_LIMIT
    assert any(b["bucket_key"] == "tokens:daily" for b in body["buckets"])
