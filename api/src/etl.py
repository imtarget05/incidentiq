"""AI Knowledge Platform — ETL worker logic.

Handles document chunking, Workers AI embedding, Vectorize upsert, and D1
status updates. Designed to be invoked from a Cloudflare Queues consumer with
bounded retries and a dead-letter queue.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 800
MAX_CHUNKS_PER_DOCUMENT = 25

def _rows(result: Any) -> List[Any]:
    if isinstance(result, dict):
        return list(result.get("results") or [])
    rows = getattr(result, "results", None)
    if rows is not None:
        return list(rows)
    return list(result or [])


async def _db_all(stmt: Any) -> List[Any]:
    res = stmt.all()
    if inspect.isawaitable(res):
        res = await res
    return _rows(res)


MAX_RETRIES = 3


# --------------------------------------------------------------------------- retry circuit breaker
#
# D1-backed, per-tenant circuit breaker for the queue ETL path (table
# `etl_circuit_state`, migrations/006_orchestration.sql). A tenant whose ETL
# keeps failing floods the queue with retries; the breaker lets a single
# half-open probe through after a cooldown instead. Every helper is wrapped in
# try/except and fails OPEN: if the breaker table itself is broken, ETL must
# never be blocked by its own safety mechanism.

CB_THRESHOLD = 5           # consecutive failures before the circuit opens
CB_COOLDOWN_MS = 60_000    # default half-open cooldown


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _circuit_check(env: Any, key: str) -> str:
    """Return "closed" | "open" | "half_open" for a breaker key."""
    try:
        rows = await _db_all(env.DB.prepare(
            "SELECT consecutive_failures, opened_at, half_open_after_ms "
            "FROM etl_circuit_state WHERE key = ?"
        ).bind(key))
        if not rows:
            return "closed"
        r = rows[0]
        failures = int(r[0] if not isinstance(r, dict) else r.get("consecutive_failures") or 0)
        if failures < CB_THRESHOLD:
            return "closed"
        opened_at = r[1] if not isinstance(r, dict) else r.get("opened_at")
        cooldown = r[2] if not isinstance(r, dict) else r.get("half_open_after_ms")
        opened_at = int(opened_at) if opened_at is not None else 0
        cooldown = int(cooldown) if cooldown else CB_COOLDOWN_MS
        if _now_ms() - opened_at < cooldown:
            return "open"
        return "half_open"
    except Exception:
        # Fail OPEN: a broken breaker table must not block ETL.
        return "closed"


async def _circuit_record_success(env: Any, key: str) -> None:
    """Close the breaker: clear all state for the key."""
    try:
        await env.DB.prepare("DELETE FROM etl_circuit_state WHERE key = ?").bind(key).run()
    except Exception:
        pass  # fail open


async def _circuit_record_failure(env: Any, key: str) -> None:
    """Increment failures; set/refresh opened_at when the threshold is crossed.

    Refreshing opened_at on every failure at/above the threshold also gives a
    failing half-open probe a fresh cooldown (re-open + increment).
    """
    try:
        await env.DB.prepare(
            "INSERT INTO etl_circuit_state (key, consecutive_failures, opened_at, half_open_after_ms) "
            "VALUES (?, 1, NULL, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "  consecutive_failures = consecutive_failures + 1, "
            "  opened_at = CASE WHEN consecutive_failures + 1 >= ? THEN ? "
            "                   ELSE etl_circuit_state.opened_at END"
        ).bind(key, CB_COOLDOWN_MS, CB_THRESHOLD, _now_ms()).run()
    except Exception:
        pass  # fail open


async def _circuit_mark_probe(env: Any, key: str) -> None:
    """Best-effort half-open single-flight gate.

    While a half-open probe is being processed, refresh opened_at so every
    other concurrent check sees "open" and does not join. This is racy under
    true parallel consumers (two probes may slip through); that is acceptable
    — the probe result (success closes, failure re-opens) is what matters.
    """
    try:
        await env.DB.prepare(
            "UPDATE etl_circuit_state SET opened_at = ? WHERE key = ?"
        ).bind(_now_ms(), key).run()
    except Exception:
        pass  # fail open


def coerce_payload(body: Any) -> Dict[str, Any]:
    """Normalize a queue message body (Python dict/str or a JS proxy)."""
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    if isinstance(body, str):
        return json.loads(body)
    try:
        from js import JSON as JSJSON  # type: ignore[import-not-found]
        return json.loads(JSJSON.stringify(body))
    except Exception:
        return json.loads(str(body))


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    chunks: List[str] = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        chunks.append(text[:cut])
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks[:MAX_CHUNKS_PER_DOCUMENT]


async def embed_texts(env: Any, texts: List[str]) -> List[Optional[List[float]]]:
    """Embed a batch of texts via Workers AI. Returns one vector per text."""
    if not texts:
        return []
    try:
        result = await env.ai.run(
            "@cf/qwen/qwen3-embedding-0.6b",
            {"text": texts},
        )
        vectors = result.get("vectors") if isinstance(result, dict) else None
        if vectors:
            return [list(map(float, v)) for v in vectors]
    except Exception:
        pass
    return [None] * len(texts)


async def _delete_vectors_for_document(env: Any, document_id: str, tenant_id: str) -> List[str]:
    """Delete existing vectors before a reindex, propagating failures for retry.

    Returns the list of vector ids that were requested for deletion.
    """
    vector_ids: List[str] = []
    try:
        rows = await _db_all(env.DB.prepare(
            "SELECT vector_id FROM chunks WHERE document_id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id))
    except Exception as exc:
        raise RuntimeError("Could not load existing document vectors") from exc
    for r in rows or []:
        vid = r[1] if not isinstance(r, dict) else r.get("vector_id")
        if vid:
            vector_ids.append(vid)
    if vector_ids:
        await env.VECTORIZE_INDEX.delete(ids=vector_ids)
    return vector_ids


async def process_document(env: Any, document_id: str, tenant_id: str,
                           content: str, filename: str,
                           version: int = 1, attempt: int = 0,
                           reindex: bool = False) -> Dict[str, Any]:
    """Process a single document end-to-end.

    Returns a status dict: {"status": "ok"|"retry"|"dlq", "chunks": n}.
    """
    if reindex:
        try:
            await _delete_vectors_for_document(env, document_id, tenant_id)
        except Exception:
            return {
                "status": "retry" if attempt < MAX_RETRIES else "dlq",
                "chunks": 0,
                "reason": "vector_cleanup_failed",
            }

    chunks = chunk_text(content)
    if not chunks:
        try:
            await env.DB.prepare(
                "UPDATE documents SET status = 'processed', processed_at = ?, error = NULL, version = ? "
                "WHERE id = ? AND tenant_id = ?"
            ).bind(int(__import__("time").time() * 1000), version, document_id, tenant_id).run()
        except Exception:
            pass
        return {"status": "ok", "chunks": 0}

    vectors = await embed_texts(env, chunks)
    if len(vectors) != len(chunks) or any(vector is None for vector in vectors):
        reason = "embedding_incomplete"
        return {
            "status": "retry" if attempt < MAX_RETRIES else "dlq",
            "chunks": 0,
            "reason": reason,
        }

    # Build Vectorize points with versioned ids.
    points: List[Dict[str, Any]] = []
    db_rows: List[tuple] = []
    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        point_id = f"{document_id}-v{version}-{i}"
        points.append({
            "id": point_id,
            "values": vector,
            "metadata": {
                "document_id": document_id,
                "tenant_id": tenant_id,
                "chunk_id": point_id,
                "content": chunk,
                "filename": filename,
            },
        })
        db_rows.append((point_id, document_id, tenant_id, chunk, point_id, version))

    # Upsert to Vectorize.
    if points:
        try:
            await env.VECTORIZE_INDEX.upsert(points)
        except Exception as exc:
            if attempt < MAX_RETRIES:
                return {"status": "retry", "chunks": 0, "reason": str(exc)}
            return {"status": "dlq", "chunks": 0, "reason": str(exc)}

    # Persist chunk metadata to D1 and mark document processed.
    try:
        for row in db_rows:
            await env.DB.prepare(
                "INSERT INTO chunks (id, document_id, tenant_id, content, vector_id, version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET content = excluded.content, "
                "vector_id = excluded.vector_id, version = excluded.version, created_at = excluded.created_at"
            ).bind(*row, int(__import__("time").time() * 1000)).run()
        await env.DB.prepare(
            "UPDATE documents SET status = 'processed', processed_at = ?, error = NULL, version = ? "
            "WHERE id = ? AND tenant_id = ?"
        ).bind(int(__import__("time").time() * 1000), version, document_id, tenant_id).run()
    except Exception as exc:
        if attempt < MAX_RETRIES:
            return {"status": "retry", "chunks": len(points), "reason": str(exc)}
        return {"status": "dlq", "chunks": len(points), "reason": str(exc)}

    return {"status": "ok", "chunks": len(points)}


async def handle_queue_message(env: Any, message: Any) -> None:
    """Cloudflare Queues consumer entry point.

    Parses the message body, runs ETL, and acks / retries / DLQs accordingly.
    """
    body = message.body
    payload = coerce_payload(body)

    job = payload.get("job")
    if job != "etl.process":
        message.ack()
        return

    document_id = payload.get("document_id")
    tenant_id = payload.get("tenant_id")
    attempt = int(payload.get("attempt", 0))
    version = int(payload.get("version", 1))
    reindex = bool(payload.get("reindex", False))

    # Retry circuit breaker (per tenant) — checked before doing any work.
    circuit_key = f"etl:{tenant_id}"
    circuit_state = await _circuit_check(env, circuit_key)
    if circuit_state == "open":
        # Trip: dead-letter immediately, do NOT retry, and ack. The document
        # must be consumable again later via the DLQ reprocess operator path.
        logger.info("etl.circuit.open tenant=%s document=%s", tenant_id, document_id)
        return await _dlq_circuit_open(env, message, document_id, tenant_id, attempt)
    if circuit_state == "half_open":
        # Allow ONE probe through; mark it in-flight so parallel messages see
        # "open" again (best-effort single flight, races are acceptable).
        await _circuit_mark_probe(env, circuit_key)

    # Fetch document content from D1.
    try:
        row = await env.DB.prepare(
            "SELECT id, tenant_id, content, filename, status, version FROM documents WHERE id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id).first()
    except Exception:
        # Retry on transient DB errors.
        await _retry_message(message)
        return

    if not row:
        message.ack()
        return

    content = row[2] if not isinstance(row, dict) else row["content"]
    filename = row[3] if not isinstance(row, dict) else row["filename"]
    row_version = row[5] if not isinstance(row, dict) else row.get("version", 1)
    version = int(row_version) if version is None else int(version)

    result = await process_document(env, document_id, tenant_id, content, filename,
                                    version=version, attempt=attempt, reindex=reindex)

    if result["status"] == "ok":
        await _circuit_record_success(env, circuit_key)
        message.ack()
        return

    if result["status"] == "retry" and attempt < MAX_RETRIES:
        await _circuit_record_failure(env, circuit_key)
        # Re-enqueue with incremented attempt for retry.
        try:
            await env.ETL_QUEUE.send(json.dumps({
                "job": "etl.process",
                "document_id": document_id,
                "tenant_id": tenant_id,
                "version": version,
                "reindex": reindex,
                "attempt": attempt + 1,
            }))
        except Exception:
            await _retry_message(message)
        else:
            message.ack()
        return

    # Dead-letter: mark document failed and send to DLQ.
    await _circuit_record_failure(env, circuit_key)
    try:
        await env.DB.prepare(
            "UPDATE documents SET status = 'failed', error = ? WHERE id = ? AND tenant_id = ?"
        ).bind(result.get("reason", "etl_failed")[:500], document_id, tenant_id).run()
    except Exception:
        await _retry_message(message)
        return
    try:
        await env.ETL_DLQ.send(json.dumps({
            "job": "etl.process",
            "document_id": document_id,
            "tenant_id": tenant_id,
            "attempt": attempt,
            "reason": result.get("reason"),
        }))
    except Exception:
        await _retry_message(message)
        return
    message.ack()


async def _retry_message(message: Any) -> None:
    """Leave failed work unacknowledged so the queue can retry or dead-letter it."""
    try:
        retried = message.retry()
        if inspect.isawaitable(retried):
            await retried
    except Exception:
        # The platform owns retrying an unacknowledged message when retry() itself fails.
        pass


async def _dlq_circuit_open(env: Any, message: Any, document_id: Any,
                            tenant_id: Any, attempt: int) -> None:
    """Dead-letter a message while the tenant circuit is open.

    Ack without retrying so an open breaker cannot re-flood the queue. The
    document is best-effort marked `failed` with reason `circuit_open`; the
    DLQ payload carries the same reason for later reprocessing.
    """
    try:
        await env.DB.prepare(
            "UPDATE documents SET status = 'failed', error = ? WHERE id = ? AND tenant_id = ?"
        ).bind("circuit_open", document_id, tenant_id).run()
    except Exception:
        pass  # do not let a status write fail the DLQ path
    try:
        await env.ETL_DLQ.send(json.dumps({
            "job": "etl.process",
            "document_id": document_id,
            "tenant_id": tenant_id,
            "attempt": attempt,
            "reason": "circuit_open",
        }))
    except Exception:
        # DLQ unavailable: fall back to a platform retry rather than losing work.
        await _retry_message(message)
        return
    message.ack()
