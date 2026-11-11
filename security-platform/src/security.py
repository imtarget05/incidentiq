"""security-platform — Authentication helpers (API key hash + tenant binding).

Mirrors the IncidentIQ pattern: API keys are stored as SHA-256 hashes keyed by
an 8-char prefix, and every request is bound to a single tenant.
"""

from __future__ import annotations

import hashlib
from typing import Optional, Dict

from fastapi import Header, HTTPException, Request

from db import get_conn, put_conn


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def authenticate_tenant(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
) -> Dict:
    """Validate an API key and return the tenant row.

    Raises HTTPException(401) when the key is missing or invalid.
    """
    if not x_api_key or len(x_api_key) < 8:
        raise HTTPException(
            status_code=401, detail="missing or invalid X-Api-Key header"
        )

    prefix = x_api_key[:8]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, api_key_hash, is_active FROM tenants "
                "WHERE api_key_prefix = %s AND is_active = TRUE LIMIT 1",
                (prefix,),
            )
            row = cur.fetchone()
    finally:
        put_conn(conn)

    if row is None:
        raise HTTPException(status_code=401, detail="invalid or inactive API key")

    tenant_id, name, stored_hash, is_active = row
    if _sha256_hex(x_api_key) != stored_hash:
        raise HTTPException(status_code=401, detail="invalid or inactive API key")

    return {
        "id": str(tenant_id),
        "name": name,
    }


def require_tenant(
    request: Request, x_api_key: Optional[str] = Header(default=None)
) -> Dict:
    """FastAPI dependency wrapper around authenticate_tenant."""
    return authenticate_tenant(request, x_api_key)
