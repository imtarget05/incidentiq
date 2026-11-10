"""ETL execution modes: inline processing (default) and queue consumer.

Covers the two paths added in Slice 6:
  * inline: uploads are chunked/embedded/upserted during the request, no consumer needed
  * queue: ETL_MODE=queue enqueues, and api/src/etl_consumer.py drains `etl-queue`
  * inline failures fall back to the queue instead of failing the upload
"""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

import etl  # noqa: E402
import main  # noqa: E402


class FakeVectorize:
    def __init__(self, fail=False, fail_delete=False):
        self.fail = fail
        self.fail_delete = fail_delete
        self.upserted = []

    async def upsert(self, points):
        if self.fail:
            raise RuntimeError("vectorize unavailable")
        self.upserted = list(points)
        return SimpleNamespace()

    async def delete(self, ids=None):
        if self.fail_delete:
            raise RuntimeError("vectorize delete unavailable")
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
    def __init__(self):
        self.calls = []

    async def run(self, model, inputs):
        self.calls.append((model, inputs))
        texts = inputs.get("text", [])
        return {"vectors": [[0.1] * 1024 for _ in texts]}


class FakeMessage:
    def __init__(self, body):
        self.body = body
        self.acked = False
        self.retried = False

    def ack(self):
        self.acked = True

    def retry(self):
        self.retried = True


class FakeDB:
    def __init__(self, key_hash):
        self.key_hash = key_hash
        self.documents = {}
        self.chunks = {}
        self.audit = []
        self.fail_on_chunk_write = None
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

    async def all(self):
        if "workspace_members" in self.sql:
            return self.db.workspace_rows
        if "chunks WHERE document_id = ?" in self.sql:
            return [[c["id"], c["vector_id"]] for c in self.db.chunks.values()
                    if c["document_id"] == self._params[0]]
        return []

    async def run(self):
        p = self._params
        if "INSERT INTO documents" in self.sql:
            self.db.documents[p[0]] = {
                "id": p[0], "tenant_id": p[1], "filename": p[2], "content": p[3],
                "status": "uploaded", "idempotency_key": p[4], "version": 1,
            }
        elif "INSERT INTO chunks" in self.sql:
            if self.db.fail_on_chunk_write is not None:
                self.db.fail_on_chunk_write -= 1
                if self.db.fail_on_chunk_write == 0:
                    self.db.fail_on_chunk_write = None
                    raise RuntimeError("simulated partial D1 write")
            self.db.chunks[p[0]] = {
                "id": p[0], "document_id": p[1], "tenant_id": p[2],
                "content": p[3], "vector_id": p[4], "version": p[5],
            }
        elif "status = 'processed'" in self.sql:
            doc = self.db.documents.get(p[2])
            if doc:
                doc["status"] = "processed"
                doc["version"] = p[1]
        elif "status = 'failed'" in self.sql:
            doc = self.db.documents.get(p[1])
            if doc:
                doc["status"] = "failed"
                doc["error"] = p[0]
        elif "INSERT INTO audit_logs" in self.sql:
            self.db.audit.append(p)
        return SimpleNamespace()


def make_env(key_hash, mode="inline", vectorize_fail=False):
    return SimpleNamespace(
        DB=FakeDB(key_hash),
        VECTORIZE_INDEX=FakeVectorize(fail=vectorize_fail),
        ETL_QUEUE=FakeQueue(),
        ETL_DLQ=FakeQueue(),
        ai=FakeAI(),
        ETL_MODE=mode,
    )


def _install(monkeypatch, env):
    monkeypatch.setattr(main, "_env", lambda request: env)


def _upload(client, text="OOMKilled exit code 137 check memory limit"):
    files = {"file": ("runbook.md", text.encode(), "text/markdown")}
    return client.post("/api/v1/documents", files=files,
                       headers={"X-Api-Key": "sk-test12345678",
                                "Idempotency-Key": "etl-doc-1"})


def test_inline_mode_processes_document_without_queue(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"), mode="inline")
    _install(monkeypatch, env)
    r = _upload(TestClient(main.app))

    assert r.status_code == 202, r.text
    assert r.json()["etl"] == "ok"
    doc = next(iter(env.DB.documents.values()))
    assert doc["status"] == "processed"
    assert len(env.DB.chunks) == 1
    assert len(env.VECTORIZE_INDEX.upserted) == 1
    assert env.ETL_QUEUE.sent == []


def test_document_upload_requires_investigator_workspace_membership(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"), mode="inline")
    env.DB.workspace_rows = []
    _install(monkeypatch, env)
    response = _upload(TestClient(main.app))

    assert response.status_code == 403
    assert response.json()["detail"] == "no workspace assigned to tenant"


def test_queue_mode_enqueues_without_processing(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"), mode="queue")
    _install(monkeypatch, env)
    r = _upload(TestClient(main.app))

    assert r.status_code == 202, r.text
    assert r.json()["etl"] == "queued"
    doc = next(iter(env.DB.documents.values()))
    assert doc["status"] == "uploaded"
    assert env.DB.chunks == {}
    assert len(env.ETL_QUEUE.sent) == 1


def test_inline_failure_falls_back_to_queue(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"), mode="inline",
                   vectorize_fail=True)
    _install(monkeypatch, env)
    r = _upload(TestClient(main.app))

    assert r.status_code == 202, r.text
    assert r.json()["etl"] == "queued"
    assert len(env.ETL_QUEUE.sent) == 1
    assert "etl.process" in env.ETL_QUEUE.sent[0]


def test_consumer_acks_and_processes():
    env = make_env(main._sha256_hex("sk-test12345678"), mode="queue")
    env.DB.documents["d1"] = {
        "id": "d1", "tenant_id": "t1", "filename": "runbook.md",
        "content": "OOMKilled exit code 137", "status": "uploaded",
        "idempotency_key": "ik", "version": 1,
    }
    message = FakeMessage({"job": "etl.process", "document_id": "d1",
                           "tenant_id": "t1", "version": 1})
    asyncio.run(etl.handle_queue_message(env, message))

    assert message.acked is True
    assert message.retried is False
    assert env.DB.documents["d1"]["status"] == "processed"
    assert len(env.DB.chunks) == 1


def test_embedding_failure_never_marks_document_processed(monkeypatch):
    env = make_env(main._sha256_hex("sk-test12345678"), mode="inline")
    env.DB.documents["d1"] = {
        "id": "d1", "tenant_id": "t1", "filename": "runbook.md",
        "content": "a valid runbook chunk", "status": "uploaded", "version": 2,
    }

    async def failed_embedding(_env, texts):
        return [None for _ in texts]

    monkeypatch.setattr(etl, "embed_texts", failed_embedding)
    result = asyncio.run(etl.process_document(
        env, "d1", "t1", "a valid runbook chunk", "runbook.md", version=2,
    ))

    assert result["status"] == "retry"
    assert env.DB.documents["d1"]["status"] == "uploaded"
    assert env.VECTORIZE_INDEX.upserted == []


def test_reindex_does_not_upsert_when_old_vector_cleanup_fails():
    env = make_env(main._sha256_hex("sk-test12345678"), mode="inline")
    env.VECTORIZE_INDEX.fail_delete = True
    env.DB.chunks["old"] = {
        "id": "old", "document_id": "d1", "tenant_id": "t1",
        "content": "old version", "vector_id": "old-vector", "version": 1,
    }

    result = asyncio.run(etl.process_document(
        env, "d1", "t1", "new content", "runbook.md", version=2, reindex=True,
    ))

    assert result["status"] == "retry"
    assert env.VECTORIZE_INDEX.upserted == []


def test_partial_chunk_write_retry_does_not_duplicate_saved_chunks():
    env = make_env(main._sha256_hex("sk-test12345678"), mode="inline")
    env.DB.documents["d1"] = {
        "id": "d1", "tenant_id": "t1", "filename": "runbook.md",
        "content": "", "status": "uploaded", "version": 1,
    }
    content = "a" * 799 + " " + "b" * 799
    env.DB.fail_on_chunk_write = 2

    first = asyncio.run(etl.process_document(env, "d1", "t1", content, "runbook.md"))
    retry = asyncio.run(etl.process_document(env, "d1", "t1", content, "runbook.md", attempt=1))

    assert first["status"] == "retry"
    assert retry["status"] == "ok"
    assert len(env.DB.chunks) == 2
    assert len({chunk["vector_id"] for chunk in env.DB.chunks.values()}) == 2


def test_queue_retry_preserves_document_version_and_reindex_flag():
    env = make_env(main._sha256_hex("sk-test12345678"), mode="queue", vectorize_fail=True)
    env.DB.documents["d1"] = {
        "id": "d1", "tenant_id": "t1", "filename": "runbook.md",
        "content": "a valid runbook chunk", "status": "uploaded", "version": 7,
    }
    message = FakeMessage({"job": "etl.process", "document_id": "d1",
                           "tenant_id": "t1", "version": 7, "reindex": True})

    asyncio.run(etl.handle_queue_message(env, message))

    assert message.acked is True
    assert len(env.ETL_QUEUE.sent) == 1
    retry_payload = __import__("json").loads(env.ETL_QUEUE.sent[0])
    assert retry_payload["version"] == 7
    assert retry_payload["reindex"] is True
    assert retry_payload["attempt"] == 1


def test_consumer_does_not_ack_when_dead_letter_delivery_fails():
    env = make_env(main._sha256_hex("sk-test12345678"), mode="queue", vectorize_fail=True)
    env.ETL_DLQ = FailingQueue()
    env.DB.documents["d1"] = {
        "id": "d1", "tenant_id": "t1", "filename": "runbook.md",
        "content": "a valid runbook chunk", "status": "uploaded", "version": 1,
    }
    message = FakeMessage({"job": "etl.process", "document_id": "d1",
                           "tenant_id": "t1", "attempt": etl.MAX_RETRIES})

    asyncio.run(etl.handle_queue_message(env, message))

    assert message.acked is False
    assert message.retried is True


def test_consumer_dead_letters_after_max_retries():
    env = make_env(main._sha256_hex("sk-test12345678"), mode="queue",
                   vectorize_fail=True)
    env.DB.documents["d1"] = {
        "id": "d1", "tenant_id": "t1", "filename": "runbook.md",
        "content": "OOMKilled exit code 137", "status": "uploaded",
        "idempotency_key": "ik", "version": 1,
    }
    message = FakeMessage({"job": "etl.process", "document_id": "d1",
                           "tenant_id": "t1", "version": 1,
                           "attempt": etl.MAX_RETRIES})
    asyncio.run(etl.handle_queue_message(env, message))

    assert message.acked is True
    assert env.DB.documents["d1"]["status"] == "failed"
    assert len(env.ETL_DLQ.sent) == 1


def test_consumer_acks_unknown_jobs():
    env = make_env(main._sha256_hex("sk-test12345678"), mode="queue")
    message = FakeMessage({"job": "something.else"})
    asyncio.run(etl.handle_queue_message(env, message))

    assert message.acked is True
    assert message.retried is False
