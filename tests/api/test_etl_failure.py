"""ETL failure / recovery tests (P2.3).

Verifies that a document is never marked `processed` when embedding,
Vectorize upsert, or D1 chunk write is incomplete, and that the ETL falls
back to the queue / DLQ instead of silently succeeding. Runs locally without
Cloudflare bindings.
"""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

import etl  # noqa: E402
import main  # noqa: E402 (conftest adds api/src to path)


class FakeVectorize:
    def __init__(self, fail=False):
        self.fail = fail
        self.upserted = []

    async def upsert(self, points):
        if self.fail:
            raise RuntimeError("vectorize unavailable")
        self.upserted = list(points)
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


class FailingQueue(FakeQueue):
    async def send(self, body):
        raise RuntimeError("queue unavailable")


class FakeAI:
    def __init__(self, fail=False):
        self.fail = fail

    async def run(self, model, inputs):
        if self.fail:
            raise RuntimeError("workers ai unavailable")
        texts = inputs.get("text", [])
        return {"vectors": [[0.1] * 1024 for _ in texts]}


class FakeDB:
    def __init__(self, key_hash, fail_chunk_write=None):
        self.key_hash = key_hash
        self.documents = {}
        self.chunks = {}
        self.fail_on_chunk_write = fail_chunk_write
        self.audit = []
        self.workspace_rows = [["w1", "Workspace One", 1, "investigator", 1001]]

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
        if "JOIN api_keys" in sql:
            return {"id": "t1", "name": "Tenant One", "key_hash": self.db.key_hash}
        if "idempotency_key" in sql:
            for doc in self.db.documents.values():
                if doc["idempotency_key"] == p[0] and doc["tenant_id"] == p[1]:
                    return (doc["id"],)
            return None
        if "content, filename, status, version" in sql:
            doc = self.db.documents.get(p[0])
            if doc and doc["tenant_id"] == p[1]:
                return (doc["id"], doc["tenant_id"], doc["content"],
                        doc["filename"], doc["status"], doc["version"])
            return None
        return None

    async def all(self):
        sql = self.sql
        if "workspace_members" in sql:
            return [[self._params[0], "w1", 1, "investigator", 1001]]
        if "chunks WHERE document_id = ?" in sql:
            return [[c["id"], c["vector_id"]] for c in self.db.chunks.values()
                    if c["document_id"] == self._params[0]]
        return []

    async def run(self):
        p = self._params
        sql = self.sql
        if "INSERT INTO documents" in sql:
            self.db.documents[p[0]] = {
                "id": p[0], "tenant_id": p[1], "filename": p[2], "content": p[3],
                "status": "uploaded", "idempotency_key": p[4], "version": 1,
            }
        elif "INSERT INTO chunks" in sql:
            if self.db.fail_on_chunk_write is not None:
                self.db.fail_on_chunk_write -= 1
                if self.db.fail_on_chunk_write == 0:
                    self.db.fail_on_chunk_write = None
                    raise RuntimeError("simulated partial D1 write")
            self.db.chunks[p[0]] = {
                "id": p[0], "document_id": p[1], "tenant_id": p[2],
                "content": p[3], "vector_id": p[4], "version": p[5],
            }
        elif "status = 'processed'" in sql:
            doc = self.db.documents.get(p[2])
            if doc:
                doc["status"] = "processed"
        elif "INSERT INTO audit_logs" in sql:
            self.db.audit.append(p)
        return SimpleNamespace()


def make_env(key_hash, vectorize_fail=False, ai_fail=False, fail_chunk_write=None):
    return SimpleNamespace(
        DB=FakeDB(key_hash, fail_chunk_write=fail_chunk_write),
        VECTORIZE_INDEX=FakeVectorize(fail=vectorize_fail),
        ETL_QUEUE=FakeQueue(),
        ETL_DLQ=FakeQueue(),
        ai=FakeAI(fail=ai_fail),
        ETL_MODE="inline",
    )


def _install(monkeypatch, env):
    monkeypatch.setattr(main, "_env", lambda request: env)


def _upload(client, text="OOMKilled exit code 137 check memory limit"):
    files = {"file": ("runbook.md", text.encode(), "text/markdown")}
    return client.post("/api/v1/documents", files=files,
                       headers={"X-Api-Key": "sk-test12345678",
                                "Idempotency-Key": "etl-doc-1"})


def test_ai_embedding_failure_document_stays_uploaded(monkeypatch):
    """Workers AI embedding down: document must NOT be marked processed."""
    env = make_env(main._sha256_hex("sk-test12345678"), ai_fail=True)
    _install(monkeypatch, env)
    r = _upload(TestClient(main.app))

    assert r.status_code == 202, r.text
    assert r.json()["etl"] == "queued", "inline AI failure -> fall back to queue"
    doc = next(iter(env.DB.documents.values()))
    assert doc["status"] == "uploaded", "document must not be processed when embedding failed"
    assert env.DB.chunks == {}, "no chunks persisted when embedding failed"


def test_vectorize_upsert_failure_document_stays_uploaded(monkeypatch):
    """Vectorize down: document must NOT be marked processed."""
    env = make_env(main._sha256_hex("sk-test12345678"), vectorize_fail=True)
    _install(monkeypatch, env)
    r = _upload(TestClient(main.app))

    assert r.status_code == 202, r.text
    assert r.json()["etl"] == "queued"
    doc = next(iter(env.DB.documents.values()))
    assert doc["status"] == "uploaded"
    assert env.DB.chunks == {}, "no chunks persisted when Vectorize upsert failed"


def test_partial_d1_chunk_write_document_stays_uploaded(monkeypatch):
    """Partial D1 chunk write: document must NOT be marked processed."""
    env = make_env(main._sha256_hex("sk-test12345678"), fail_chunk_write=1)
    _install(monkeypatch, env)
    r = _upload(TestClient(main.app))

    assert r.status_code == 202, r.text
    doc = next(iter(env.DB.documents.values()))
    assert doc["status"] == "uploaded", "partial chunk write must not mark processed"
    # Retry should eventually succeed.
    doc_id = doc["id"]
    retry = asyncio.run(etl.process_document(env, doc_id, "t1", "a" * 500, "runbook.md", attempt=1))
    assert retry["status"] == "ok", "retry after partial write should succeed"


def test_queue_and_dlq_both_unavailable_document_not_processed(monkeypatch):
    """Inline ETL fails AND queue/DLQ unavailable: upload returns 202 but etl=failed."""
    env = make_env(main._sha256_hex("sk-test12345678"), ai_fail=True)
    env.ETL_QUEUE = FailingQueue()
    env.ETL_DLQ = FailingQueue()
    _install(monkeypatch, env)
    r = _upload(TestClient(main.app))

    assert r.status_code == 202, r.text
    assert r.json()["etl"] == "failed", "both queue and DLQ down -> etl=failed"
    doc = next(iter(env.DB.documents.values()))
    assert doc["status"] == "uploaded", "document must not be processed"


def test_reindex_aborts_when_vector_cleanup_fails(monkeypatch):
    """Reindex with failed Vectorize delete: document not reindexed, chunks not replaced."""
    import asyncio

    env = make_env(main._sha256_hex("sk-test12345678"))
    env.VECTORIZE_INDEX.fail = True
    env.DB.documents["d1"] = {
        "id": "d1", "tenant_id": "t1", "filename": "runbook.md",
        "content": "old content", "status": "uploaded", "version": 1,
    }
    env.DB.chunks["old"] = {
        "id": "old", "document_id": "d1", "tenant_id": "t1",
        "content": "old content", "vector_id": "old-vector", "version": 1,
    }

    result = asyncio.run(etl.process_document(
        env, "d1", "t1", "new content", "runbook.md", version=2, reindex=True,
    ))

    assert result["status"] == "retry", "reindex must retry when Vectorize is down"
    assert env.DB.documents["d1"]["status"] == "uploaded", "not marked processed"
    assert env.DB.chunks.get("old") is not None, "old chunks retained until clean reindex"
