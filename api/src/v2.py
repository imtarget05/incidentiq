
# ---------------------------------------------------------------------------
# API v2 — versioned router (additive; v1 kept for backward compatibility).
# ---------------------------------------------------------------------------

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from main import (
    _db_all,
    _env,
    _json_error,
    _now_ms,
    _row_col,
    app,
    require_role,
)

_v2 = APIRouter(prefix="/api/v2")


@_v2.get("/incidents/{incident_id}")
async def v2_get_incident(incident_id: str, request: Request,
                          ctx: dict = Depends(require_role("reader"))):
    """v2 incident detail — identical to v1 but includes `api_version` field."""
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    try:
        row = await env.DB.prepare(
            "SELECT id, workspace_id, tenant_id, title, severity, service, environment, status, version, "
            "payload_hash, created_at, updated_at, resolved_at FROM incidents WHERE id = ? AND tenant_id = ?"
        ).bind(incident_id, tenant_id).first()
    except Exception as exc:
        return _json_error(500, "db_query_failed", str(exc))
    if not row:
        return JSONResponse({"error": {"code": "not_found", "message": "incident not found"}}, status_code=404)
    if _row_col(row, "workspace_id", 1) != workspace_id:
        return JSONResponse({"error": {"code": "forbidden", "message": "incident not in workspace"}}, status_code=403)
    incident = {
        "id": _row_col(row, "id", 0),
        "workspace_id": _row_col(row, "workspace_id", 1),
        "tenant_id": _row_col(row, "tenant_id", 2),
        "title": _row_col(row, "title", 3),
        "severity": _row_col(row, "severity", 4),
        "service": _row_col(row, "service", 5),
        "environment": _row_col(row, "environment", 6),
        "status": _row_col(row, "status", 7),
        "version": _row_col(row, "version", 8),
        "payload_hash": _row_col(row, "payload_hash", 9),
        "created_at": _row_col(row, "created_at", 10),
        "updated_at": _row_col(row, "updated_at", 11),
        "resolved_at": _row_col(row, "resolved_at", 12),
        "api_version": "v2",
    }
    return JSONResponse({"incident": incident})


@_v2.get("/health")
async def v2_health(request: Request):
    """v2 health — alias for /health/ready with api_version tag."""
    env = _env(request)
    checks: Dict[str, str] = {
        "d1": "ok" if (env and getattr(env, "DB", None)) else "unavailable",
        "vectorize": "ok" if (env and getattr(env, "VECTORIZE_INDEX", None)) else "unavailable",
        "workers_ai": "ok" if (env and getattr(env, "ai", None)) else "unavailable",
        "etl_queue": "ok" if (env and getattr(env, "ETL_QUEUE", None)) else "unavailable",
    }
    overall = "ok" if checks["d1"] == "ok" else "degraded"
    return JSONResponse({
        "status": overall, "api_version": "v2",
        "service": "ai-knowledge-platform",
        "checks": checks, "ts": _now_ms(),
    }, status_code=200 if overall == "ok" else 503)


@_v2.get("/metrics/quota")
async def v2_metrics_quota(request: Request, ctx: dict = Depends(require_role("reader"))):
    """v2 quota metrics — adds token_budget and reset_at fields."""
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    buckets: List[Dict[str, Any]] = []
    try:
        rows = await _db_all(env.DB.prepare(
            "SELECT bucket_key, count, window_start FROM rate_limit_buckets WHERE tenant_id = ?"
        ).bind(tenant_id))
        now = _now_ms()
        window_start = now - (now % 86400000)
        for r in rows or []:
            bk = r[0] if not isinstance(r, dict) else r.get("bucket_key")
            cnt = r[1] if not isinstance(r, dict) else r.get("count")
            ws = r[2] if not isinstance(r, dict) else r.get("window_start")
            # Reset count if the window has rolled over.
            effective_count = int(cnt or 0) if (ws == window_start) else 0
            buckets.append({
                "bucket_key": bk,
                "count": effective_count,
                "window_start": ws,
                "reset_at": window_start + 86400000,
            })
    except Exception:
        pass
    ai_bucket = next((b for b in buckets if b["bucket_key"] == "ai:daily"), None)
    ai_count = ai_bucket["count"] if ai_bucket else 0
    return JSONResponse({
        "api_version": "v2",
        "tenant_id": tenant_id,
        "ai_daily_count": ai_count,
        "daily_ai_limit": 100,
        "token_budget_remaining": max(0, 100 - ai_count),
        "reset_at": (_now_ms() - (_now_ms() % 86400000)) + 86400000,
        "buckets": buckets,
    })


app.include_router(_v2)
