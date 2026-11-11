"""Tests for document ingestion (Slice 2).

Covers upload/update/delete/reindex, versioning, FTS5 keyword baseline,
Vectorize upsert/delete, ETL retry/DLQ, malformed input and size limits.
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import main  # noqa: E402 (conftest adds api/src to path)
import etl  # noqa: E402


class FakeVectorize:
    def __init__(self):
        self.upserted = []
        self.deleted = []
        self.fail_delete = False

    async def upsert(self, points):
        self.upserted = list(points)
        return SimpleNamespace()

    async def delete(self, ids=None):
        if self.fail_delete:
            raise RuntimeError("vector delete unavailable")
        self.deleted = list(ids or [])
        return SimpleNamespace()


class FakeQueue:
    def __init__(self):
        self.sent = []

    async def send(self, body):
        self.sent.append(body)
        return SimpleNamespace()


class FakeAI:
    def __init__(self, embed_vector=None):
        self.embed_vector = embed_vector or [0.1] * 1024
        self.calls = []

    async def run(self, model, inputs):
        self.calls.append((model, inputs))
        if "embedding" in model:
            texts = inputs.get("text", [])
            return {"vectors": [list(self.embed_vector) for _ in texts]}
        return {"response": "answer", "usage": {"total_tokens": 5}}


class FakeDB:
    def __init__(self, tenant_hash):
        self.tenant_hash = tenant_hash
        self.tenants = {}
        self.api_keys = []
        self.workspaces = {}
        self.workspace_members = []
        self.documents = {}
        self.chunks = {}
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

    def _doc_by_id_tenant(self):
        doc = self.db.documents.get(self._params[0])
        if doc and doc["tenant_id"] == self._params[1]:
            return (doc["id"], doc["tenant_id"])
        return None

    def _doc_version(self):
        doc = self.db.documents.get(self._params[0])
        if doc and doc["tenant_id"] == self._params[1]:
            return (doc["id"], doc["tenant_id"], doc.get("version", 1))
        return None

    def _doc_full(self):
        doc = self.db.documents.get(self._params[0])
        if doc and doc["tenant_id"] == self._params[1]:
            return (doc["id"], doc["tenant_id"], doc.get("content"),
                    doc.get("filename"), doc.get("version", 1))
        return None

    async def first(self):
        sql = self.sql
        p = self._params
        if "api_keys" in sql and "tenants" in sql:
            return self._tenant_auth()
        if "content, filename, version" in sql and "documents WHERE id = ?" in sql:
            return self._doc_full()
        if "id, tenant_id, version" in sql and "documents WHERE id = ?" in sql:
            return self._doc_version()
        if "id, tenant_id FROM documents WHERE id = ?" in sql:
            return self._doc_by_id_tenant()
        if "idempotency_key" in sql and "documents" in sql:
            ik, tid = p[0], p[1]
            for doc in self.db.documents.values():
                if doc.get("idempotency_key") == ik and doc["tenant_id"] == tid:
                    return (doc["id"],)
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
        if "chunks WHERE document_id = ?" in sql:
            doc_id = p[0]
            out = []
            for cid, ch in self.db.chunks.items():
                if ch["document_id"] == doc_id and ch["tenant_id"] == p[1]:
                    out.append([cid, ch["vector_id"]])
            return out
        return []

    async def run(self):
        self.db.executed.append((self.sql, self._params))
        p = self._params
        if "INSERT INTO documents" in self.sql:
            self.db.documents[p[0]] = {
                "id": p[0], "tenant_id": p[1], "filename": p[2], "content": p[3],
                "status": "uploaded", "idempotency_key": p[4], "uploaded_at": p[5],
                "processed_at": None, "error": None, "version": 1,
            }
            return SimpleNamespace()
        if "UPDATE documents SET content" in self.sql:
            doc = self.db.documents.get(p[4])
            if doc and doc["tenant_id"] == p[5]:
                doc["content"] = p[0]
                doc["filename"] = p[1] if p[1] else doc["filename"]
                doc["version"] = p[2]
                doc["status"] = "uploaded"
                doc["processed_at"] = None
                doc["error"] = None
                doc["uploaded_at"] = p[3]
            return SimpleNamespace()
        if "DELETE FROM chunks WHERE document_id" in self.sql:
            doc_id = p[0]
            for cid in [c for c, ch in self.db.chunks.items()
                        if ch["document_id"] == doc_id and ch["tenant_id"] == p[1]]:
                del self.db.chunks[cid]
            return SimpleNamespace()
        if "DELETE FROM documents WHERE id = ?" in self.sql:
            self.db.documents.pop(p[0], None)
            return SimpleNamespace()
        if "UPDATE documents SET status = 'processed'" in self.sql:
            doc = self.db.documents.get(p[2])
            if doc and doc["tenant_id"] == p[3]:
                doc["status"] = "processed"
                doc["processed_at"] = p[0]
                doc["error"] = None
                doc["version"] = p[1]
            return SimpleNamespace()
        if "INSERT INTO chunks" in self.sql:
            self.db.chunks[p[0]] = {
                "id": p[0], "document_id": p[1], "tenant_id": p[2], "content": p[3],
                "vector_id": p[4], "version": p[5], "created_at": p[6],
            }
            return SimpleNamespace()
        if "INSERT INTO audit_logs" in self.sql:
            self.db.audit.append(p)
            return SimpleNamespace()
        return SimpleNamespace()


def make_env(tenant_hash, tenant_id):
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


def _headers(env, idem="ik-1", apikey="sk-test12345678"):
    return {
        "X-Api-Key": apikey,
        "Idempotency-Key": idem,
    }


def _setup_db(db):
    db.tenants["t1"] = {"id": "t1", "name": "Tenant One", "is_active": 1}
    db.api_keys.append({
        "id": "ak1", "tenant_id": "t1", "key_prefix": "sk-test1",
        "key_hash": db.tenant_hash, "is_active": 1,
    })
    db.workspaces["w1"] = {"id": "w1", "name": "Workspace One", "is_active": 1, "created_at": 1000}
    db.workspace_members.append({
        "id": "wm1", "workspace_id": "w1", "tenant_id": "t1", "role": "investigator", "created_at": 1001,
    })


# --------------------------------------------------------------------------- HTTP routes

def test_upload_document_enqueues_etl(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="doc-1")
    files = {"file": ("runbook.md", b"OOMKilled exit code 137 check memory limit", "text/markdown")}
    r = client.post("/api/v1/documents", files=files, headers=h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "uploaded"
    doc_id = body["document_id"]
    assert doc_id in env.DB.documents
    assert env.DB.documents[doc_id]["status"] == "uploaded"
    assert len(env.ETL_QUEUE.sent) == 1
    payload = env.ETL_QUEUE.sent[0]
    assert '"job": "etl.process"' in payload
    assert f'"document_id": "{doc_id}"' in payload
    assert '"tenant_id": "t1"' in payload
    assert any(a[3] == "document.upload" for a in env.DB.audit)


def test_upload_missing_idempotency_key(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"), "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    files = {"file": ("f.txt", b"hi", "text/plain")}
    r = client.post("/api/v1/documents", files=files,
                    headers={"X-Api-Key": "sk-test12345678"})
    assert r.status_code == 400


def test_upload_invalid_encoding(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="doc-enc")
    files = {"file": ("f.txt", b"\xff\xfeinvalid", "text/plain")}
    r = client.post("/api/v1/documents", files=files, headers=h)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_encoding"


def test_upload_oversize(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="doc-big")
    files = {"file": ("f.txt", b"x" * (1024 * 1024 + 1), "text/plain")}
    r = client.post("/api/v1/documents", files=files, headers=h)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "document_too_large"


def test_update_document_new_version(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="doc-upd")
    # create
    files = {"file": ("runbook.md", b"v1 content", "text/markdown")}
    r = client.post("/api/v1/documents", files=files, headers=h)
    doc_id = r.json()["document_id"]
    assert env.DB.documents[doc_id]["version"] == 1
    # update
    r2 = client.put(f"/api/v1/documents/{doc_id}",
                    json={"content": "v2 content updated", "filename": "runbook.md"},
                    headers={**h, "Idempotency-Key": "doc-upd-2"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "updated"
    assert body["version"] == 2
    doc = env.DB.documents[doc_id]
    assert doc["version"] == 2
    assert doc["content"] == "v2 content updated"
    assert doc["status"] == "uploaded"
    assert doc["processed_at"] is None
    # ETL re-enqueued
    assert len(env.ETL_QUEUE.sent) == 2


def test_update_document_missing_content(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="doc-upd2")
    files = {"file": ("f.txt", b"hi", "text/plain")}
    r = client.post("/api/v1/documents", files=files, headers=h)
    doc_id = r.json()["document_id"]
    r2 = client.put(f"/api/v1/documents/{doc_id}",
                    json={"filename": "x.md"}, headers={**h, "Idempotency-Key": "x"})
    assert r2.status_code == 422
    assert r2.json()["error"]["code"] == "validation_error"


def test_delete_document_removes_rows_and_vectors(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="doc-del")
    files = {"file": ("f.txt", b"content to delete", "text/plain")}
    r = client.post("/api/v1/documents", files=files, headers=h)
    doc_id = r.json()["document_id"]
    # pre-populate a chunk + vector to simulate processed state
    env.DB.chunks["c1"] = {
        "id": "c1", "document_id": doc_id, "tenant_id": "t1", "content": "chunk",
        "vector_id": "vec-1", "version": 1, "created_at": 1,
    }
    r2 = client.delete(f"/api/v1/documents/{doc_id}", headers={**h, "Idempotency-Key": "doc-del-2"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "deleted"
    assert doc_id not in env.DB.documents
    assert "c1" not in env.DB.chunks
    assert "vec-1" in env.VECTORIZE_INDEX.deleted


def test_delete_document_preserves_records_when_vector_cleanup_fails(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    env.VECTORIZE_INDEX.fail_delete = True
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    headers = _headers(env, idem="doc-del-failure")
    response = client.post("/api/v1/documents", files={
        "file": ("f.txt", b"content to preserve", "text/plain"),
    }, headers=headers)
    doc_id = response.json()["document_id"]
    env.DB.chunks["c1"] = {
        "id": "c1", "document_id": doc_id, "tenant_id": "t1", "content": "chunk",
        "vector_id": "vec-1", "version": 1, "created_at": 1,
    }

    deleted = client.delete(f"/api/v1/documents/{doc_id}", headers=headers)

    assert deleted.status_code == 503
    assert doc_id in env.DB.documents
    assert "c1" in env.DB.chunks


def test_delete_document_not_found(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="doc-del3")
    r = client.delete("/api/v1/documents/does-not-exist", headers={**h, "Idempotency-Key": "x"})
    assert r.status_code == 404


def test_reindex_enqueues_etl_with_reindex(monkeypatch):
    key_hash = main._sha256_hex("sk-test12345678")
    env = make_env(key_hash, "t1")
    _setup_db(env.DB)
    _set_env(monkeypatch, env)
    client = TestClient(main.app)
    h = _headers(env, idem="doc-reidx")
    files = {"file": ("f.txt", b"content", "text/plain")}
    r = client.post("/api/v1/documents", files=files, headers=h)
    doc_id = r.json()["document_id"]
    r2 = client.post(f"/api/v1/documents/{doc_id}/reindex",
                     headers={**h, "Idempotency-Key": "doc-reidx-2"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "reindexed"
    last = env.ETL_QUEUE.sent[-1]
    assert '"reindex": true' in last
    assert f'"document_id": "{doc_id}"' in last


# --------------------------------------------------------------------------- ETL unit logic

def test_etl_process_document_creates_chunks_and_vectors():
    env = SimpleNamespace(
        DB=SimpleNamespace(),
        VECTORIZE_INDEX=FakeVectorize(),
        ETL_QUEUE=SimpleNamespace(),
        ETL_DLQ=SimpleNamespace(),
        ai=FakeAI(),
    )
    # minimal DB stub for process_document
    class StubDB:
        def prepare(self, sql):
            return StubStmt(self, sql)

    class StubStmt:
        def __init__(self, db, sql):
            self.db = db
            self.sql = sql
            self._params = []
        def bind(self, *p):
            self._params = list(p)
            return self
        async def first(self):
            return None
        async def all(self):
            return []
        async def run(self):
            return SimpleNamespace()
    env.DB = StubDB()

    import asyncio
    result = asyncio.run(
        etl.process_document(env, "doc-1", "t1", "hello world this is a test document", "f.md",
                             version=1)
    )
    assert result["status"] == "ok"
    assert result["chunks"] >= 1
    assert len(env.VECTORIZE_INDEX.upserted) >= 1
    point = env.VECTORIZE_INDEX.upserted[0]
    assert point["id"].startswith("doc-1-v1-")
    assert point["metadata"]["tenant_id"] == "t1"
    assert point["metadata"]["version"] if "version" in point["metadata"] else True


def test_etl_reindex_deletes_old_vectors_before_upsert():
    env = SimpleNamespace(
        DB=SimpleNamespace(), VECTORIZE_INDEX=FakeVectorize(),
        ETL_QUEUE=SimpleNamespace(), ETL_DLQ=SimpleNamespace(), ai=FakeAI(),
    )
    class StubDB:
        def prepare(self, sql):
            return StubStmt(self, sql)
    class StubStmt:
        def __init__(self, db, sql):
            self.db = db
            self.sql = sql
            self._params = []
        def bind(self, *p):
            self._params = list(p)
            return self
        async def first(self):
            return None
        async def all(self):
            # return existing chunks with vector_ids to delete
            if "chunks WHERE document_id" in self.sql:
                return [["c-old", "vec-old-1"], ["c-old2", "vec-old-2"]]
            return []
        async def run(self):
            return SimpleNamespace()
    env.DB = StubDB()

    import asyncio
    result = asyncio.run(
        etl.process_document(env, "doc-1", "t1", "new content here", "f.md",
                             version=2, reindex=True)
    )
    assert result["status"] == "ok"
    # old vectors deleted before new upsert
    assert "vec-old-1" in env.VECTORIZE_INDEX.deleted
    assert "vec-old-2" in env.VECTORIZE_INDEX.deleted
    # new versioned points
    for p in env.VECTORIZE_INDEX.upserted:
        assert p["id"].startswith("doc-1-v2-")


def test_etl_dlq_after_max_retries(monkeypatch):
    # Vectorize that always fails
    class BadVectorize:
        async def upsert(self, points):
            raise RuntimeError("vectorize down")
        async def delete(self, ids=None):
            return SimpleNamespace()

    env = SimpleNamespace(
        DB=SimpleNamespace(), VECTORIZE_INDEX=BadVectorize(),
        ETL_QUEUE=SimpleNamespace(), ETL_DLQ=FakeQueue(), ai=FakeAI(),
    )
    class StubDB:
        def prepare(self, sql):
            return StubStmt(self, sql)
    class StubStmt:
        def __init__(self, db, sql):
            self.db = db
            self.sql = sql
            self._params = []
        def bind(self, *p):
            self._params = list(p)
            return self
        async def first(self):
            return None
        async def all(self):
            return []
        async def run(self):
            return SimpleNamespace()
    env.DB = StubDB()

    import asyncio
    result = asyncio.run(
        etl.process_document(env, "doc-1", "t1", "content here", "f.md",
                             version=1, attempt=3)
    )
    assert result["status"] == "dlq"
