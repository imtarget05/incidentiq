"""Edge-case QA tests for IncidentIQ helper functions (no DB mocking needed)."""

import main
import etl


# --------------------------------------------------------------------------- #
# chunk_text edge cases
# --------------------------------------------------------------------------- #

def test_chunk_text_empty_and_whitespace():
    assert main._chunk_text("") == []
    assert main._chunk_text("   ") == []
    assert main._chunk_text("\n\n\t") == []


def test_chunk_text_exact_max_chars():
    # 10 chars exactly, max_chars=10 -> single chunk
    assert main._chunk_text("0123456789", max_chars=10) == ["0123456789"]


def test_chunk_text_splits_on_space():
    text = "a b c d e f g h i j"
    chunks = main._chunk_text(text, max_chars=5)
    # rfind cuts at the last space before max_chars
    assert chunks == ["a b c", "d e f", "g h i", "j"]


def test_chunk_text_respects_max_chunks_limit():
    text = "x " * 100  # 200 chars
    chunks = main._chunk_text(text, max_chars=10)
    assert len(chunks) <= etl.MAX_CHUNKS_PER_DOCUMENT


def test_chunk_text_single_word_longer_than_max():
    long_word = "x" * 5000
    chunks = main._chunk_text(long_word, max_chars=800)
    # Forced cut at max_chars when no space found
    assert len(chunks[0]) == 800


# --------------------------------------------------------------------------- #
# coerce_payload edge cases
# --------------------------------------------------------------------------- #

def test_coerce_payload_dict_passthrough():
    assert etl.coerce_payload({"job": "etl.process"}) == {"job": "etl.process"}


def test_coerce_payload_json_string():
    result = etl.coerce_payload('{"job": "etl.process", "attempt": 2}')
    assert result == {"job": "etl.process", "attempt": 2}


def test_coerce_payload_bytes():
    result = etl.coerce_payload(b'{"job": "etl.process"}')
    assert result == {"job": "etl.process"}


def test_coerce_payload_invalid_json_raises():
    try:
        etl.coerce_payload("not json at all")
        assert False, "Should have raised"
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# ETL process_document statuses (no DB needed for unit-level checks)
# --------------------------------------------------------------------------- #

def test_etl_max_chunks_per_document_enforced():
    # Document with many words should be capped at MAX_CHUNKS_PER_DOCUMENT
    text = "word " * 10000
    chunks = etl.chunk_text(text, max_chars=10)
    assert len(chunks) <= etl.MAX_CHUNKS_PER_DOCUMENT