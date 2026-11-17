import asyncio
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
