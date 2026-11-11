"""IncidentIQ — FastAPI Worker (Cloudflare Workers Python).

Production incident triage API: incident management, grounded RAG triage with
citations, document versioning, and observability. Never mutates Production.

Routes:
  GET    /health
  POST   /api/v1/workspaces
  POST   /api/v1/documents   (multipart upload, idempotent, tenant auth)
  GET    /api/v1/documents   (list tenant documents)
  PUT    /api/v1/documents/{id}   (version bump + re-enqueue ETL)
  DELETE /api/v1/documents/{id}
  POST   /api/v1/documents/{id}/reindex
  POST   /api/v1/incidents   (idempotent)
  GET    /api/v1/incidents/{id}
  PATCH  /api/v1/incidents/{id}   (status transition, If-Match)
  POST   /api/v1/incidents/{id}/events
  GET    /api/v1/incidents/{id}/timeline
  POST   /api/v1/incidents/{id}/triage   (grounded, read-only)
  GET    /api/v1/incidents/{id}/report
  POST   /api/v1/question   (RAG ask with citations)
  GET    /api/v1/metrics/quota   (AI quota dashboard)

Environment bindings (wrangler.toml):
  DB              - D1 database
  VECTORIZE_INDEX - Vectorize index (1024-dim, cosine)
  ETL_QUEUE       - Queue producer (ETL jobs)
  ETL_DLQ         - Queue producer (dead-letter)
  ai              - Workers AI
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import time
import uuid
from typing import Annotated, Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, Request, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

try:  # Provided by the Workers runtime; absent in local pytest runs.
    import asgi
    from workers import WorkerEntrypoint
except ImportError:  # pragma: no cover - local test fallback
    asgi = None  # type: ignore[assignment]

    class WorkerEntrypoint:  # type: ignore[no-redef]
        pass

import etl

try:  # Azure backend client (Option B hybrid). Available at runtime.
    from azure_backend import AzureBackendClient, AzureBackendError
except ImportError:  # pragma: no cover - local test fallback
    AzureBackendClient = None  # type: ignore[assignment]
    AzureBackendError = RuntimeError  # type: ignore[assignment]

import os as _os


def _use_azure_backend() -> bool:
    """Feature flag: route data-plane calls to the Azure backend instead of D1."""
    return _os.environ.get("USE_AZURE_BACKEND", "0") == "1"


def _azure_backend_url() -> Optional[str]:
    return _os.environ.get("AZURE_BACKEND_URL")


def _azure_edge_secret() -> Optional[str]:
    return _os.environ.get("AZURE_EDGE_SECRET")


def _azure_client(request: Request) -> Optional[Any]:
    """Build an AzureBackendClient bound to the current request's tenant key."""
    if AzureBackendClient is None or not _use_azure_backend():
        return None
    base_url = _azure_backend_url()
    edge_secret = _azure_edge_secret()
    if not base_url or not edge_secret:
        return None
    api_key = (
        request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    )
    return AzureBackendClient(
        base_url=base_url, edge_secret=edge_secret, api_key=api_key,
    )


def _rows(result: Any) -> List[Any]:
    """Normalize a D1 `.all()` result: the runtime returns {results, success, meta}."""
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

app = FastAPI(title="AI Knowledge Platform", version="1.0.0")

# ---------------------------------------------------------------------------
# Unified error responses: {"error": {"code", "message", "status", "request_id"}}.
# ---------------------------------------------------------------------------


class ApiError(Exception):
    """App-level error carrying the unified error code/status for handlers."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


def api_error(request: Request, status: int, code: str, message: str,
              headers: Optional[Dict[str, str]] = None) -> JSONResponse:
    """Format every API error response with the unified envelope."""
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(
        {"error": {"code": code, "message": message, "status": status, "request_id": rid}},
        status_code=status, headers=headers,
    )


def _validation_error_response(request: Request, exc: Exception) -> JSONResponse:
    """Build the unified 422 body from a pydantic/FastAPI validation error."""
    try:
        errors = exc.errors()  # type: ignore[attr-defined]
    except Exception:
        errors = []
    details = [{"loc": list(err.get("loc", [])), "msg": str(err.get("msg", "")),
                "type": str(err.get("type", ""))} for err in errors]
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(
        {"error": {"code": "validation_error", "message": "request validation failed",
                   "status": 422, "request_id": rid, "details": details}},
        status_code=422,
    )


def _register_error_handlers(application: FastAPI) -> None:
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return api_error(request, exc.status, exc.code, exc.message)

    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        return api_error(request, exc.status_code, "http_error", detail,
                         headers=getattr(exc, "headers", None))

    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _validation_error_response(request, exc)

    application.add_exception_handler(ApiError, _api_error_handler)
    application.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    application.add_exception_handler(RequestValidationError, _validation_error_handler)


_register_error_handlers(app)


# ---------------------------------------------------------------------------
# Schema-based request validation (pydantic v2).
# ---------------------------------------------------------------------------


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    service: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    environment: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class IncidentPatch(BaseModel):
    status: Literal["OPEN", "INVESTIGATING", "RESOLVED"]


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class DocumentUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=1_000_000)
    filename: Optional[str] = Field(default=None, max_length=255)


# ---------------------------------------------------------------------------
# Observability: correlation IDs, structured logging, rate limits, quota.
# ---------------------------------------------------------------------------

_REQUEST_LOG: List[Dict[str, Any]] = []
_MAX_REQUEST_LOG = 5000

AI_DAILY_LIMIT = 100
AI_BUCKET_KEY = "ai:daily"
# Daily per-tenant AI token quota. Enforced best-effort: the pre-check below
# reads the accumulated "tokens:daily" bucket, but tokens are only known after
# a run completes, so concurrent requests can overshoot slightly. Race windows
# are acceptable (best-effort enforcement); the bucket is accumulated post-run.
TOKEN_DAILY_LIMIT = 200_000
TOKEN_BUCKET_KEY = "tokens:daily"
_DAY_MS = 86_400_000

REQUIRED_BINDINGS = ("DB", "VECTORIZE_INDEX", "ETL_QUEUE", "ETL_DLQ", "ai")


def validate_bindings(env: Any) -> List[str]:
    """Return the names of required bindings/vars missing from `env`.

    Defensive: `env` may be a JS proxy whose attribute access raises.
    """
    missing: List[str] = []
    for name in REQUIRED_BINDINGS:
        try:
            value = getattr(env, name, None)
        except Exception:
            value = None
        if value is None:
            missing.append(name)
    return missing


def _log_event(event: str, **fields: Any) -> None:
    """Emit a structured JSON log record to stdout."""
    record = {"ts": _now_ms(), "event": event}
    record.update(fields)
    try:
        print(json.dumps(record))
    except Exception:
        pass


def _correlation_id(request: Request) -> str:
    rid = request.headers.get("x-request-id") or request.headers.get("X-Request-ID")
    if not rid:
        rid = str(uuid.uuid4())
    request.state.request_id = rid
    return rid


def _db(request: Request) -> Any:
    env = _env(request)
    return getattr(env, "DB", None) if env is not None else None


def _is_ai_path(path: str) -> bool:
    """AI-quota middleware applies to question/triage on both v1 and v2."""
    if path.startswith("/api/v1/question") or path.startswith("/api/v2/question"):
        return True
    return (path.startswith("/api/v1/incidents/") or path.startswith("/api/v2/incidents/")) and "/triage" in path


def _utc_day_window(now_ms: int) -> int:
    """Start (ms) of the UTC day containing now_ms."""
    return now_ms - (now_ms % _DAY_MS)


async def _ai_rate_limit(request: Request, env: Any, tenant_id: str) -> bool:
    """Daily per-tenant AI quota gate. True = allowed.

    Window keyed by UTC day start (ms). Missing row or a new day resets the
    count; the upsert below writes the incremented count with today's window
    start (a reset naturally overwrites the stale row). D1 failures fail OPEN
    so quota bookkeeping never blocks inference traffic.
    """
    try:
        now = _now_ms()
        window_start = _utc_day_window(now)
        row = await env.DB.prepare(
            "SELECT count, window_start FROM rate_limit_buckets WHERE tenant_id = ? AND bucket_key = ?"
        ).bind(tenant_id, AI_BUCKET_KEY).first()
        count = 0
        if row:
            count = int(_row_col(row, "count", 0) or 0)
            if _row_col(row, "window_start", 1) != window_start:
                count = 0  # new daily window
        if count >= AI_DAILY_LIMIT:
            _log_event("rate_limit.exceeded", request_id=getattr(request.state, "request_id", None),
                       tenant_id=tenant_id, path=request.url.path)
            return False
        await env.DB.prepare(
            "INSERT INTO rate_limit_buckets (id, tenant_id, bucket_key, count, window_start) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_id, bucket_key) DO UPDATE SET count = count + 1, window_start = excluded.window_start"
        ).bind(str(uuid.uuid4()), tenant_id, AI_BUCKET_KEY, count + 1, window_start).run()
        return True
    except Exception as exc:
        # Fail open: quota accounting must not block AI requests.
        _log_event("rate_limit.db_error", request_id=getattr(request.state, "request_id", None),
                   tenant_id=tenant_id, error=type(exc).__name__)
        return True


def _seconds_until_utc_midnight(now_ms: int) -> int:
    """Whole seconds from now until the next UTC midnight (min 1)."""
    return max(1, (_utc_day_window(now_ms) + _DAY_MS - now_ms + 999) // 1000)


async def _token_quota_check(request: Request, env: Any, tenant_id: str) -> bool:
    """Daily per-tenant AI token quota gate (read-only pre-check). True = allowed.

    Reads the accumulated "tokens:daily" bucket written post-run by
    _accumulate_tokens. Tokens are only known AFTER a run, so this is
    best-effort enforcement: concurrent requests can overshoot the limit and
    race windows are acceptable. A stale window (previous UTC day) counts as 0.
    D1 failures fail OPEN so quota bookkeeping never blocks inference traffic.
    """
    try:
        now = _now_ms()
        window_start = _utc_day_window(now)
        row = await env.DB.prepare(
            "SELECT count, window_start FROM rate_limit_buckets WHERE tenant_id = ? AND bucket_key = ?"
        ).bind(tenant_id, TOKEN_BUCKET_KEY).first()
        count = 0
        if row:
            count = int(_row_col(row, "count", 0) or 0)
            if _row_col(row, "window_start", 1) != window_start:
                count = 0  # new daily window
        if count >= TOKEN_DAILY_LIMIT:
            _log_event("token_quota.exceeded", request_id=getattr(request.state, "request_id", None),
                       tenant_id=tenant_id, count=count, limit=TOKEN_DAILY_LIMIT,
                       path=request.url.path)
            return False
        return True
    except Exception as exc:
        # Fail open: quota accounting must not block AI requests.
        _log_event("token_quota.db_error", request_id=getattr(request.state, "request_id", None),
                   tenant_id=tenant_id, error=type(exc).__name__)
        return True


async def _accumulate_tokens(env: Any, tenant_id: str, tokens_used: int) -> None:
    """Post-run token accounting into the "tokens:daily" rate-limit bucket.

    triage_metrics.incident_id is NOT NULL, so question requests (no incident)
    and per-tenant daily token totals are tracked here instead: rate_limit_buckets
    (tenant_id, bucket_key="tokens:daily") with INTEGER count = token sum and
    daily window_start semantics, mirroring _ai_rate_limit. Best-effort: a
    concurrent write can lose an increment (read-modify-write race) —
    acceptable for best-effort enforcement.
    """
    if not tokens_used or tokens_used <= 0:
        return
    try:
        now = _now_ms()
        window_start = _utc_day_window(now)
        row = await env.DB.prepare(
            "SELECT count, window_start FROM rate_limit_buckets WHERE tenant_id = ? AND bucket_key = ?"
        ).bind(tenant_id, TOKEN_BUCKET_KEY).first()
        current = 0
        if row:
            current = int(_row_col(row, "count", 0) or 0)
            if _row_col(row, "window_start", 1) != window_start:
                current = 0  # new daily window resets the accumulator
        await env.DB.prepare(
            "INSERT INTO rate_limit_buckets (id, tenant_id, bucket_key, count, window_start) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_id, bucket_key) DO UPDATE SET count = excluded.count, "
            "window_start = excluded.window_start"
        ).bind(str(uuid.uuid4()), tenant_id, TOKEN_BUCKET_KEY,
               current + int(tokens_used), window_start).run()
    except Exception:
        # Fail open: token accounting must not fail the AI request itself.
        pass


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    rid = _correlation_id(request)
    start = _now_ms()
    env = _env(request)
    api_key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    tenant_id = None
    if env and api_key:
        t = await _tenant_from_api_key(env, api_key)
        tenant_id = t.get("id") if isinstance(t, dict) else None
    # AI inference quota: rate-limit question/triage endpoints per tenant.
    if _is_ai_path(request.url.path) and tenant_id:
        allowed = await _ai_rate_limit(request, env, tenant_id)
        if not allowed:
            return api_error(request, 429, "ai_quota_exceeded", "Daily AI inference quota exceeded")
        tokens_allowed = await _token_quota_check(request, env, tenant_id)
        if not tokens_allowed:
            return api_error(request, 429, "token_quota_exceeded", "Daily AI token quota exceeded",
                             headers={"Retry-After": str(_seconds_until_utc_midnight(_now_ms()))})

    response = await call_next(request)
    latency = _now_ms() - start
    response.headers["X-Request-ID"] = rid
    _REQUEST_LOG.append({
        "ts": start, "request_id": rid, "tenant_id": tenant_id,
        "method": request.method, "path": request.url.path,
        "status": response.status_code, "latency_ms": latency,
    })
    if len(_REQUEST_LOG) > _MAX_REQUEST_LOG:
        del _REQUEST_LOG[: len(_REQUEST_LOG) - _MAX_REQUEST_LOG]
    _log_event("request", request_id=rid, tenant_id=tenant_id, method=request.method,
               path=request.url.path, status=response.status_code, latency_ms=latency)
    return response

# ---------------------------------------------------------------------------
# Cloudflare Workers entry point (ASGI adapter).
# ---------------------------------------------------------------------------


def _request_path(js_request: Any) -> str:
    """Best-effort path extraction from a Workers JS Request. May be ''."""
    try:
        url = getattr(js_request, "url", "")
        if isinstance(url, str) and url:
            return urlparse(url).path
    except Exception:
        pass
    return ""


def _binding_gate_response(missing: List[str]) -> Any:
    """Build a JS Response for the fail-fast 503 gate (runtime only)."""
    try:
        import js  # type: ignore
        from pyodide.ffi import to_js  # type: ignore

        body = json.dumps({"error": {"code": "binding_not_configured",
                                     "message": "Missing required bindings: " + ", ".join(missing),
                                     "status": 503, "request_id": None}})
        init = to_js({"status": 503,
                      "headers": {"Content-Type": "application/json"}})
        return js.Response.new(body, init)
    except Exception:
        return None


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        # Fail fast on missing bindings: never serve app traffic without the
        # full binding set. Health endpoints stay reachable for observability.
        missing = validate_bindings(self.env)
        if missing:
            _log_event("startup.binding_missing", missing=missing)
            path = _request_path(request)
            if not (path == "/health" or path.startswith("/health/")):
                gate = _binding_gate_response(missing)
                if gate is not None:
                    return gate
        if asgi is None:  # defensive: entrypoint invoked outside the runtime
            raise RuntimeError("asgi runtime unavailable")
        return await asgi.fetch(app, request.js_object, self.env)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _env(request: Request) -> Any:
    env = getattr(request.state, "env", None)
    if env is None:
        env = request.scope.get("env")
    return env


async def _tenant_from_api_key(env: Any, api_key: str) -> Optional[Dict[str, Any]]:
    """Validate an API key and return the tenant row."""
    if not api_key or len(api_key) < 8:
        return None
    prefix = api_key[:8]
    try:
        row = await env.DB.prepare(
            "SELECT t.id, t.name, k.key_hash, t.is_active "
            "FROM tenants t JOIN api_keys k ON k.tenant_id = t.id "
            "WHERE k.key_prefix = ? AND k.is_active = 1 AND t.is_active = 1 LIMIT 1"
        ).bind(prefix).first()
    except Exception:
        return None
    if not row:
        return None
    stored_hash = row["key_hash"] if isinstance(row, dict) else row[2]
    if _sha256_hex(api_key) != stored_hash:
        return None
    return {
        "id": row["id"] if isinstance(row, dict) else row[0],
        "name": row["name"] if isinstance(row, dict) else row[1],
    }


async def get_tenant(request: Request,
                     x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """FastAPI dependency: authenticate tenant via X-Api-Key."""
    env = _env(request)
    if env is None:
        raise ApiError(500, "environment_not_configured", "environment not configured")
    if not x_api_key:
        raise ApiError(401, "unauthorized", "missing X-Api-Key header")
    tenant = await _tenant_from_api_key(env, x_api_key)
    if tenant is None:
        raise ApiError(401, "unauthorized", "invalid or inactive API key")
    request.state.tenant = tenant
    return tenant


async def _audit(env: Any, tenant_id: str, actor: str, action: str,
                 resource: str, metadata: Dict[str, Any]) -> None:
    try:
        await env.DB.prepare(
            "INSERT INTO audit_logs (id, tenant_id, actor, action, resource, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        ).bind(str(uuid.uuid4()), tenant_id, actor, action, resource,
               json.dumps(metadata), _now_ms()).run()
    except Exception:
        pass


def _chunk_text(text: str, max_chars: int = 800) -> List[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    chunks: List[str] = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, min(max_chars + 1, len(text)))
        if cut <= 0:
            cut = max_chars
        chunks.append(text[:cut])
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


async def _queue_send(binding: Any, payload: Dict[str, Any]) -> bool:
    """Send an ETL job to the queue, awaiting the binding if it is awaitable."""
    if binding is None:
        return False
    try:
        sent = binding.send(json.dumps(payload))
        if hasattr(sent, "__await__"):
            await sent
        return True
    except Exception:
        return False


async def _dispatch_etl(env: Any, document_id: str, tenant_id: str,
                        content: str, filename: str,
                        version: int = 1, reindex: bool = False) -> Dict[str, Any]:
    """Process a document via ETL.

    ETL_MODE=inline (default) runs chunk/embed/upsert in-request so documents
    are searchable without a queue consumer. ETL_MODE=queue enqueues only.
    Inline failures fall back to the queue (and its DLQ) instead of failing
    the upload request.
    """
    mode = str(getattr(env, "ETL_MODE", "inline") or "inline").lower()
    payload = {
        "job": "etl.process",
        "document_id": document_id,
        "tenant_id": tenant_id,
        "version": version,
    }
    if reindex:
        payload["reindex"] = True

    if mode != "queue":
        try:
            result = await etl.process_document(
                env, document_id, tenant_id, content, filename,
                version=version, reindex=reindex,
            )
        except Exception as exc:
            result = {"status": "dlq", "reason": str(exc)}
        if result.get("status") == "ok":
            return result
        queued = await _queue_send(getattr(env, "ETL_QUEUE", None), payload)
        return {"status": "queued" if queued else "failed", "chunks": result.get("chunks", 0),
                "reason": result.get("reason")}

    queued = await _queue_send(getattr(env, "ETL_QUEUE", None), payload)
    return {"status": "queued" if queued else "failed"}


async def _drop_document_vectors(env: Any, document_id: str, tenant_id: str) -> List[str]:
    """Delete indexed vectors and surface errors before removing D1 source records."""
    chunks = await _db_all(env.DB.prepare(
        "SELECT id, vector_id FROM chunks WHERE document_id = ? AND tenant_id = ?"
    ).bind(document_id, tenant_id))
    vector_ids = [_row_col(c, "vector_id", 1) for c in (chunks or [])
                  if _row_col(c, "vector_id", 1)]
    if vector_ids:
        await env.VECTORIZE_INDEX.delete(ids=vector_ids)
    return vector_ids


def _safe_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _row_col(row: Any, name: str, idx: int) -> Any:
    """Read a column from a D1 row that may be dict-like or tuple-like."""
    if isinstance(row, dict):
        return row.get(name)
    try:
        return row[idx]
    except Exception:
        return None


ALLOWED_SEVERITY = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
ALLOWED_STATUS = {"OPEN", "INVESTIGATING", "RESOLVED"}
STATUS_TRANSITIONS = {
    "OPEN": {"INVESTIGATING", "RESOLVED"},
    "INVESTIGATING": {"RESOLVED"},
    "RESOLVED": set(),
}
# Keep ALLOWED_* sets as the domain reference backing the pydantic Literals above.


async def _tenant_workspaces(env: Any, tenant_id: str) -> List[Dict[str, Any]]:
    """Return workspaces the tenant is a member of, with their role."""
    try:
        rows = await _db_all(env.DB.prepare(
            "SELECT w.id, w.name, w.is_active, wm.role, wm.created_at "
            "FROM workspace_members wm "
            "JOIN workspaces w ON w.id = wm.workspace_id "
            "WHERE wm.tenant_id = ? AND w.is_active = 1 AND wm.role IS NOT NULL "
            "ORDER BY wm.created_at"
        ).bind(tenant_id))
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows or []:
        out.append({
            "id": _row_col(r, "id", 0),
            "name": _row_col(r, "name", 1),
            "is_active": _row_col(r, "is_active", 2),
            "role": _row_col(r, "role", 3),
            "created_at": _row_col(r, "created_at", 4),
        })
    return out


async def _get_workspace_for_tenant(env: Any, tenant_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
    for ws in await _tenant_workspaces(env, tenant_id):
        if ws["id"] == workspace_id:
            return ws
    return None


def _role_rank(role: str) -> int:
    return {"reader": 0, "investigator": 1, "admin": 2}.get(role or "reader", 0)


def require_role(min_role: str = "reader"):
    """FastAPI dependency factory: require the caller's workspace role >= min_role."""

    async def dep(request: Request,
                  tenant: dict = Depends(get_tenant),
                  x_workspace_id: Optional[str] = Header(default=None)):
        env = _env(request)
        if env is None:
            raise ApiError(500, "environment_not_configured", "environment not configured")
        tenant_id = tenant["id"]
        ws_id = x_workspace_id
        if not ws_id:
            workspaces = await _tenant_workspaces(env, tenant_id)
            if not workspaces:
                raise ApiError(403, "forbidden", "no workspace assigned to tenant")
            ws_id = workspaces[0]["id"]
        ws = await _get_workspace_for_tenant(env, tenant_id, ws_id)
        if ws is None:
            raise ApiError(403, "forbidden", "tenant is not a member of workspace")
        if _role_rank(ws.get("role", "reader")) < _role_rank(min_role):
            raise ApiError(403, "forbidden", "insufficient role for workspace")
        request.state.tenant = tenant
        request.state.workspace_id = ws_id
        request.state.workspace_role = ws.get("role", "reader")
        return {"tenant": tenant, "workspace_id": ws_id, "role": ws.get("role", "reader")}
    return dep


async def get_workspace_ctx(request: Request) -> Dict[str, Any]:
    """Read workspace context previously set by require_role."""
    return {
        "tenant": getattr(request.state, "tenant", None),
        "workspace_id": getattr(request.state, "workspace_id", None),
        "role": getattr(request.state, "workspace_role", "reader"),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_HEALTH_BINDINGS = (("db", "DB"), ("vectorize", "VECTORIZE_INDEX"),
                    ("etl_queue", "ETL_QUEUE"), ("etl_dlq", "ETL_DLQ"), ("ai", "ai"))


def _binding_status_map(env: Any) -> Dict[str, str]:
    """Per-dependency status for readiness. Absent env -> all "missing"."""
    status = {key: "missing" for key, _ in _HEALTH_BINDINGS}
    if env is None:
        return status
    for key, attr in _HEALTH_BINDINGS:
        try:
            if getattr(env, attr, None) is not None:
                status[key] = "ok"
        except Exception:
            status[key] = "missing"
    return status


@app.get("/health")
async def health(request: Request):
    env = _env(request)
    checks = _binding_status_map(env)
    client = _azure_client(request)
    if client is not None:
        try:
            status, body = client.health_ready()
            checks["azure_backend"] = "ok" if status == 200 else "error"
        except Exception:
            checks["azure_backend"] = "error"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded",
                         "service": "ai-knowledge-platform",
                         "ts": _now_ms(),
                         "checks": checks})


@app.get("/health/live")
async def health_live(request: Request):
    """Liveness: no dependency checks; if this responds, the isolate is up."""
    client = _azure_client(request)
    azure_ok = True
    if client is not None:
        try:
            status, _ = client.health_live()
            azure_ok = status == 200
        except Exception:
            azure_ok = False
    return JSONResponse({"status": "ok" if azure_ok else "degraded",
                         "service": "ai-knowledge-platform",
                         "ts": _now_ms()})


@app.get("/health/ready")
async def health_ready(request: Request):
    """Readiness: every required binding present + a cheap D1 round-trip."""
    env = _env(request)
    checks = _binding_status_map(env)
    if checks["db"] == "ok":
        try:
            await env.DB.prepare("SELECT 1").first()
        except Exception:
            checks["db"] = "error"
    client = _azure_client(request)
    if client is not None:
        try:
            status, _ = client.health_ready()
            checks["azure_backend"] = "ok" if status == 200 else "error"
        except Exception:
            checks["azure_backend"] = "error"
    degraded = any(v != "ok" for v in checks.values())
    return JSONResponse({"status": "degraded" if degraded else "ok",
                         "service": "ai-knowledge-platform",
                         "ts": _now_ms(),
                         "checks": checks},
                        status_code=503 if degraded else 200)


@app.post("/api/v1/documents")
async def upload_document(request: Request,
                          ctx: dict = Depends(require_role("investigator")),
                          file: UploadFile = File(...),
                          idempotency_key: Optional[str] = Header(default=None)):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]

    if not idempotency_key:
        return api_error(request, 400, "missing_idempotency_key", "Idempotency-Key header is required")

    client = _azure_client(request)
    if client is not None:
        content = await file.read()
        if len(content) > 1024 * 1024:
            return api_error(request, 413, "document_too_large", "Document exceeds 1 MB limit")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return api_error(request, 400, "invalid_encoding", "Only UTF-8 TXT/Markdown is supported")
        status, body = client.create_document(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            filename=file.filename or "document.txt",
            content=text,
            idempotency_key=idempotency_key,
        )
        if status >= 400:
            return api_error(request, status, body.get("code", "azure_error"),
                             body.get("message", "Azure document create failed"))
        return JSONResponse({"status": "uploaded", "document_id": body.get("document_id"),
                             "etl": body.get("etl")}, status_code=202)

    try:
        existing = await env.DB.prepare(
            "SELECT id FROM documents WHERE idempotency_key = ? AND tenant_id = ? LIMIT 1"
        ).bind(idempotency_key, tenant_id).first()
    except Exception:
        existing = None
    if existing:
        did = existing[0] if not isinstance(existing, dict) else existing["id"]
        return JSONResponse({"status": "duplicate", "document_id": did}, status_code=202)

    content = await file.read()
    if len(content) > 1024 * 1024:
        return api_error(request, 413, "document_too_large", "Document exceeds 1 MB limit")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return api_error(request, 400, "invalid_encoding", "Only UTF-8 TXT/Markdown is supported")

    doc_id = str(uuid.uuid4())
    try:
        await env.DB.prepare(
            "INSERT INTO documents (id, tenant_id, filename, content, status, "
            "idempotency_key, uploaded_at, processed_at, error) "
            "VALUES (?, ?, ?, ?, 'uploaded', ?, ?, NULL, NULL)"
        ).bind(doc_id, tenant_id, file.filename or "document.txt", text,
               idempotency_key, _now_ms()).run()
    except Exception as exc:
        return api_error(request, 500, "db_insert_failed", str(exc))

    await _audit(env, tenant_id, tenant_id, "document.upload", doc_id,
                 {"filename": file.filename, "size_bytes": len(content)})

    result = await _dispatch_etl(env, doc_id, tenant_id, text,
                                 file.filename or "document.txt", version=1)

    return JSONResponse({"status": "uploaded", "document_id": doc_id,
                         "etl": result.get("status")}, status_code=202)


@app.get("/api/v1/documents")
async def list_documents(request: Request,
                         tenant: dict = Depends(get_tenant)):
    env = _env(request)
    tenant_id = tenant["id"]
    client = _azure_client(request)
    if client is not None:
        status, body = client.list_documents(tenant_id=tenant_id)
        if status >= 400:
            return api_error(request, status, body.get("code", "azure_error"),
                             body.get("message", "Azure list documents failed"))
        docs = body.get("documents", [])
        return JSONResponse({"documents": docs})
    try:
        rows = await _db_all(env.DB.prepare(
            "SELECT id, filename, status, uploaded_at, processed_at, error "
            "FROM documents WHERE tenant_id = ? ORDER BY uploaded_at DESC LIMIT 50"
        ).bind(tenant_id))
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    docs = []
    for r in rows:
        docs.append({"id": r[0], "filename": r[1], "status": r[2],
                     "uploaded_at": r[3], "processed_at": r[4], "error": r[5]})
    return JSONResponse({"documents": docs})


@app.put("/api/v1/documents/{document_id}")
async def update_document(document_id: str, request: Request,
                          ctx: dict = Depends(require_role("investigator"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    client = _azure_client(request)
    if client is not None:
        try:
            body = await request.json()
        except Exception:
            return api_error(request, 400, "invalid_json", "Request body must be JSON")
        try:
            data = DocumentUpdate.model_validate(body)
        except ValidationError as exc:
            return _validation_error_response(request, exc)
        text = data.content
        filename = data.filename
        if len(text.encode("utf-8")) > 1024 * 1024:
            return api_error(request, 413, "document_too_large", "Document exceeds 1 MB limit")
        status, b = client.update_document(
            document_id=document_id, tenant_id=tenant_id, workspace_id=workspace_id,
            content=text, filename=filename,
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure document update failed"))
        return JSONResponse({"status": "updated", "document_id": document_id,
                             "version": b.get("version"), "etl": b.get("etl")})
    try:
        row = await env.DB.prepare(
            "SELECT id, tenant_id, version FROM documents WHERE id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "document not found")
    if await _get_workspace_for_tenant(env, tenant_id, workspace_id) is None:
        return api_error(request, 403, "forbidden", "document not in workspace")
    try:
        body = await request.json()
    except Exception:
        return api_error(request, 400, "invalid_json", "Request body must be JSON")
    try:
        data = DocumentUpdate.model_validate(body)
    except ValidationError as exc:
        return _validation_error_response(request, exc)
    text = data.content
    filename = data.filename
    if len(text.encode("utf-8")) > 1024 * 1024:
        return api_error(request, 413, "document_too_large", "Document exceeds 1 MB limit")
    current_version = _row_col(row, "version", 2)
    new_version = int(current_version) + 1
    now = _now_ms()
    try:
        await _drop_document_vectors(env, document_id, tenant_id)
    except Exception:
        return api_error(request, 503, "vector_cleanup_failed", "Document index cleanup failed; update was not applied")
    try:
        await env.DB.prepare(
            "UPDATE documents SET content = ?, filename = COALESCE(?, filename), version = ?, "
            "status = 'uploaded', processed_at = NULL, error = NULL, uploaded_at = ? "
            "WHERE id = ? AND tenant_id = ?"
        ).bind(text, filename, new_version, now, document_id, tenant_id).run()
        await env.DB.prepare(
            "DELETE FROM chunks WHERE document_id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id).run()
        await _audit(env, tenant_id, tenant_id, "document.update", document_id,
                     {"version": new_version, "filename": filename})
    except Exception as exc:
        return api_error(request, 500, "db_update_failed", str(exc))
    result = await _dispatch_etl(env, document_id, tenant_id, text,
                                 filename or "document.txt",
                                 version=new_version)
    return JSONResponse({"status": "updated", "document_id": document_id,
                         "version": new_version, "etl": result.get("status")})


@app.delete("/api/v1/documents/{document_id}")
async def delete_document(document_id: str, request: Request,
                          ctx: dict = Depends(require_role("investigator"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    client = _azure_client(request)
    if client is not None:
        status, b = client.delete_document(
            document_id=document_id, tenant_id=tenant_id,
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure document delete failed"))
        return JSONResponse({"status": "deleted", "document_id": document_id})
    try:
        row = await env.DB.prepare(
            "SELECT id, tenant_id FROM documents WHERE id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "document not found")
    if await _get_workspace_for_tenant(env, tenant_id, workspace_id) is None:
        return api_error(request, 403, "forbidden", "document not in workspace")
    try:
        vector_ids = await _drop_document_vectors(env, document_id, tenant_id)
    except Exception:
        return api_error(request, 503, "vector_cleanup_failed", "Document index cleanup failed; delete was not applied")
    try:
        await env.DB.prepare(
            "DELETE FROM chunks WHERE document_id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id).run()
        await env.DB.prepare(
            "DELETE FROM documents WHERE id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id).run()
        await _audit(env, tenant_id, tenant_id, "document.delete", document_id,
                     {"vector_ids": vector_ids})
    except Exception as exc:
        return api_error(request, 500, "db_delete_failed", str(exc))
    return JSONResponse({"status": "deleted", "document_id": document_id})


@app.post("/api/v1/documents/{document_id}/reindex")
async def reindex_document(document_id: str, request: Request,
                           ctx: dict = Depends(require_role("investigator"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    client = _azure_client(request)
    if client is not None:
        status, b = client.reindex_document(
            document_id=document_id, tenant_id=tenant_id, workspace_id=workspace_id,
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure document reindex failed"))
        return JSONResponse({"status": "reindexed", "document_id": document_id,
                             "etl": b.get("etl")})
    try:
        row = await env.DB.prepare(
            "SELECT id, tenant_id, content, filename, version FROM documents WHERE id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "document not found")
    if await _get_workspace_for_tenant(env, tenant_id, workspace_id) is None:
        return api_error(request, 403, "forbidden", "document not in workspace")
    try:
        await _drop_document_vectors(env, document_id, tenant_id)
    except Exception:
        return api_error(request, 503, "vector_cleanup_failed", "Document index cleanup failed; reindex was not applied")
    try:
        await env.DB.prepare(
            "DELETE FROM chunks WHERE document_id = ? AND tenant_id = ?"
        ).bind(document_id, tenant_id).run()
        current_version = _row_col(row, "version", 4)
        await _audit(env, tenant_id, tenant_id, "document.reindex", document_id,
                     {"version": current_version})
    except Exception as exc:
        return api_error(request, 500, "db_delete_failed", str(exc))
    result = await _dispatch_etl(
        env, document_id, tenant_id,
        _row_col(row, "content", 2) or "",
        _row_col(row, "filename", 3) or "document.txt",
        version=current_version, reindex=True,
    )
    return JSONResponse({"status": "reindexed", "document_id": document_id,
                         "etl": result.get("status")})


@app.get("/api/v1/workspaces")
async def list_workspaces(request: Request, ctx: dict = Depends(require_role("reader"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    client = _azure_client(request)
    if client is not None:
        status, body = client.list_workspaces(tenant_id=tenant_id)
        if status >= 400:
            return api_error(request, status, body.get("code", "azure_error"),
                             body.get("message", "Azure list workspaces failed"))
        return JSONResponse({"workspaces": body.get("workspaces", [])})
    workspaces = await _tenant_workspaces(env, tenant_id)
    return JSONResponse({"workspaces": workspaces})


@app.post("/api/v1/incidents")
async def create_incident(request: Request,
                          ctx: dict = Depends(require_role("investigator")),
                          idempotency_key: Optional[str] = Header(default=None)):
    env = _env(request)
    tenant = ctx["tenant"]
    tenant_id = tenant["id"]
    workspace_id = ctx["workspace_id"]
    client = _azure_client(request)
    if client is not None:
        try:
            body = await request.json()
        except Exception:
            return api_error(request, 400, "invalid_json", "Request body must be JSON")
        try:
            data = IncidentCreate.model_validate(body)
        except ValidationError as exc:
            return _validation_error_response(request, exc)
        if not idempotency_key:
            return api_error(request, 400, "missing_idempotency_key", "Idempotency-Key header is required")
        status, b = client.create_incident(
            tenant_id=tenant_id, workspace_id=workspace_id,
            title=data.title, severity=data.severity, service=data.service,
            environment=data.environment, idempotency_key=idempotency_key,
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure incident create failed"))
        return JSONResponse({"status": "created", "incident_id": b.get("incident_id")},
                            status_code=201)
    if not idempotency_key:
        return api_error(request, 400, "missing_idempotency_key", "Idempotency-Key header is required")
    try:
        body = await request.json()
    except Exception:
        return api_error(request, 400, "invalid_json", "Request body must be JSON")
    try:
        data = IncidentCreate.model_validate(body)
    except ValidationError as exc:
        return _validation_error_response(request, exc)
    # Payload dict is built from the validated model so the idempotency
    # payload_hash contract stays identical (strip handled by the model).
    payload = {"title": data.title, "severity": data.severity,
               "service": data.service, "environment": data.environment}
    title, severity, service, environment = data.title, data.severity, data.service, data.environment
    payload_hash = _sha256_hex(json.dumps(payload, sort_keys=True))
    try:
        existing = await env.DB.prepare(
            "SELECT id, payload_hash FROM incidents WHERE idempotency_key = ? AND tenant_id = ? LIMIT 1"
        ).bind(idempotency_key, tenant_id).first()
    except Exception:
        existing = None
    if existing:
        eid = existing[0] if not isinstance(existing, dict) else existing["id"]
        ehash = existing[1] if not isinstance(existing, dict) else existing["payload_hash"]
        if ehash == payload_hash:
            return JSONResponse({"status": "duplicate", "incident_id": eid}, status_code=202)
        return api_error(request, 409, "idempotency_conflict", "Idempotency-Key reused with different payload")
    incident_id = str(uuid.uuid4())
    now = _now_ms()
    try:
        await env.DB.prepare(
            "INSERT INTO incidents (id, workspace_id, tenant_id, title, severity, service, environment, "
            "status, version, payload_hash, idempotency_key, created_at, updated_at, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', 1, ?, ?, ?, ?, NULL)"
        ).bind(incident_id, workspace_id, tenant_id, title, severity, service, environment,
               payload_hash, idempotency_key, now, now).run()
        await env.DB.prepare(
            "INSERT INTO incident_events (id, incident_id, tenant_id, event_type, severity, service, "
            "environment, timestamp, logs, deploy_context, created_at) "
            "VALUES (?, ?, ?, 'created', ?, ?, ?, ?, NULL, NULL, ?)"
        ).bind(str(uuid.uuid4()), incident_id, tenant_id, severity, service, environment, now, now).run()
        await _audit(env, tenant_id, tenant_id, "incident.create", incident_id,
                     {"severity": severity, "service": service, "environment": environment})
    except Exception as exc:
        return api_error(request, 500, "db_insert_failed", str(exc))
    try:
        await env.ETL_QUEUE.send(json.dumps({"job": "incident.created", "incident_id": incident_id, "tenant_id": tenant_id}))
    except Exception:
        pass
    return JSONResponse({"status": "created", "incident_id": incident_id}, status_code=201)


@app.get("/api/v1/incidents/{incident_id}")
async def get_incident(incident_id: str, request: Request, ctx: dict = Depends(require_role("reader"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    try:
        row = await env.DB.prepare(
            "SELECT id, workspace_id, tenant_id, title, severity, service, environment, status, version, "
            "payload_hash, created_at, updated_at, resolved_at FROM incidents WHERE id = ? AND tenant_id = ?"
        ).bind(incident_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "incident not found")
    if _row_col(row, "workspace_id", 1) != workspace_id:
        return api_error(request, 403, "forbidden", "incident not in workspace")
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
    }
    return JSONResponse({"incident": incident})


@app.patch("/api/v1/incidents/{incident_id}")
async def update_incident(incident_id: str, request: Request,
                          ctx: dict = Depends(require_role("investigator")),
                          if_match: Optional[str] = Header(default=None)):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    client = _azure_client(request)
    if client is not None:
        try:
            body = await request.json()
        except Exception:
            return api_error(request, 400, "invalid_json", "Request body must be JSON")
        new_status = (body or {}).get("status")
        if new_status is None:
            return api_error(request, 400, "missing_status", "status field is required")
        new_status = str(new_status).strip().upper()
        status, b = client.patch_incident(
            incident_id=incident_id, tenant_id=tenant_id, workspace_id=workspace_id,
            status=new_status, if_match=int(if_match) if if_match else None,
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure incident update failed"))
        return JSONResponse({"status": "updated", "incident_id": incident_id,
                             "version": b.get("version"), "incident_status": b.get("incident_status")})
    try:
        row = await env.DB.prepare(
            "SELECT id, workspace_id, tenant_id, title, severity, service, environment, status, version, "
            "payload_hash, created_at, updated_at, resolved_at FROM incidents WHERE id = ? AND tenant_id = ?"
        ).bind(incident_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "incident not found")
    if _row_col(row, "workspace_id", 1) != workspace_id:
        return api_error(request, 403, "forbidden", "incident not in workspace")
    current_version = _row_col(row, "version", 8)
    current_status = _row_col(row, "status", 7)
    if if_match is not None:
        try:
            if int(if_match) != int(current_version):
                return api_error(request, 409, "conflict", "stale version")
        except Exception:
            return api_error(request, 409, "conflict", "stale version")
    try:
        body = await request.json()
    except Exception:
        return api_error(request, 400, "invalid_json", "Request body must be JSON")
    try:
        data = IncidentPatch.model_validate(body)
    except ValidationError as exc:
        return _validation_error_response(request, exc)
    new_status = data.status
    if new_status == current_status:
        return api_error(request, 409, "no_change", "status already set")
    if new_status not in STATUS_TRANSITIONS.get(current_status, set()):
        return api_error(request, 409, "invalid_transition", f"cannot transition {current_status} -> {new_status}")
    now = _now_ms()
    resolved_at = _row_col(row, "resolved_at", 12)
    if new_status == "RESOLVED" and resolved_at is None:
        resolved_at = now
    new_version = int(current_version) + 1
    try:
        await env.DB.prepare(
            "UPDATE incidents SET status = ?, version = ?, updated_at = ?, resolved_at = ? "
            "WHERE id = ? AND tenant_id = ? AND version = ?"
        ).bind(new_status, new_version, now, resolved_at, incident_id, tenant_id, current_version).run()
        await env.DB.prepare(
            "INSERT INTO incident_events (id, incident_id, tenant_id, event_type, severity, service, "
            "environment, timestamp, logs, deploy_context, created_at) "
            "VALUES (?, ?, ?, 'status_changed', NULL, NULL, NULL, ?, NULL, NULL, ?)"
        ).bind(str(uuid.uuid4()), incident_id, tenant_id, now, now).run()
        await _audit(env, tenant_id, tenant_id, "incident.update", incident_id,
                     {"from": current_status, "to": new_status, "version": new_version})
    except Exception as exc:
        return api_error(request, 500, "db_update_failed", str(exc))
    return JSONResponse({"status": "updated", "incident_id": incident_id, "version": new_version,
                         "incident_status": new_status})


@app.post("/api/v1/incidents/{incident_id}/events")
async def add_incident_event(incident_id: str, request: Request,
                             ctx: dict = Depends(require_role("investigator"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    client = _azure_client(request)
    if client is not None:
        try:
            body = await request.json()
        except Exception:
            return api_error(request, 400, "invalid_json", "Request body must be JSON")
        status, b = client.add_incident_event(
            incident_id=incident_id, tenant_id=tenant_id, workspace_id=workspace_id,
            event_type=(body or {}).get("event_type", "event_added"),
            severity=(body or {}).get("severity"),
            service=(body or {}).get("service"),
            environment=(body or {}).get("environment"),
            timestamp=(body or {}).get("timestamp"),
            logs=(body or {}).get("logs"),
            deploy_context=(body or {}).get("deploy_context"),
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure incident event failed"))
        return JSONResponse({"status": "event_added", "incident_id": incident_id},
                            status_code=201)
    try:
        row = await env.DB.prepare("SELECT id, workspace_id FROM incidents WHERE id = ? AND tenant_id = ?").bind(incident_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "incident not found")
    if _row_col(row, "workspace_id", 1) != workspace_id:
        return api_error(request, 403, "forbidden", "incident not in workspace")
    try:
        body = await request.json()
    except Exception:
        return api_error(request, 400, "invalid_json", "Request body must be JSON")
    event_type = (body or {}).get("event_type", "event_added").strip()
    severity = (body or {}).get("severity")
    service = (body or {}).get("service")
    environment = (body or {}).get("environment")
    timestamp = (body or {}).get("timestamp")
    logs = (body or {}).get("logs")
    deploy_context = (body or {}).get("deploy_context")
    if timestamp is None:
        timestamp = _now_ms()
    try:
        timestamp = int(timestamp)
    except Exception:
        return api_error(request, 400, "invalid_timestamp", "timestamp must be an integer")
    now = _now_ms()
    try:
        await env.DB.prepare(
            "INSERT INTO incident_events (id, incident_id, tenant_id, event_type, severity, service, "
            "environment, timestamp, logs, deploy_context, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        ).bind(str(uuid.uuid4()), incident_id, tenant_id, event_type, severity, service, environment,
               timestamp, logs, deploy_context, now).run()
        await env.DB.prepare("UPDATE incidents SET updated_at = ? WHERE id = ? AND tenant_id = ?").bind(now, incident_id, tenant_id).run()
        await _audit(env, tenant_id, tenant_id, "incident.event_added", incident_id,
                     {"event_type": event_type, "timestamp": timestamp})
    except Exception as exc:
        return api_error(request, 500, "db_insert_failed", str(exc))
    return JSONResponse({"status": "event_added", "incident_id": incident_id}, status_code=201)


@app.get("/api/v1/incidents/{incident_id}/timeline")
async def get_incident_timeline(incident_id: str, request: Request, ctx: dict = Depends(require_role("reader"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    client = _azure_client(request)
    if client is not None:
        status, b = client.get_incident_timeline(
            incident_id=incident_id, tenant_id=tenant_id,
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure incident timeline failed"))
        return JSONResponse(b)
    try:
        row = await env.DB.prepare("SELECT id, workspace_id FROM incidents WHERE id = ? AND tenant_id = ?").bind(incident_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "incident not found")
    if _row_col(row, "workspace_id", 1) != workspace_id:
        return api_error(request, 403, "forbidden", "incident not in workspace")
    try:
        rows = await _db_all(env.DB.prepare(
            "SELECT id, event_type, severity, service, environment, timestamp, logs, deploy_context, created_at "
            "FROM incident_events WHERE incident_id = ? ORDER BY created_at ASC, id ASC"
        ).bind(incident_id))
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    events = []
    for r in rows or []:
        events.append({
            "id": _row_col(r, "id", 0),
            "event_type": _row_col(r, "event_type", 1),
            "severity": _row_col(r, "severity", 2),
            "service": _row_col(r, "service", 3),
            "environment": _row_col(r, "environment", 4),
            "timestamp": _row_col(r, "timestamp", 5),
            "logs": _row_col(r, "logs", 6),
            "deploy_context": _row_col(r, "deploy_context", 7),
            "created_at": _row_col(r, "created_at", 8),
        })
    return JSONResponse({"incident_id": incident_id, "events": events})


@app.get("/api/v1/metrics/quota")
async def metrics_quota(request: Request, ctx: dict = Depends(require_role("reader"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    client = _azure_client(request)
    if client is not None:
        status, b = client.metrics_quota(tenant_id=tenant_id)
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure metrics quota failed"))
        return JSONResponse(b)
    buckets: List[Dict[str, Any]] = []
    ai_daily_count = 0
    tokens_daily = 0
    try:
        rows = await _db_all(env.DB.prepare(
            "SELECT bucket_key, count, window_start FROM rate_limit_buckets WHERE tenant_id = ?"
        ).bind(tenant_id))
        today_start = _utc_day_window(_now_ms())
        for r in rows or []:
            bucket_key = r[0] if not isinstance(r, dict) else r.get("bucket_key")
            count = r[1] if not isinstance(r, dict) else r.get("count")
            window_start = r[2] if not isinstance(r, dict) else r.get("window_start")
            buckets.append({
                "bucket_key": bucket_key,
                "count": count,
                "window_start": window_start,
            })
            if bucket_key == AI_BUCKET_KEY:
                ai_daily_count = int(count or 0)
            if bucket_key == TOKEN_BUCKET_KEY:
                # Stale windows (previous UTC day) do not count against today.
                tokens_daily = int(count or 0) if window_start == today_start else 0
    except Exception:
        pass
    return JSONResponse({
        "tenant_id": tenant_id,
        "ai_daily_count": ai_daily_count,
        "daily_ai_limit": AI_DAILY_LIMIT,
        "tokens_daily": tokens_daily,
        "daily_token_limit": TOKEN_DAILY_LIMIT,
        "buckets": buckets,
    })


TRIAGE_SYSTEM_PROMPT = (
    "You are the grounded triage analyst for an incident management platform — "
    "a strict, read-only triage assistant.\n"
    "Hard rules — follow every rule without exception:\n"
    "1. Use ONLY the numbered context items [1..N] provided in the user message; "
    "never rely on outside knowledge.\n"
    "2. Every claim in the summary must cite the context items it rests on, using [n] "
    "citation markers.\n"
    "3. Classify each hypothesis as confirmed or unconfirmed, and list the evidence "
    "(context item numbers) that supports it.\n"
    "4. If the provided evidence is insufficient, set summary to an explicit insufficiency "
    "statement (for example: 'Insufficient evidence in the provided context to determine "
    "the cause.') and return an empty hypotheses list.\n"
    "5. READ-ONLY recommendations only: refuse restart, deploy, rollback, or config-change "
    "suggestions; propose read-only checks (logs, describe, metrics) instead.\n"
    "6. Answer in the same language as the incident title/logs.\n"
    "7. Output STRICT JSON only: "
    '{"summary": str, "hypotheses": [{"text": str, "confirmed": bool, "evidence": [n,...]}], '
    '"read_only_checks": [str,...]} — no markdown fences and no text before or after the JSON.'
)

QUESTION_SYSTEM_PROMPT = (
    "You answer questions strictly from the numbered context provided in the user message. "
    "Rules: (1) use only the context items [1..N], never outside knowledge; "
    "(2) cite every claim with [n] markers matching the context item numbers; "
    "(3) if the context does not contain the answer, explicitly state that the provided "
    "documents are insufficient (abstain) instead of guessing; "
    "(4) answer in the same language as the question; "
    "(5) be concise — a short cited answer beats a long one."
)


async def _ai_run_with_retry(env: Any, model: str, inputs: Dict[str, Any],
                             attempts: int = 2) -> Optional[Any]:
    """Run a Workers AI model with one retry; return None when unavailable.

    One retry covers transient timeouts/5xx from the inference gateway. When
    all attempts fail the caller must degrade to the deterministic extractive
    fallback (_ai_unavailable_fallback) instead of erroring out.
    """
    for attempt in range(max(1, attempts)):
        try:
            return await env.ai.run(model, inputs)
        except Exception as exc:
            _log_event("ai.unavailable", model=model, attempt=attempt + 1,
                       attempts=attempts, error=type(exc).__name__)
    return None


def _ai_unavailable_fallback(context_chunks: List[Dict[str, Any]], topic: str,
                             kind: str = "question") -> str:
    """Deterministic EXTRACTIVE fallback when Workers AI is unavailable.

    No LLM involved: the answer is assembled from the retrieved context only
    (top 2-3 chunks, trimmed) with [n] citation markers so every statement
    stays traceable to a source document.
    """
    prefix = "(fallback khong LLM)" if kind == "triage" else "(fallback without LLM)"
    parts: List[str] = []
    for idx, ch in enumerate(context_chunks[:3], start=1):
        content = re.sub(r"\s+", " ", ch.get("content") or "").strip()
        if content:
            parts.append(f"[{idx}] {content[:300]}")
    if parts:
        body = f"Relevant context for '{topic}': " + " ".join(parts)
    else:
        body = (f"No matching context retrieved for '{topic}'. "
                "Run the read-only checks and retry when AI is available.")
    return f"{prefix} {body}"


def _parse_triage_json(answer_text: str) -> Optional[Dict[str, Any]]:
    """Parse the strict-JSON triage answer. Returns None on any parse failure.

    Tolerates markdown code fences and stray prose: tries the first fenced
    block, then the outermost {...} span. The caller falls back to line
    parsing when this returns None.
    """
    if not answer_text or not answer_text.strip():
        return None
    text = answer_text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None

READ_ONLY_CHECKS = {
    "oomkilled": ["kubectl logs <pod> --previous", "kubectl describe pod <pod>", "kubectl top pod <pod>"],
    "crashloopbackoff": ["kubectl logs <pod> --previous", "kubectl describe pod <pod>", "kubectl get events"],
    "imagepullbackoff": ["kubectl describe pod <pod>", "kubectl get events", "kubectl logs <pod>"],
    "readiness": ["kubectl describe pod <pod>", "kubectl logs <pod>", "kubectl get svc <service>"],
    "database_timeout": ["kubectl logs <pod>", "kubectl get svc <db-service>", "kubectl describe pod <pod>"],
    "queue_backlog": ["kubectl get events", "kubectl describe <queue-resource>", "kubectl logs <pod>"],
}


def _read_only_checks(service: str, logs_hint: str) -> List[str]:
    key = None
    text = f"{service} {logs_hint}".lower()
    for k in READ_ONLY_CHECKS:
        if k in text:
            key = k
            break
    checks = READ_ONLY_CHECKS.get(key, READ_ONLY_CHECKS["oomkilled"])
    return [c.replace("<pod>", service).replace("<service>", service).replace("<db-service>", service) for c in checks]


async def _record_triage_metric(env: Any, tenant_id: str, incident_id: str, status: str,
                                 citations: int, tokens_used: int, latency_ms: int) -> None:
    try:
        await env.DB.prepare(
            "INSERT INTO triage_metrics (id, tenant_id, incident_id, status, citations, tokens_used, latency_ms, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        ).bind(str(uuid.uuid4()), tenant_id, incident_id, status, citations, tokens_used, latency_ms, _now_ms()).run()
    except Exception:
        pass


async def _store_triage_report(env: Any, incident_id: str, tenant_id: str, status: str,
                                summary: str, hypotheses: List[Dict[str, Any]],
                                evidence: List[Dict[str, Any]], similar: List[str],
                                read_only_checks: List[str], citations: List[Dict[str, Any]]) -> None:
    await env.DB.prepare(
        "INSERT INTO triage_reports (id, incident_id, tenant_id, status, summary, hypotheses, "
        "evidence, similar_incidents, read_only_checks, citations, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ).bind(str(uuid.uuid4()), incident_id, tenant_id, status, summary,
           json.dumps(hypotheses), json.dumps(evidence), json.dumps(similar),
           json.dumps(read_only_checks), json.dumps(citations), _now_ms()).run()


async def _hybrid_search(env: Any, tenant_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Hybrid retrieval: Vectorize semantic + D1 FTS5 keyword, merged and re-ranked.
    Both paths are tenant-isolated. Failures in one path do not fail the other.
    """
    results: List[Dict[str, Any]] = []
    seen: set = set()

    # 1. Vectorize semantic search (tenant-isolated via metadata filter).
    question_vector: Optional[List[float]] = None
    try:
        embed = await env.ai.run("@cf/qwen/qwen3-embedding-0.6b", {"text": [query]})
        vectors = embed.get("vectors") or embed.get("data") or []
        question_vector = vectors[0] if vectors else None
    except Exception:
        question_vector = None
    if question_vector:
        try:
            raw = await env.VECTORIZE_INDEX.query(
                vector=question_vector, topK=top_k, returnMetadata=True,
                filter={"tenant_id": tenant_id},
            )
            matches = raw.get("matches", []) if isinstance(raw, dict) else []
            for m in matches:
                meta = m.get("metadata", {}) or {}
                doc_id = meta.get("document_id")
                key = f"vec:{doc_id}:{meta.get('chunk_id')}"
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "document_id": doc_id,
                    "chunk_id": meta.get("chunk_id"),
                    "content": meta.get("content", ""),
                    "score": float(m.get("score", 0) or 0),
                    "version": meta.get("version", 1),
                    "source": "vector",
                })
        except Exception:
            pass

    # 2. D1 FTS5 keyword search (tenant-isolated via join to documents).
    try:
        fts_rows = await _db_all(env.DB.prepare(
            "SELECT d.id, d.filename, d.content, bm25(documents_fts) AS rank "
            "FROM documents_fts JOIN documents d ON d.rowid = documents_fts.rowid "
            "WHERE documents_fts MATCH ? AND d.tenant_id = ? ORDER BY rank LIMIT ?"
        ).bind(query, tenant_id, top_k))
        for r in fts_rows or []:
            doc_id = r[0] if not isinstance(r, dict) else r.get("id")
            key = f"fts:{doc_id}"
            if key in seen:
                continue
            seen.add(key)
            rank = r[3] if not isinstance(r, dict) else r.get("rank", 0)
            results.append({
                "document_id": doc_id,
                "chunk_id": None,
                "content": r[2] if not isinstance(r, dict) else r.get("content"),
                "score": 1.0 / (1.0 + float(rank or 0)),
                "version": 1,
                "source": "keyword",
            })
    except Exception:
        pass

    results.sort(key=lambda x: (0 if x["source"] == "vector" else 1, -x["score"]))
    return results[:top_k]


async def _similar_incidents(env: Any, tenant_id: str, incident_id: str,
                       service: str, limit: int = 5) -> List[str]:
    try:
        rows = await _db_all(env.DB.prepare(
            "SELECT id FROM incidents WHERE tenant_id = ? AND service = ? AND id != ? "
            "ORDER BY created_at DESC LIMIT ?"
        ).bind(tenant_id, service, incident_id, limit))
    except Exception:
        return []
    out: List[str] = []
    for r in rows or []:
        out.append(r[0] if not isinstance(r, dict) else r.get("id"))
    return out


@app.post("/api/v1/incidents/{incident_id}/triage")
async def triage_incident(incident_id: str, request: Request,
                          ctx: dict = Depends(require_role("investigator"))):
    """Grounded incident triage. Read-only: never modifies production."""
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    workspace_id = ctx["workspace_id"]
    client = _azure_client(request)
    if client is not None:
        status, b = client.triage_incident(
            incident_id=incident_id, tenant_id=tenant_id, workspace_id=workspace_id,
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure triage failed"))
        return JSONResponse(b)
    try:
        row = await env.DB.prepare(
            "SELECT id, workspace_id, tenant_id, title, severity, service, environment, status, version, "
            "payload_hash, created_at, updated_at, resolved_at FROM incidents WHERE id = ? AND tenant_id = ?"
        ).bind(incident_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "incident not found")
    if _row_col(row, "workspace_id", 1) != workspace_id:
        return api_error(request, 403, "forbidden", "incident not in workspace")
    title = _row_col(row, "title", 3)
    severity = _row_col(row, "severity", 4)
    service = _row_col(row, "service", 5)
    environment = _row_col(row, "environment", 6)

    # Latest event logs to enrich the search query.
    logs_hint = ""
    try:
        evs = await _db_all(env.DB.prepare(
            "SELECT logs, timestamp FROM incident_events WHERE incident_id = ? ORDER BY created_at DESC LIMIT 3"
        ).bind(incident_id))
        logs_hint = " ".join(
            (r[0] if not isinstance(r, dict) else r.get("logs", "") or "")
            for r in (evs or []) if (r[0] if not isinstance(r, dict) else r.get("logs"))
        )
    except Exception:
        logs_hint = ""
    query = f"{title} {service} {environment} {logs_hint}".strip()

    # Hybrid retrieval.
    context_chunks = await _hybrid_search(env, tenant_id, query)

    citations: List[Dict[str, Any]] = []
    context_parts: List[str] = []
    evidence: List[Dict[str, Any]] = []
    for idx, ch in enumerate(context_chunks, start=1):
        context_parts.append(f"[{idx}] {ch['content']}")
        citations.append({
            "id": idx, "document_id": ch["document_id"],
            "chunk_id": ch["chunk_id"], "score": ch["score"],
        })
        evidence.append({
            "document_id": ch["document_id"],
            "version": ch["version"],
            "section": ch["chunk_id"] or "document",
            "quote": ch["content"][:200],
        })
    context = "\n".join(context_parts)

    # Read-only enforcement: this handler performs no writes to production tables.
    read_only_checks = _read_only_checks(service, logs_hint)

    if not context_chunks:
        similar = await _similar_incidents(env, tenant_id, incident_id, service)
        try:
            await _store_triage_report(env, incident_id, tenant_id, "insufficient_evidence",
                                       "Không có bằng chứng từ tài liệu/kiến thức nào khớp với sự cố này.",
                                       [], [], similar, read_only_checks, [])
        except Exception as exc:
            _log_event("triage.report_persist_failed", request_id=getattr(request.state, "request_id", None),
                       incident_id=incident_id, error=type(exc).__name__)
            return api_error(request, 503, "report_persist_failed", "Triage report could not be persisted")
        await _record_triage_metric(env, tenant_id, incident_id, "insufficient_evidence", 0, 0, 0)
        await _audit(env, tenant_id, tenant_id, "incident.triage", incident_id,
                     {"status": "insufficient_evidence", "reason": "no_context"})
        return JSONResponse({
            "status": "insufficient_evidence",
            "incident_id": incident_id,
            "summary": "Không có bằng chứng từ tài liệu/kiến thức nào khớp với sự cố này.",
            "hypotheses": [],
            "evidence": [],
            "similar_incidents": similar,
            "read_only_checks": read_only_checks,
            "citations": [],
        })

    user_prompt = (f"Context:\n{context}\n\nIncident: service={service}, severity={severity}, "
                   f"environment={environment}, title={title}.\n"
                   f"Produce triage JSON in the same language as the incident.")

    # LLM answer (retry once; deterministic extractive fallback if unavailable).
    llm = await _ai_run_with_retry(env, "@cf/openai/gpt-oss-20b", {
        "messages": [
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 512,
    }, attempts=2)
    answer_text = ""
    tokens_used = 0
    ai_unavailable = llm is None
    if llm is not None:
        answer_text = llm.get("response", "") if isinstance(llm, dict) else str(llm)
        usage = llm.get("usage", {}) if isinstance(llm, dict) else {}
        tokens_used = int(usage.get("total_tokens", 0) or 0)

    # Strict-JSON path first; line-parsing fallback mirrors the legacy behavior.
    hypotheses: List[Dict[str, Any]] = []
    parsed = _parse_triage_json(answer_text) if not ai_unavailable else None
    if parsed is not None:
        summary = str(parsed.get("summary", "")).strip() or answer_text.strip()
        for h in parsed.get("hypotheses", []) or []:
            if isinstance(h, dict) and h.get("text"):
                # Keep the API contract {text, confirmed}; the model's per-item
                # evidence key ([n] ids) is dropped here — the response-level
                # `evidence` list carries the full grounding.
                hypotheses.append({"text": str(h["text"]),
                                   "confirmed": bool(h.get("confirmed", False))})
        model_checks = [str(c) for c in (parsed.get("read_only_checks") or []) if c]
        if model_checks:
            read_only_checks = model_checks
    else:
        summary = answer_text.strip() or "Có bằng chứng nhưng không thể tổng hợp tự động."
        for line in answer_text.splitlines():
            line = line.strip()
            if line.lower().startswith("hypothesis:"):
                hyp_text = line.split(":", 1)[1].strip()
                confirmed = "confirmed" in hyp_text.lower() or "yes" in hyp_text.lower()
                hypotheses.append({"text": hyp_text, "confirmed": bool(confirmed)})
        if not hypotheses:
            hypotheses = [{"text": summary, "confirmed": False}]
    if ai_unavailable:
        # Deterministic extractive fallback: summary built from retrieved
        # context with [n] citations, no hypotheses, status stays "ok".
        summary = _ai_unavailable_fallback(context_chunks, title, kind="triage")
        hypotheses = []

    similar = await _similar_incidents(env, tenant_id, incident_id, service)
    try:
        await _store_triage_report(env, incident_id, tenant_id, "ok", summary, hypotheses,
                                   evidence, similar, read_only_checks, citations)
    except Exception as exc:
        _log_event("triage.report_persist_failed", request_id=getattr(request.state, "request_id", None),
                   incident_id=incident_id, error=type(exc).__name__)
        return api_error(request, 503, "report_persist_failed", "Triage report could not be persisted")
    await _record_triage_metric(env, tenant_id, incident_id, "ok", len(citations), tokens_used, 0)
    # Post-run token accounting for the daily quota bucket (best-effort).
    await _accumulate_tokens(env, tenant_id, tokens_used)
    await _audit(env, tenant_id, tenant_id, "incident.triage", incident_id,
                 {"status": "ok", "tokens": tokens_used, "citations": [c["id"] for c in citations],
                  "ai": "unavailable" if ai_unavailable else "ok"})

    response_body: Dict[str, Any] = {
        "status": "ok",
        "incident_id": incident_id,
        "summary": summary,
        "hypotheses": hypotheses,
        "evidence": evidence,
        "similar_incidents": similar,
        "read_only_checks": read_only_checks,
        "citations": citations,
        "tokens_used": tokens_used,
    }
    if ai_unavailable:
        response_body["ai"] = "unavailable"
    return JSONResponse(response_body)


@app.get("/api/v1/incidents/{incident_id}/report")
async def get_incident_report(incident_id: str, request: Request,
                              ctx: dict = Depends(require_role("reader"))):
    env = _env(request)
    tenant_id = ctx["tenant"]["id"]
    client = _azure_client(request)
    if client is not None:
        status, b = client.get_incident_report(
            incident_id=incident_id, tenant_id=tenant_id,
        )
        if status == 404:
            return api_error(request, 404, "not_found", "no triage report for incident")
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure incident report failed"))
        return JSONResponse(b)
    try:
        row = await env.DB.prepare(
            "SELECT id, status, summary, hypotheses, evidence, similar_incidents, read_only_checks, citations, created_at "
            "FROM triage_reports WHERE incident_id = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 1"
        ).bind(incident_id, tenant_id).first()
    except Exception as exc:
        return api_error(request, 500, "db_query_failed", str(exc))
    if not row:
        return api_error(request, 404, "not_found", "no triage report for incident")
    r = row
    return JSONResponse({
        "report_id": _row_col(r, "id", 0),
        "incident_id": incident_id,
        "status": _row_col(r, "status", 1),
        "summary": _row_col(r, "summary", 2),
        "hypotheses": _safe_json(_row_col(r, "hypotheses", 3)),
        "evidence": _safe_json(_row_col(r, "evidence", 4)),
        "similar_incidents": _safe_json(_row_col(r, "similar_incidents", 5)),
        "read_only_checks": _safe_json(_row_col(r, "read_only_checks", 6)),
        "citations": _safe_json(_row_col(r, "citations", 7)),
        "created_at": _row_col(r, "created_at", 8),
    })


@app.post("/api/v1/question")
async def ask_question(request: Request,
                       tenant: dict = Depends(get_tenant),
                       idempotency_key: Optional[str] = Header(default=None)):
    env = _env(request)
    tenant_id = tenant["id"]
    client = _azure_client(request)
    if client is not None:
        if not idempotency_key:
            return api_error(request, 400, "missing_idempotency_key", "Idempotency-Key header is required")
        try:
            body = await request.json()
        except Exception:
            return api_error(request, 400, "invalid_json", "Request body must be JSON")
        try:
            data = QuestionRequest.model_validate(body)
        except ValidationError as exc:
            return _validation_error_response(request, exc)
        status, b = client.ask_question(
            tenant_id=tenant_id, question=data.question, idempotency_key=idempotency_key,
        )
        if status >= 400:
            return api_error(request, status, b.get("code", "azure_error"),
                             b.get("message", "Azure question failed"))
        return JSONResponse(b)
    if not idempotency_key:
        return api_error(request, 400, "missing_idempotency_key", "Idempotency-Key header is required")

    try:
        body = await request.json()
    except Exception:
        return api_error(request, 400, "invalid_json", "Request body must be JSON")

    try:
        data = QuestionRequest.model_validate(body)
    except ValidationError as exc:
        return _validation_error_response(request, exc)
    question = data.question

    try:
        existing = await env.DB.prepare(
            "SELECT id FROM audit_logs WHERE tenant_id = ? AND action = 'question' "
            "AND metadata LIKE ? ORDER BY created_at DESC LIMIT 1"
        ).bind(tenant_id, f"%{idempotency_key}%").first()
    except Exception:
        existing = None
    if existing:
        return JSONResponse({"status": "duplicate"}, status_code=202)

    # 1. Embed the question.
    question_vector: Optional[List[float]] = None
    try:
        embed = await env.ai.run("@cf/qwen/qwen3-embedding-0.6b", {"text": [question]})
        vectors = embed.get("vectors") or embed.get("data") or []
        question_vector = vectors[0] if vectors else None
    except Exception:
        question_vector = None

    # 2. Vector search (tenant-isolated via metadata filter).
    context_chunks: List[Dict[str, Any]] = []
    if question_vector:
        try:
            results = await env.VECTORIZE_INDEX.query(
                vector=question_vector,
                topK=5,
                returnMetadata=True,
                filter={"tenant_id": tenant_id},
            )
            matches = results.get("matches", []) if isinstance(results, dict) else []
            for m in matches:
                meta = m.get("metadata", {}) or {}
                context_chunks.append({
                    "id": m.get("id"),
                    "document_id": meta.get("document_id"),
                    "chunk_id": meta.get("chunk_id"),
                    "content": meta.get("content", ""),
                    "score": m.get("score", 0),
                })
        except Exception:
            context_chunks = []

    # 3. Build cited context.
    context_parts: List[str] = []
    citations: List[Dict[str, Any]] = []
    for idx, ch in enumerate(context_chunks, start=1):
        context_parts.append(f"[{idx}] {ch['content']}")
        citations.append({"id": idx, "document_id": ch["document_id"],
                          "chunk_id": ch["chunk_id"], "score": ch["score"]})
    context = "\n".join(context_parts)

    system_prompt = QUESTION_SYSTEM_PROMPT
    user_prompt = (f"Context:\n{context}\n\nQuestion: {question}" if context
                   else f"Question: {question}")

    # 4. LLM answer (retry once; deterministic extractive fallback if unavailable).
    llm = await _ai_run_with_retry(env, "@cf/openai/gpt-oss-20b", {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 512,
    }, attempts=2)
    answer = ""
    tokens_used = 0
    ai_unavailable = llm is None
    if llm is not None:
        answer = llm.get("response", "") if isinstance(llm, dict) else str(llm)
        usage = llm.get("usage", {}) if isinstance(llm, dict) else {}
        tokens_used = int(usage.get("total_tokens", 0) or 0)
        # Post-run token accounting for the daily quota bucket (best-effort).
        await _accumulate_tokens(env, tenant_id, tokens_used)
    else:
        # Deterministic extractive fallback: answer built from retrieved
        # context with [n] citation markers, no LLM involved.
        answer = _ai_unavailable_fallback(context_chunks, question, kind="question")

    await _audit(env, tenant_id, tenant_id, "question", question,
                 {"idempotency_key": idempotency_key, "tokens": tokens_used,
                  "citations": [c["id"] for c in citations],
                  "ai": "unavailable" if ai_unavailable else "ok"})

    response_body: Dict[str, Any] = {
        "answer": answer,
        "citations": citations,
        "tokens_used": tokens_used,
        "ts": _now_ms(),
    }
    if ai_unavailable:
        response_body["ai"] = "unavailable"
    return JSONResponse(response_body)


# ---------------------------------------------------------------------------
# API v2 aliases.
#
# Mechanism: every /api/v1/* route is re-registered under /api/v2/* pointing at
# the SAME handler endpoint (single implementation, two prefixes). v1 contracts
# are untouched; v2 is a pure alias so both versions stay in lock-step. The
# AI-quota middleware path check (_is_ai_path) covers both prefixes.
# ---------------------------------------------------------------------------

from fastapi.routing import APIRoute as _APIRoute  # noqa: E402


def _register_v2_aliases(application: FastAPI) -> None:
    for route in list(application.routes):
        if isinstance(route, _APIRoute) and route.path.startswith("/api/v1/"):
            application.add_api_route(
                "/api/v2/" + route.path[len("/api/v1/"):],
                route.endpoint,
                methods=sorted(route.methods),
                name=route.name + "_v2",
            )


_register_v2_aliases(app)
