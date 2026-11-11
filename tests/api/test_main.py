"""Tests for AI Knowledge Platform FastAPI Worker.

Runs locally without Cloudflare bindings by monkeypatching `main._env`.
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import main  # noqa: E402 (conftest adds api/src to path)


class FakeDB:
    def __init__(self, tenant_hash):
        self.tenant_hash = tenant_hash
        self.documents = {}
        self.audit = []
        self.executed = []
        self.tenants = {}
        self.workspaces = [{"id": "ws1", "name": "Workspace", "is_active": 1,
                            "role": "investigator", "created_at": 1}]

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

    async def first(self):
        sql = self.sql
        p = self._params
        if "api_keys" in sql and "tenants" in sql:
            prefix = p[0]
            for tenant in self.db.tenants.values():
                for ak in tenant.get("api_keys", []):
                    if (ak["key_prefix"] == prefix and ak["is_active"]
                            and tenant["is_active"]
                            and ak["key_hash"] == self.db.tenant_hash):
                        return {"id": tenant["id"], "name": tenant["name"],
                                "key_hash": ak["key_hash"]}
            return None
        if "audit_logs" in sql and "action = 'question'" in sql:
            tenant_id = p[0]
            like = p[1]
            import re as _re
            for a in reversed(self.db.audit):
                if (a["tenant_id"] == tenant_id and a["action"] == "question"
                        and _re.search(like.replace("%", ".*"), a["metadata"])):
                    return (a["id"],)
            return None
        if "idempotency_key" in sql:
            ik, tenant_id = p[0], p[1]
            for doc in self.db.documents.values():
                if doc.get("idempotency_key") == ik and doc["tenant_id"] == tenant_id:
                    return (doc["id"],)
            return None
        if "WHERE id = ?" in sql:
            doc = self.db.documents.get(p[0])
            if doc and doc["tenant_id"] == p[1]:
                return doc
            return None
        return None

    async def all(self):
        if "workspace_members" in self.sql:
            return [("ws1", "Workspace", 1, "investigator", 1)]
        return []

    async def run(self):
        self.db.executed.append((self.sql, self._params))
        if "INSERT INTO documents" in self.sql:
            p = self._params
            self.db.documents[p[0]] = {
                "id": p[0], "tenant_id": p[1], "filename": p[2], "content": p[3],
                "idempotency_key": p[4], "uploaded_at": p[5],
            }
        if "INSERT INTO audit_logs" in self.sql:
            p = self._params
            self.db.audit.append({
                "id": p[0], "tenant_id": p[1], "actor": p[2], "action": p[3],
                "resource": p[4], "metadata": p[5], "created_at": p[6],
            })
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
    def __init__(self, embed_vector=None, llm_response="answer"):
        self.embed_vector = embed_vector or [0.1] * 1024
        self.llm_response = llm_response
        self.calls = []

    async def run(self, model, inputs):
        self.calls.append((model, inputs))
        if "embedding" in model:
            return {"vectors": [self.embed_vector]}
        return {"response": self.llm_response, "usage": {"total_tokens": 42}}


def make_env(tenant_hash):
    db = FakeDB(tenant_hash)
    return SimpleNamespace(
        DB=db,
        VECTORIZE_INDEX=FakeVectorize(),
        ETL_QUEUE=FakeQueue(),
        ETL_DLQ=FakeQueue(),
        ai=FakeAI(),
        ETL_MODE="queue",
    )


def _set_env(monkeypatch, env):
    monkeypatch.setattr(main, "_env", lambda request: env)


def _headers(env, idem="ik-1"):
    return {
        "X-Api-Key": "sk-test12345678",
        "Idempotency-Key": idem,
    }


def test_chunk_text():
    assert main._chunk_text("") == []
    assert main._chunk_text("hello world", max_chars=5) == ["hello", "world"]
    assert main._chunk_text("a b c d e f", max_chars=3) == ["a b", "c d", "e f"]


def test_tenant_from_api_key(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash)
    env.DB.tenants = {
        "t1": {
            "id": "t1", "name": "Tenant One", "is_active": 1,
            "api_keys": [{"key_prefix": "sk-test1", "key_hash": key_hash, "is_active": 1}],
        }
    }
    import asyncio
    assert asyncio.run(main._tenant_from_api_key(env, "sk-test12345678")) is not None
    assert asyncio.run(main._tenant_from_api_key(env, "sk-wrong00000000")) is None
    env.DB.tenants["t1"]["is_active"] = 0
    assert asyncio.run(main._tenant_from_api_key(env, "sk-test12345678")) is None


def test_upload_document_idempotent(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash)
    env.DB.tenants = {
        "t1": {
            "id": "t1", "name": "T", "is_active": 1,
            "api_keys": [{"key_prefix": "sk-test1", "key_hash": key_hash, "is_active": 1}],
        }
    }
    _set_env(monkeypatch, env)
    client = TestClient(main.app)

    files = {"file": ("doc.txt", b"Hello world content for testing.", "text/plain")}
    r = client.post("/api/v1/documents", files=files, headers=_headers(env))
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "uploaded"

    r2 = client.post("/api/v1/documents", files=files, headers=_headers(env))
    assert r2.status_code == 202
    assert r2.json()["status"] == "duplicate"

    r3 = client.post("/api/v1/documents", files=files, headers={"Idempotency-Key": "ik-x"})
    assert r3.status_code == 401  # missing X-Api-Key


def test_upload_missing_apikey(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"))
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    files = {"file": ("doc.txt", b"hi", "text/plain")}
    r = client.post("/api/v1/documents", files=files,
                    headers={"Idempotency-Key": "ik-x"})
    assert r.status_code == 401


def test_health(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"))
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ask_question(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash)
    env.DB.tenants = {
        "t1": {
            "id": "t1", "name": "T", "is_active": 1,
            "api_keys": [{"key_prefix": "sk-test1", "key_hash": key_hash, "is_active": 1}],
        }
    }
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env)
    h["Content-Type"] = "application/json"

    r = client.post("/api/v1/question", json={"question": "What is AI?"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "answer" in body
    assert "citations" in body
    assert body["tokens_used"] == 42

    r2 = client.post("/api/v1/question", json={"question": "What is AI?"}, headers=h)
    assert r2.status_code == 202  # idempotent duplicate

    r3 = client.post("/api/v1/question", json={"question": ""}, headers=h)
    assert r3.status_code == 422
    assert r3.json()["error"]["code"] == "validation_error"
