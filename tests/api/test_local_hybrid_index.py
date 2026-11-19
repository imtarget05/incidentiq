import asyncio

import pytest

from eval.run_local_fts_ai_benchmark import LocalVectorize


def test_local_vectorize_orders_cosine_matches_and_enforces_tenant():
    index = LocalVectorize(
        [{"id": "a", "content": "alpha"}, {"id": "b", "content": "beta"}],
        [[1.0, 0.0], [0.0, 1.0]], "tenant-a",
    )
    matches = asyncio.run(index.query(
        [0.9, 0.1], {"topK": 2, "namespace": "tenant-a", "filter": {"tenant_id": "tenant-a"}},
    ))["matches"]
    assert [match["metadata"]["document_id"] for match in matches] == ["a", "b"]
    assert asyncio.run(index.query(
        [1.0, 0.0], {"topK": 2, "namespace": "tenant-b", "filter": {"tenant_id": "tenant-b"}},
    ))["matches"] == []
    assert index.queries == 2


def test_local_vectorize_rejects_incomplete_or_invalid_embeddings():
    with pytest.raises(ValueError, match="Every document"):
        LocalVectorize([{"id": "a", "content": "alpha"}], [], "tenant-a")
    with pytest.raises(ValueError, match="Invalid embedding"):
        LocalVectorize([{"id": "a", "content": "alpha"}], [[0.0, 0.0]], "tenant-a")
