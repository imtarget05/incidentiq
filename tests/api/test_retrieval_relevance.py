import asyncio
import sqlite3
from types import SimpleNamespace

import main


class AI:
    async def run(self, _model, _inputs):
        return {"vectors": [[0.1, 0.2]]}


class Vectorize:
    def __init__(self, matches):
        self.matches = matches

    async def query(self, _vector, _options):
        return {"matches": self.matches}


class DB:
    def __init__(self, rows):
        self.rows = rows

    def prepare(self, _sql):
        return self

    def bind(self, *_params):
        return self

    async def all(self):
        return self.rows


def match(doc_id, content, score=0.9):
    return {"id": doc_id, "score": score,
            "metadata": {"document_id": doc_id, "chunk_id": doc_id + "-0",
                         "content": content, "tenant_id": "t1"}}


def search(title, matches, fts_rows=()):
    env = SimpleNamespace(ai=AI(), VECTORIZE_INDEX=Vectorize(matches), DB=DB(fts_rows))
    return asyncio.run(main._hybrid_search(env, "t1", title + " payment-api prod", keyword_query=title))


def test_unknown_incident_abstains_from_generic_vector_neighbors():
    results = search("Weird timeout", [match("db-timeout", "Database connection timeout. Check pool.")])
    assert results == []


def test_keyword_result_is_not_discarded_after_five_vector_neighbors():
    vectors = [match(f"vec-{i}", "OOMKilled exit code 137. Check memory limit.") for i in range(5)]
    exact = ("expected", "expected.txt", "OOMKilled payment-api: memory limit exceeded.", -5.0)
    results = search("OOMKilled payment-api", vectors, [exact])
    assert results[0]["document_id"] == "expected"
    assert len(results) == 5


def test_newest_identical_runbook_is_kept_when_fts_limit_is_five():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE documents(id TEXT, tenant_id TEXT, filename TEXT, content TEXT, uploaded_at INTEGER);
        CREATE VIRTUAL TABLE documents_fts USING fts5(content, content=documents, content_rowid=rowid);
        CREATE TRIGGER documents_fts_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, content) VALUES (new.rowid, new.content);
        END;
    """)
    for i in range(6):
        conn.execute("INSERT INTO documents VALUES (?, 't1', 'runbook.txt', ?, ?)",
                     (f"old-{i}", "OOMKilled payment-api: check memory limit.", i))
    conn.execute("INSERT INTO documents VALUES ('fresh', 't1', 'runbook.txt', ?, 100)",
                 ("OOMKilled payment-api: check memory limit.",))

    class SqliteDB:
        def prepare(self, sql):
            self.sql = sql
            return self

        def bind(self, *params):
            self.params = params
            return self

        def all(self):
            return conn.execute(self.sql, self.params).fetchall()

    env = SimpleNamespace(ai=AI(), VECTORIZE_INDEX=Vectorize([]), DB=SqliteDB())
    results = asyncio.run(main._hybrid_search(env, "t1", "OOMKilled payment-api",
                                              keyword_query="OOMKilled payment-api"))
    assert len(results) == 5
    assert results[0]["document_id"] == "fresh"
