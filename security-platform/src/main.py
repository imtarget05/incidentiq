"""security-platform — FastAPI application for the Cybersecurity Dashboard.

Endpoints:
  POST   /api/v1/tenants          (register tenant + API key)
  GET    /api/v1/health
  GET    /api/v1/assets
  POST   /api/v1/assets
  GET    /api/v1/assets/{id}
  PUT    /api/v1/assets/{id}
  DELETE /api/v1/assets/{id}
  GET    /api/v1/vulnerabilities
  POST   /api/v1/vulnerabilities
  GET    /api/v1/alerts
  POST   /api/v1/alerts
  GET    /api/v1/alerts/{id}
  PUT    /api/v1/alerts/{id}
  DELETE /api/v1/alerts/{id}
  GET    /api/v1/incidents
  POST   /api/v1/incidents
  GET    /api/v1/incidents/{id}
  PUT    /api/v1/incidents/{id}/status
  GET    /api/v1/scan-results
  POST   /api/v1/scan-results
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)
from psycopg2.errors import UniqueViolation

from db import get_conn, put_conn, run_migration
from models import (
    AlertCreate,
    AlertOut,
    AlertUpdate,
    AssetCreate,
    AssetOut,
    AssetUpdate,
    IncidentCreate,
    IncidentOut,
    IncidentUpdate,
    ScanResultCreate,
    ScanResultOut,
    TenantCreate,
    TenantOut,
    VulnerabilityCreate,
    VulnerabilityOut,
)
from queries import (
    create_asset,
    create_alert,
    create_incident,
    create_scan_result,
    create_tenant,
    create_vulnerability,
    delete_alert,
    delete_asset,
    get_alert,
    get_asset,
    get_incident,
    list_alerts,
    list_assets,
    list_incidents,
    list_vulnerabilities,
    update_alert,
    update_asset,
    update_incident_status,
    write_audit_log,
)
from security import authenticate_tenant

MIGRATION_PATH = "migrations/0001_initial.sql"

app = FastAPI(title="Cybersecurity Dashboard API", version="1.0.0")


# ---------------------------------------------------------------------------
# Startup: run migrations
# ---------------------------------------------------------------------------


@app.on_event("startup")
def _startup() -> None:
    try:
        run_migration(MIGRATION_PATH)
    except Exception as exc:  # pragma: no cover - best effort at startup
        print(f"[security-platform] migration warning: {exc}")


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def get_tenant(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    return authenticate_tenant(request, x_api_key)


# ---------------------------------------------------------------------------
# Observability middleware (attach tenant to request.state as fallback)
# ---------------------------------------------------------------------------


@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    x_api_key = request.headers.get("x-api-key") or request.headers.get("X-Api-Key")
    tenant = None
    if x_api_key and len(x_api_key) >= 8:
        try:
            tenant = authenticate_tenant(request, x_api_key)
        except HTTPException:
            tenant = None
    request.state.tenant = tenant
    response = await call_next(request)
    return response


def require_tenant(request: Request) -> Dict[str, Any]:
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise HTTPException(
            status_code=401, detail="missing or invalid X-Api-Key header"
        )
    return tenant


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Health"])
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "security-platform"}


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------


@app.post("/api/v1/tenants", response_model=TenantOut, tags=["Tenants"])
def register_tenant(payload: TenantCreate) -> Any:
    try:
        return create_tenant(payload.name, payload.api_key)
    except Exception as exc:
        cause = getattr(exc, "__cause__", None)
        if isinstance(cause, UniqueViolation) or "unique" in str(exc).lower():
            raise HTTPException(
                status_code=409, detail="tenant name or api key prefix already exists"
            )
        raise HTTPException(status_code=500, detail="cannot create tenant")


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@app.get("/api/v1/assets", response_model=List[AssetOut], tags=["Assets"])
def list_assets_endpoint(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    is_active: Optional[bool] = Query(default=None),
) -> Any:
    tenant = require_tenant(request)
    rows, _total = list_assets(
        tenant["id"], limit=limit, offset=offset, is_active=is_active
    )
    return rows


@app.post("/api/v1/assets", response_model=AssetOut, status_code=201, tags=["Assets"])
def create_asset_endpoint(request: Request, payload: AssetCreate) -> Any:
    tenant = require_tenant(request)
    return create_asset(tenant["id"], payload.model_dump())


@app.get("/api/v1/assets/{asset_id}", response_model=AssetOut, tags=["Assets"])
def get_asset_endpoint(request: Request, asset_id: str = Path(...)) -> Any:
    tenant = require_tenant(request)
    asset = get_asset(asset_id, tenant["id"])
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


@app.put("/api/v1/assets/{asset_id}", response_model=AssetOut, tags=["Assets"])
def update_asset_endpoint(
    request: Request,
    asset_id: str = Path(...),
    payload: AssetUpdate = Depends(),
) -> Any:
    tenant = require_tenant(request)
    asset = update_asset(asset_id, tenant["id"], payload.model_dump(exclude_unset=True))
    if asset is None:
        raise HTTPException(status_code=404, detail="asset not found")
    return asset


@app.delete("/api/v1/assets/{asset_id}", tags=["Assets"])
def delete_asset_endpoint(request: Request, asset_id: str = Path(...)) -> Response:
    tenant = require_tenant(request)
    if not delete_asset(asset_id, tenant["id"]):
        raise HTTPException(status_code=404, detail="asset not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Vulnerabilities
# ---------------------------------------------------------------------------


@app.get(
    "/api/v1/vulnerabilities",
    response_model=List[VulnerabilityOut],
    tags=["Vulnerabilities"],
)
def list_vulnerabilities_endpoint(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    severity: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
) -> Any:
    tenant = require_tenant(request)
    rows, _ = list_vulnerabilities(
        tenant["id"], limit=limit, offset=offset, severity=severity, status=status
    )
    return rows


@app.post(
    "/api/v1/vulnerabilities",
    response_model=VulnerabilityOut,
    status_code=201,
    tags=["Vulnerabilities"],
)
def create_vulnerability_endpoint(
    request: Request, payload: VulnerabilityCreate
) -> Any:
    tenant = require_tenant(request)
    return create_vulnerability(tenant["id"], payload.model_dump())


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@app.get("/api/v1/alerts", response_model=List[AlertOut], tags=["Alerts"])
def list_alerts_endpoint(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    severity: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
) -> Any:
    tenant = require_tenant(request)
    rows, _ = list_alerts(
        tenant["id"], limit=limit, offset=offset, severity=severity, status=status
    )
    return rows


@app.post("/api/v1/alerts", response_model=AlertOut, status_code=201, tags=["Alerts"])
def create_alert_endpoint(request: Request, payload: AlertCreate) -> Any:
    tenant = require_tenant(request)
    alert = create_alert(tenant["id"], payload.model_dump())
    write_audit_log(
        tenant["id"],
        tenant["id"],
        "alert.create",
        str(alert["id"]),
        {"title": payload.title},
    )
    return alert


@app.get("/api/v1/alerts/{alert_id}", response_model=AlertOut, tags=["Alerts"])
def get_alert_endpoint(request: Request, alert_id: str = Path(...)) -> Any:
    tenant = require_tenant(request)
    alert = get_alert(alert_id, tenant["id"])
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return alert


@app.put("/api/v1/alerts/{alert_id}", response_model=AlertOut, tags=["Alerts"])
def update_alert_endpoint(
    request: Request,
    alert_id: str = Path(...),
    payload: AlertUpdate = Depends(),
) -> Any:
    tenant = require_tenant(request)
    alert = update_alert(alert_id, tenant["id"], payload.model_dump(exclude_unset=True))
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    write_audit_log(
        tenant["id"], tenant["id"], "alert.update", alert_id, {"status": payload.status}
    )
    return alert


@app.delete("/api/v1/alerts/{alert_id}", tags=["Alerts"])
def delete_alert_endpoint(request: Request, alert_id: str = Path(...)) -> Response:
    tenant = require_tenant(request)
    if not delete_alert(alert_id, tenant["id"]):
        raise HTTPException(status_code=404, detail="alert not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


@app.get("/api/v1/incidents", response_model=List[IncidentOut], tags=["Incidents"])
def list_incidents_endpoint(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    severity: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
) -> Any:
    tenant = require_tenant(request)
    rows, _ = list_incidents(
        tenant["id"], limit=limit, offset=offset, severity=severity, status=status
    )
    return rows


@app.post(
    "/api/v1/incidents", response_model=IncidentOut, status_code=201, tags=["Incidents"]
)
def create_incident_endpoint(request: Request, payload: IncidentCreate) -> Any:
    tenant = require_tenant(request)
    incident = create_incident(tenant["id"], payload.model_dump())
    write_audit_log(
        tenant["id"],
        tenant["id"],
        "incident.create",
        str(incident["id"]),
        {"severity": payload.severity},
    )
    return incident


@app.get(
    "/api/v1/incidents/{incident_id}", response_model=IncidentOut, tags=["Incidents"]
)
def get_incident_endpoint(request: Request, incident_id: str = Path(...)) -> Any:
    tenant = require_tenant(request)
    incident = get_incident(incident_id, tenant["id"])
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return incident


@app.put(
    "/api/v1/incidents/{incident_id}/status",
    response_model=IncidentOut,
    tags=["Incidents"],
)
def update_incident_status_endpoint(
    request: Request,
    incident_id: str = Path(...),
    payload: IncidentUpdate = Depends(),
) -> Any:
    tenant = require_tenant(request)
    if payload.status is None:
        raise HTTPException(status_code=400, detail="status field is required")
    incident = update_incident_status(incident_id, tenant["id"], payload.status)
    if incident is None:
        raise HTTPException(status_code=404, detail="incident not found")
    write_audit_log(
        tenant["id"],
        tenant["id"],
        "incident.status_changed",
        incident_id,
        {"to": payload.status},
    )
    return incident


# ---------------------------------------------------------------------------
# Scan results
# ---------------------------------------------------------------------------


@app.get(
    "/api/v1/scan-results", response_model=List[ScanResultOut], tags=["Scan Results"]
)
def list_scan_results_endpoint(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    tenant = require_tenant(request)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, asset_id, scan_type, status, findings_count, started_at, completed_at "
                "FROM scan_results WHERE tenant_id = %s ORDER BY started_at DESC LIMIT %s OFFSET %s",
                (tenant["id"], limit, offset),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        put_conn(conn)
    return rows


@app.post(
    "/api/v1/scan-results",
    response_model=ScanResultOut,
    status_code=201,
    tags=["Scan Results"],
)
def create_scan_result_endpoint(request: Request, payload: ScanResultCreate) -> Any:
    tenant = require_tenant(request)
    return create_scan_result(tenant["id"], payload.model_dump())
