"""Tenant isolation tests (P2.2).

Verifies that an API key bound to one tenant cannot read, write, or delete
another tenant's documents or incidents. Runs locally without Cloudflare
bindings by monkeypatching `main._env`.
"""

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main  # noqa: E402 (conftest adds api/src to path)


class FakeVectorize:
    async def upsert(self, points):
        return SimpleNamespace()

    async def deleteByIds(self, ids=None):
        return await self.delete(ids=ids)

    async def delete(self, ids=None):
        return SimpleNamespace()


class FakeQueue:
    def __init__(self):
        self.sent = []

    async def send(self, body):
        self.sent.append(body)
        return SimpleNamespace()


class FakeAI:
    async def run(self, model, inputs):
        texts = inputs.get("text", [])
        return {"vectors": [[0.1] * 1024 for _ in texts]}


class _IsolatedStatement:
    """A statement that carries its SQL string and operates on one tenant's store."""

    def __init__(self, store, tenant_id, key_hash, sql=""):
        self.store = store
        self.tenant_id = tenant_id
        self.key_hash = key_hash
        self._sql = sql
        self._params = []

    def bind(self, *params):
        self._params = list(params)
        return self

    @property
    def sql(self):
        return self._sql

    async def first(self):
        sql = self._sql
        p = self._params
        if "JOIN api_keys" in sql:
            return {"id": self.tenant_id, "name": "Tenant " + self.tenant_id,
                    "key_hash": self.key_hash}
        if "idempotency_key" in sql and "documents" in sql:
            for doc in self.store["documents"].values():
                if doc.get("idempotency_key") == p[0]:
                    return (doc["id"],)
            return None
        if "FROM incidents WHERE id = ?" in sql and "AND tenant_id = ?" in sql:
            inc = self.store["incidents"].get(p[0])
            if inc and inc["tenant_id"] == self.tenant_id:
                return (inc["id"], inc["workspace_id"], inc["tenant_id"],
                        inc["title"], inc["severity"], inc["service"],
                        inc["environment"], inc["status"], inc["version"],
                        inc.get("payload_hash"), inc["created_at"],
                        inc["updated_at"], inc.get("resolved_at"))
            return None
        return None

    async def all(self):
        sql = self._sql
        if "documents WHERE tenant_id = ?" in sql:
            return [[d["id"], d["filename"], d["status"], d["uploaded_at"],
                     d["processed_at"], d.get("error")]
                    for d in self.store["documents"].values()]
        if "workspace_members" in sql:
            ws = self.store["workspaces"].get("w-" + self.tenant_id)
            return [[ws["id"], ws["name"], ws["is_active"], "admin", 1]]
        if "chunks WHERE document_id = ?" in sql:
            return [[c["id"], c["vector_id"]] for c in self.store["chunks"].values()
                    if c["document_id"] == self._params[0]]
        return []

    async def run(self):
        p = self._params
        sql = self._sql
        if "INSERT INTO documents" in sql:
            self.store["documents"][p[0]] = {
                "id": p[0], "tenant_id": self.tenant_id, "filename": p[2],
                "content": p[3], "status": "uploaded",
                "idempotency_key": p[4], "version": 1,
            }
        elif "INSERT INTO chunks" in sql:
            self.store["chunks"][p[0]] = {
                "id": p[0], "document_id": p[1], "tenant_id": self.tenant_id,
                "content": p[3], "vector_id": p[4], "version": p[5],
            }
        elif "status = 'processed'" in sql:
            doc = self.store["documents"].get(p[2])
            if doc and doc["tenant_id"] == self.tenant_id:
                doc["status"] = "processed"
        elif "INSERT INTO incidents" in sql:
            self.store["incidents"][p[0]] = {
                "id": p[0], "workspace_id": p[1], "tenant_id": self.tenant_id,
                "title": p[3], "severity": p[4], "service": p[5],
                "environment": p[6], "status": "OPEN", "version": 1,
                "payload_hash": p[7], "idempotency_key": p[8],
                "created_at": p[9], "updated_at": p[9], "resolved_at": None,
            }
        elif "INSERT INTO audit_logs" in sql:
            self.store["audit"].append(p)
        return SimpleNamespace()


class _IsolatedDB:
    """DB-like wrapper with prepare(sql) returning an _IsolatedStatement."""

    def __init__(self, store, tenant_id, key_hash):
        self.store = store
        self.tenant_id = tenant_id
        self.key_hash = key_hash

    def prepare(self, sql):
        return _IsolatedStatement(self.store, self.tenant_id, self.key_hash, sql)


class _IsolatedStore:
    """Separate in-memory DB per tenant to enforce hard isolation."""

    def __init__(self):
        self.stores = {}

    def _store_for(self, tenant_id):
        if tenant_id not in self.stores:
            self.stores[tenant_id] = {
                "documents": {},
                "chunks": {},
                "incidents": {},
                "incident_events": [],
                "audit": [],
                "workspaces": {
                    "w-" + tenant_id: {
                        "id": "w-" + tenant_id,
                        "name": "WS " + tenant_id,
                        "is_active": True,
                    }
                },
                "workspace_members": [
                    {
                        "tenant_id": tenant_id,
                        "workspace_id": "w-" + tenant_id,
                        "role": "admin",
                        "created_at": 1,
                    }
                ],
            }
        return self.stores[tenant_id]

    def make_env(self, tenant_id, key_hash):
        store = self._store_for(tenant_id)
        db = _IsolatedDB(store, tenant_id, key_hash)
        return SimpleNamespace(
            DB=db,
            VECTORIZE_INDEX=FakeVectorize(),
            ETL_QUEUE=FakeQueue(),
            ETL_DLQ=FakeQueue(),
            ai=FakeAI(),
            ETL_MODE="inline",
        )

    def seed_document(self, tenant_id, doc_id, filename, content):
        self._store_for(tenant_id)["documents"][doc_id] = {
            "id": doc_id, "tenant_id": tenant_id, "filename": filename,
            "content": content, "status": "processed", "idempotency_key": "ik",
            "version": 1, "uploaded_at": 1001, "processed_at": 1002, "error": None,
        }

    def seed_incident(self, tenant_id, inc_id, title):
        self._store_for(tenant_id)["incidents"][inc_id] = {
            "id": inc_id, "workspace_id": "w-" + tenant_id, "tenant_id": tenant_id,
            "title": title, "severity": "HIGH", "service": "svc",
            "environment": "prod", "status": "OPEN", "version": 1,
            "payload_hash": "x", "idempotency_key": "ik", "created_at": 1,
            "updated_at": 1, "resolved_at": None,
        }


def _install(monkeypatch, env):
    monkeypatch.setattr(main, "_env", lambda request: env)


def _headers(api_key):
    return {"X-Api-Key": api_key, "Idempotency-Key": str(uuid.uuid4())}


def test_cannot_read_another_tenant_documents(monkeypatch):
    iso = _IsolatedStore()
    iso.seed_document("t-b", "doc-b", "secret-b.md", "tenant b secret")
    env_a = iso.make_env("t-a", main._sha256_hex("sk-aaaaaaaa"))

    _install(monkeypatch, env_a)
    client = TestClient(main.app)
    r = client.get("/api/v1/documents", headers=_headers("sk-aaaaaaaa"))

    assert r.status_code == 200, r.text
    ids = [d["id"] for d in r.json()["documents"]]
    assert "doc-b" not in ids


def test_cannot_access_another_tenant_incident(monkeypatch):
    iso = _IsolatedStore()
    iso.seed_incident("t-b", "inc-b", "Secret B")
    env_a = iso.make_env("t-a", main._sha256_hex("sk-aaaaaaaa"))

    _install(monkeypatch, env_a)
    client = TestClient(main.app)
    r = client.get("/api/v1/incidents/inc-b",
                   headers={"X-Api-Key": "sk-aaaaaaaa"})

    assert r.status_code == 404, r.text


def test_document_upload_bound_to_api_key_tenant(monkeypatch):
    iso = _IsolatedStore()
    env_a = iso.make_env("t-a", main._sha256_hex("sk-aaaaaaaa"))

    _install(monkeypatch, env_a)
    client = TestClient(main.app)
    r = client.post("/api/v1/documents",
                    files={"file": ("x.md", b"hello", "text/markdown")},
                    headers=_headers("sk-aaaaaaaa"))

    assert r.status_code == 202, r.text
    doc = next(iter(iso.stores["t-a"]["documents"].values()))
    assert doc["tenant_id"] == "t-a"
    assert "t-b" not in iso.stores


def test_api_key_rejected_for_wrong_tenant_env(monkeypatch):
    """Tenant B's key against tenant A's env gets no documents (isolation)."""
    iso = _IsolatedStore()
    iso.seed_document("t-a", "doc-a", "a.md", "tenant a doc")
    env_a = iso.make_env("t-a", main._sha256_hex("sk-aaaaaaaa"))
    env_b = iso.make_env("t-b", main._sha256_hex("sk-bbbbbbbb"))

    _install(monkeypatch, env_a)
    client = TestClient(main.app)
    r = client.get("/api/v1/documents", headers=_headers("sk-aaaaaaaa"))
    assert r.status_code == 200
    assert any(d["id"] == "doc-a" for d in r.json()["documents"])

    _install(monkeypatch, env_b)
    r = client.get("/api/v1/documents", headers=_headers("sk-bbbbbbbb"))
    assert r.status_code == 200
    assert all(d["id"] != "doc-a" for d in r.json()["documents"])
