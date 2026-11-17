import asyncio

from scripts.eval_harness import FakeVectorize, score_citations


def test_fake_vectorize_accepts_worker_options_and_filters_tenant():
    matches = [
        {"id": "other", "metadata": {"tenant_id": "t2"}},
        {"id": "own", "metadata": {"tenant_id": "t1"}},
    ]
    result = asyncio.run(FakeVectorize(matches).query(
        [0.1, 0.2], {"topK": 5, "filter": {"tenant_id": "t1"}}
    ))
    assert [match["id"] for match in result["matches"]] == ["own"]


def test_citation_scores_are_zero_without_evidence():
    assert score_citations([], {"doc-1"}) == (0.0, 0.0)


def test_citation_scores_use_expected_document_rank():
    citations = [{"document_id": "other"}, {"document_id": "doc-1"}]
    assert score_citations(citations, {"doc-1"}) == (1.0, 0.5)
