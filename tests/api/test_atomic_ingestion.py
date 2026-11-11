"""Regression tests backed by SQLite constraints, not permissive fake inserts."""
import asyncio
import io
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from fastapi import UploadFile

import etl
import main


from sqlite_d1 import SqliteD1


class Queue:
    def __init__(self):
        self.sent = []

    async def send(self, body):
        self.sent.append(body)


def env_with_sqlite(barrier=False):
    return SimpleNamespace(DB=SqliteD1(barrier), ETL_QUEUE=Queue(), ETL_MODE="queue")


async def upload(env, content=b"runbook content", tenant="t1"):
    return await main.upload_document(
        SimpleNamespace(), {"tenant": {"id": tenant}},
        UploadFile(filename="runbook.md", file=io.BytesIO(content)), "same-key",
    )


def test_simultaneous_uploads_share_one_document(monkeypatch):
    async def scenario():
        env = env_with_sqlite(barrier=True)
        monkeypatch.setattr(main, "_env", lambda request: env)
        results = await asyncio.gather(upload(env), upload(env))
        assert [r.status_code for r in results] == [202, 202]
        assert len({json.loads(r.body)["document_id"] for r in results}) == 1
        assert env.DB.connection.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
        assert len(env.ETL_QUEUE.sent) == 1
    asyncio.run(scenario())


def test_upload_same_key_different_payload_conflicts_and_other_tenant_is_independent(monkeypatch):
    async def scenario():
        env = env_with_sqlite()
        monkeypatch.setattr(main, "_env", lambda request: env)
        assert (await upload(env)).status_code == 202
        conflict = await upload(env, b"different content")
        assert conflict.status_code == 409
        assert json.loads(conflict.body)["error"]["code"] == "idempotency_conflict"
        assert (await upload(env, b"different content", tenant="t2")).status_code == 202
    asyncio.run(scenario())


def test_upload_replay_uses_original_hash_after_document_update(monkeypatch):
    async def scenario():
        env = env_with_sqlite()
        monkeypatch.setattr(main, "_env", lambda request: env)
        first = await upload(env)
        env.DB.connection.execute("UPDATE documents SET content='edited later'")
        replay = await upload(env)
        assert replay.status_code == 202
        assert json.loads(replay.body)["document_id"] == json.loads(first.body)["document_id"]
    asyncio.run(scenario())


def test_upload_lookup_failure_fails_closed(monkeypatch):
    async def scenario():
        env = env_with_sqlite()
        env.DB.connection.close()
        monkeypatch.setattr(main, "_env", lambda request: env)
        response = await upload(env)
        assert response.status_code == 503
    asyncio.run(scenario())


def test_unique_migration_refuses_legacy_duplicates_without_deleting_records():
    db = sqlite3.connect(":memory:")
    migrations = sorted((Path(__file__).parents[2] / "migrations").glob("*.sql"))
    new = [p for p in migrations if p.name.startswith("004")]
    assert new, "idempotency migration missing"
    for p in migrations:
        if p.name < "004":
            db.executescript(p.read_text())
    db.execute("INSERT INTO tenants VALUES ('t1','Tenant',0,1)")
    for did in ("a", "b"):
        db.execute("INSERT INTO documents(id,tenant_id,filename,content,idempotency_key,uploaded_at) VALUES (?,'t1','f','x','dup',0)", (did,))
    try:
        db.executescript(new[0].read_text())
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("Migration must refuse ambiguous historical keys")
    assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 2


def test_stale_queue_version_does_not_embed_or_write():
    from test_etl_modes import FakeMessage, make_env
    async def scenario():
        env = make_env("hash", mode="queue")
        env.DB.documents["d1"] = {"id":"d1", "tenant_id":"t1", "content":"new version", "filename":"f", "status":"uploaded", "version":2}
        message = FakeMessage({"job":"etl.process", "document_id":"d1", "tenant_id":"t1", "version":1, "reindex":True})
        await etl.handle_queue_message(env, message)
        assert message.acked
        assert not env.ai.calls
        assert not env.VECTORIZE_INDEX.upserted
        assert env.DB.documents["d1"]["version"] == 2
    asyncio.run(scenario())


def test_concurrent_incident_creates_share_id_and_event(monkeypatch):
    async def scenario():
        env = env_with_sqlite(barrier=True)
        env.DB.connection.execute("INSERT INTO workspaces VALUES ('w1','Workspace',0,1)")
        monkeypatch.setattr(main, "_env", lambda request: env)
        class Request:
            async def json(self):
                return {"title":"Outage", "severity":"HIGH", "service":"api", "environment":"test"}
        ctx = {"tenant":{"id":"t1"}, "workspace_id":"w1"}
        responses = await asyncio.gather(*(main.create_incident(Request(), ctx, "same-incident") for _ in range(2)))
        assert sorted(r.status_code for r in responses) == [201,202]
        assert len({json.loads(r.body)["incident_id"] for r in responses}) == 1
        assert env.DB.connection.execute("SELECT count(*) FROM incident_events").fetchone()[0] == 1
    asyncio.run(scenario())


def test_legacy_incident_replay_requires_original_workspace(monkeypatch):
    async def scenario():
        env = env_with_sqlite()
        env.DB.connection.execute("INSERT INTO workspaces VALUES ('w1','Workspace',0,1)")
        env.DB.connection.execute("INSERT INTO workspaces VALUES ('w2','Other',0,1)")
        monkeypatch.setattr(main, "_env", lambda request: env)
        body = {"title":"Outage", "severity":"HIGH", "service":"api", "environment":"test"}
        class Request:
            async def json(self):
                return body
        legacy_hash = main._sha256_hex(json.dumps(body, sort_keys=True))
        env.DB.connection.execute("INSERT INTO incidents(id,workspace_id,tenant_id,title,severity,service,environment,payload_hash,idempotency_key,created_at,updated_at) VALUES ('legacy','w1','t1','Outage','HIGH','api','test',?,'legacy-key',0,0)", (legacy_hash,))
        same = await main.create_incident(Request(), {"tenant":{"id":"t1"},"workspace_id":"w1"}, "legacy-key")
        different = await main.create_incident(Request(), {"tenant":{"id":"t1"},"workspace_id":"w2"}, "legacy-key")
        assert same.status_code == 202
        assert json.loads(same.body)["incident_id"] == "legacy"
        assert different.status_code == 409
    asyncio.run(scenario())


class QuestionRequest:
    def __init__(self, question="What is AI?"):
        self.question = question

    async def json(self):
        return {"question": self.question}


class QuestionAI:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.started = asyncio.Event()
        self.release = None

    async def run(self, model, inputs):
        if "embedding" in model:
            return {"vectors": []}
        self.calls += 1
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("provider failed")
        return {"response":"Insufficient information", "usage":{"total_tokens":3}}


def test_question_replays_exact_result_without_model_call_and_conflicts_on_payload(monkeypatch):
    async def scenario():
        env = env_with_sqlite()
        env.ai = QuestionAI()
        monkeypatch.setattr(main, "_env", lambda request: env)
        first = await main.ask_question(QuestionRequest(), {"id":"t1"}, "key%_")
        replay = await main.ask_question(QuestionRequest(), {"id":"t1"}, "key%_")
        conflict = await main.ask_question(QuestionRequest("different?"), {"id":"t1"}, "key%_")
        separate = await main.ask_question(QuestionRequest(), {"id":"t1"}, "key")
        assert first.status_code == replay.status_code == 200
        assert replay.body == first.body
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert conflict.status_code == 409
        assert separate.status_code == 200
        assert env.ai.calls == 2
    asyncio.run(scenario())


def test_question_atomic_claim_allows_one_inflight_call_and_failed_attempt_can_retry(monkeypatch):
    async def scenario():
        env = env_with_sqlite()
        env.ai = QuestionAI()
        env.ai.release = asyncio.Event()
        monkeypatch.setattr(main, "_env", lambda request: env)
        running = asyncio.create_task(main.ask_question(QuestionRequest(), {"id":"t1"}, "parallel"))
        await env.ai.started.wait()
        duplicate = await main.ask_question(QuestionRequest(), {"id":"t1"}, "parallel")
        assert duplicate.status_code == 409
        assert json.loads(duplicate.body)["error"]["code"] == "idempotency_in_progress"
        env.ai.fail = True
        env.ai.release.set()
        assert (await running).status_code == 503
        env.ai.fail = False
        success = await main.ask_question(QuestionRequest(), {"id":"t1"}, "parallel")
        assert success.status_code == 200
        assert env.ai.calls == 2
    asyncio.run(scenario())


def test_question_expired_lease_is_reclaimed_and_old_owner_cannot_complete(monkeypatch):
    async def scenario():
        env = env_with_sqlite()
        env.ai = QuestionAI()
        monkeypatch.setattr(main, "_env", lambda request: env)
        payload_hash = main._sha256_hex(json.dumps({"question":"What is AI?"}, sort_keys=True))
        env.DB.connection.execute("INSERT INTO request_idempotency(tenant_id,operation,idempotency_key,payload_hash,state,owner_token,lease_until,updated_at) VALUES ('t1','question','crash',?,'processing','dead-process',0,0)", (payload_hash,))
        response = await main.ask_question(QuestionRequest(), {"id":"t1"}, "crash")
        assert response.status_code == 200
        stale = env.DB.connection.execute("UPDATE request_idempotency SET response_json='bad' WHERE owner_token='dead-process' AND state='processing' RETURNING response_json").fetchone()
        assert stale is None
        replay = await main.ask_question(QuestionRequest(), {"id":"t1"}, "crash")
        assert replay.body == response.body
        assert env.ai.calls == 1
    asyncio.run(scenario())


def test_migration_preflight_reports_duplicates_without_writing(tmp_path):
    import subprocess
    import sys
    database = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(database)
    for table in ("documents", "incidents"):
        connection.execute(f"CREATE TABLE {table}(id TEXT,tenant_id TEXT,idempotency_key TEXT)")
    connection.executemany("INSERT INTO documents VALUES (?,'t1','dup')", [("a",),("b",)])
    connection.commit()
    connection.close()
    before = database.read_bytes()
    script = Path(__file__).parents[2] / "scripts/migration_preflight.py"
    result = subprocess.run([sys.executable, str(script), "--database", str(database)], capture_output=True, text=True)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["duplicates"]["documents"][0]["record_count"] == 2
    assert set(report["duplicates"]["documents"][0]["record_ids"].split(",")) == {"a","b"}
    assert database.read_bytes() == before


def test_question_expired_running_owner_is_fenced_after_recovery(monkeypatch):
    async def scenario():
        env = env_with_sqlite()
        first_ai = QuestionAI()
        first_ai.release = asyncio.Event()
        env.ai = first_ai
        monkeypatch.setattr(main, "_env", lambda request: env)
        first = asyncio.create_task(main.ask_question(QuestionRequest(), {"id":"t1"}, "expired"))
        await first_ai.started.wait()
        env.DB.connection.execute("UPDATE request_idempotency SET lease_until=0")
        env.ai = QuestionAI()
        recovered = await main.ask_question(QuestionRequest(), {"id":"t1"}, "expired")
        assert recovered.status_code == 200
        first_ai.release.set()
        stale = await first
        assert stale.status_code == 409
        assert json.loads(stale.body)["error"]["code"] == "idempotency_lease_lost"
        replay = await main.ask_question(QuestionRequest(), {"id":"t1"}, "expired")
        assert replay.body == recovered.body
    asyncio.run(scenario())


def test_question_timeout_releases_claim_for_retry(monkeypatch):
    import idempotency
    async def scenario():
        env = env_with_sqlite()
        env.ai = QuestionAI()
        env.ai.release = asyncio.Event()
        monkeypatch.setattr(main, "_env", lambda request: env)
        monkeypatch.setattr(idempotency, "EXECUTION_TIMEOUT_SECONDS", 0.01)
        response = await main.ask_question(QuestionRequest(), {"id":"t1"}, "timeout")
        assert response.status_code == 503
        row = env.DB.connection.execute("SELECT state FROM request_idempotency").fetchone()
        assert row[0] == "failed"
        env.ai.release.set()
        assert (await main.ask_question(QuestionRequest(), {"id":"t1"}, "timeout")).status_code == 200
    asyncio.run(scenario())
