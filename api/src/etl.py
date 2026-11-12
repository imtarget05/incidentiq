"""AI Knowledge Platform — ETL worker logic.

Handles document chunking, Workers AI embedding, Vectorize upsert, and D1
status updates. Designed to be invoked from a Cloudflare Queues consumer with
bounded retries and a dead-letter queue.
"""

from __future__ import annotations

import inspect
import json
import asyncio
import re
from typing import Any, Dict, List, Optional

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
        raw_vectors = None
        if isinstance(result, dict):
            raw_vectors = result.get("vectors") or result.get("data")
        if raw_vectors:
            vectors: List[List[float]] = []
            for item in raw_vectors:
                if isinstance(item, dict):  # newer schema: {"embedding": [...]}
                    item = item.get("embedding") or item.get("vector") or item.get("data")
                vectors.append([float(x) for x in item])
            return vectors
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
        last_exc = None
        for _attempt in range(3):  # Vectorize API returns transient errors while
            try:                   # its async mutation backlog is processing.
                _delete_by = getattr(env.VECTORIZE_INDEX, "deleteByIds", None)
                if _delete_by is not None:
                    await _delete_by(vector_ids)
                else:
                    await env.VECTORIZE_INDEX.delete(ids=vector_ids)
                break
            except Exception as exc:
                last_exc = exc
                await asyncio.sleep(2 * (_attempt + 1))
        else:
            raise last_exc if last_exc else RuntimeError("vectorize delete failed")
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
        except Exception as exc:
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
            "namespace": tenant_id,
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
        message.ack()
        return

    if result["status"] == "retry" and attempt < MAX_RETRIES:
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
