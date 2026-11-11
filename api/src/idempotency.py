"""Durable single-flight requests with expiration and fenced completion.

This prevents duplicate successful requests and allows recovery after a process
crash. It does not promise exactly-once provider billing if a provider completes
but the worker crashes before persisting its response.
"""
from typing import Any

LEASE_MS = 30_000
EXECUTION_TIMEOUT_SECONDS = 25


async def claim(db: Any, tenant: str, operation: str, key: str,
                payload_hash: str, owner: str, now: int):
    return await db.prepare(
        "INSERT INTO request_idempotency "
        "(tenant_id, operation, idempotency_key, payload_hash, state, owner_token, lease_until, updated_at) "
        "VALUES (?, ?, ?, ?, 'processing', ?, ?, ?) "
        "ON CONFLICT(tenant_id, operation, idempotency_key) DO UPDATE SET "
        "state = 'processing', owner_token = excluded.owner_token, "
        "lease_until = excluded.lease_until, updated_at = excluded.updated_at "
        "WHERE request_idempotency.payload_hash = excluded.payload_hash "
        "AND request_idempotency.state != 'completed' "
        "AND (request_idempotency.state = 'failed' OR request_idempotency.lease_until <= ?) "
        "RETURNING owner_token"
    ).bind(tenant, operation, key, payload_hash, owner, now + LEASE_MS, now, now).first()


async def get(db: Any, tenant: str, operation: str, key: str):
    return await db.prepare(
        "SELECT payload_hash, state, response_json, response_status, lease_until "
        "FROM request_idempotency WHERE tenant_id = ? AND operation = ? AND idempotency_key = ?"
    ).bind(tenant, operation, key).first()


async def complete(db: Any, tenant: str, operation: str, key: str,
                   owner: str, response: str, status: int, now: int):
    return await db.prepare(
        "UPDATE request_idempotency SET state = 'completed', response_json = ?, "
        "response_status = ?, updated_at = ? "
        "WHERE tenant_id = ? AND operation = ? AND idempotency_key = ? "
        "AND owner_token = ? AND state = 'processing' AND lease_until > ? RETURNING owner_token"
    ).bind(response, status, now, tenant, operation, key, owner, now).first()


async def fail(db: Any, tenant: str, operation: str, key: str, owner: str, now: int):
    await db.prepare(
        "UPDATE request_idempotency SET state = 'failed', lease_until = ?, updated_at = ? "
        "WHERE tenant_id = ? AND operation = ? AND idempotency_key = ? "
        "AND owner_token = ? AND state = 'processing'"
    ).bind(now, now, tenant, operation, key, owner).run()
