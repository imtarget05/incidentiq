"""security-platform — Optimized SQL queries for the Cybersecurity Dashboard."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from db import execute, fetch_all, fetch_one


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------


def create_tenant(name: str, api_key: str) -> Dict[str, Any]:
    prefix = api_key[:8]
    api_key_hash = __import__("hashlib").sha256(api_key.encode("utf-8")).hexdigest()
    return fetch_one(
        "INSERT INTO tenants (name, api_key_prefix, api_key_hash) "
        "VALUES (%s, %s, %s) RETURNING id, name, api_key_prefix, is_active, created_at",
        (name, prefix, api_key_hash),
        commit=True,
    )


def get_tenant_by_prefix(prefix: str) -> Optional[Dict[str, Any]]:
    return fetch_one(
        "SELECT id, name, api_key_prefix, is_active, created_at FROM tenants "
        "WHERE api_key_prefix = %s AND is_active = TRUE LIMIT 1",
        (prefix,),
    )


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


def create_asset(tenant_id: str, payload: dict) -> Dict[str, Any]:
    return fetch_one(
        "INSERT INTO assets (tenant_id, name, type, ip_address, environment, is_active) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id, tenant_id, name, type, ip_address, environment, is_active, created_at, updated_at",
        (
            tenant_id,
            payload["name"],
            payload["type"],
            payload.get("ip_address"),
            payload.get("environment", "production"),
            payload.get("is_active", True),
        ),
        commit=True,
    )


def list_assets(
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    is_active: Optional[bool] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    where = "WHERE tenant_id = %s"
    params: List[Any] = [tenant_id]
    if is_active is not None:
        where += " AND is_active = %s"
        params.append(is_active)

    total = fetch_one(f"SELECT count(*) AS cnt FROM assets {where}", tuple(params))[
        "cnt"
    ]

    rows = fetch_all(
        f"SELECT id, tenant_id, name, type, ip_address, environment, is_active, created_at, updated_at "
        f"FROM assets {where} "
        f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    )
    return rows, total


def get_asset(asset_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    return fetch_one(
        "SELECT id, tenant_id, name, type, ip_address, environment, is_active, created_at, updated_at "
        "FROM assets WHERE id = %s AND tenant_id = %s LIMIT 1",
        (asset_id, tenant_id),
    )


def update_asset(
    asset_id: str, tenant_id: str, payload: dict
) -> Optional[Dict[str, Any]]:
    sets = []
    params: List[Any] = []
    for field in ("name", "type", "ip_address", "environment", "is_active"):
        if field in payload:
            sets.append(f"{field} = %s")
            params.append(payload[field])
    if not sets:
        return get_asset(asset_id, tenant_id)
    params.extend([asset_id, tenant_id])
    return fetch_one(
        f"UPDATE assets SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s "
        f"RETURNING id, tenant_id, name, type, ip_address, environment, is_active, created_at, updated_at",
        tuple(params),
        commit=True,
    )


def delete_asset(asset_id: str, tenant_id: str) -> bool:
    return (
        execute(
            "DELETE FROM assets WHERE id = %s AND tenant_id = %s",
            (asset_id, tenant_id),
        )
        > 0
    )


# ---------------------------------------------------------------------------
# Vulnerabilities
# ---------------------------------------------------------------------------


def create_vulnerability(tenant_id: str, payload: dict) -> Dict[str, Any]:
    return fetch_one(
        "INSERT INTO vulnerabilities (tenant_id, asset_id, cve_id, severity, status, description) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id, tenant_id, asset_id, cve_id, severity, status, description, detected_at, remediated_at",
        (
            tenant_id,
            payload.get("asset_id"),
            payload.get("cve_id"),
            payload["severity"],
            payload.get("status", "open"),
            payload.get("description"),
        ),
        commit=True,
    )


def list_vulnerabilities(
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    severity: Optional[str] = None,
    status: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    where = "WHERE tenant_id = %s"
    params: List[Any] = [tenant_id]
    if severity:
        where += " AND severity = %s"
        params.append(severity)
    if status:
        where += " AND status = %s"
        params.append(status)

    total = fetch_one(
        f"SELECT count(*) AS cnt FROM vulnerabilities {where}", tuple(params)
    )["cnt"]

    rows = fetch_all(
        f"SELECT id, tenant_id, asset_id, cve_id, severity, status, description, detected_at, remediated_at "
        f"FROM vulnerabilities {where} "
        f"ORDER BY detected_at DESC LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    )
    return rows, total


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


def create_alert(tenant_id: str, payload: dict) -> Dict[str, Any]:
    return fetch_one(
        "INSERT INTO alerts (tenant_id, asset_id, vulnerability_id, severity, title, description) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id, tenant_id, asset_id, vulnerability_id, severity, status, title, description, created_at, resolved_at",
        (
            tenant_id,
            payload.get("asset_id"),
            payload.get("vulnerability_id"),
            payload["severity"],
            payload["title"],
            payload.get("description"),
        ),
        commit=True,
    )


def list_alerts(
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    severity: Optional[str] = None,
    status: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    where = "WHERE tenant_id = %s"
    params: List[Any] = [tenant_id]
    if severity:
        where += " AND severity = %s"
        params.append(severity)
    if status:
        where += " AND status = %s"
        params.append(status)

    total = fetch_one(f"SELECT count(*) AS cnt FROM alerts {where}", tuple(params))[
        "cnt"
    ]

    rows = fetch_all(
        f"SELECT id, tenant_id, asset_id, vulnerability_id, severity, status, title, description, created_at, resolved_at "
        f"FROM alerts {where} "
        f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    )
    return rows, total


def get_alert(alert_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    return fetch_one(
        "SELECT id, tenant_id, asset_id, vulnerability_id, severity, status, title, description, created_at, resolved_at "
        "FROM alerts WHERE id = %s AND tenant_id = %s LIMIT 1",
        (alert_id, tenant_id),
    )


def update_alert(
    alert_id: str, tenant_id: str, payload: dict
) -> Optional[Dict[str, Any]]:
    sets = []
    params: List[Any] = []
    for field in ("severity", "status", "title", "description"):
        if field in payload:
            sets.append(f"{field} = %s")
            params.append(payload[field])
    if not sets:
        return get_alert(alert_id, tenant_id)
    params.extend([alert_id, tenant_id])
    return fetch_one(
        f"UPDATE alerts SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s "
        f"RETURNING id, tenant_id, asset_id, vulnerability_id, severity, status, title, description, created_at, resolved_at",
        tuple(params),
        commit=True,
    )


def delete_alert(alert_id: str, tenant_id: str) -> bool:
    return (
        execute(
            "DELETE FROM alerts WHERE id = %s AND tenant_id = %s", (alert_id, tenant_id)
        )
        > 0
    )


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


def create_incident(tenant_id: str, payload: dict) -> Dict[str, Any]:
    return fetch_one(
        "INSERT INTO incidents (tenant_id, title, severity, service, environment) "
        "VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id, tenant_id, title, severity, status, service, environment, created_at, updated_at, resolved_at",
        (
            tenant_id,
            payload["title"],
            payload["severity"],
            payload["service"],
            payload["environment"],
        ),
        commit=True,
    )


def list_incidents(
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
    severity: Optional[str] = None,
    status: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    where = "WHERE tenant_id = %s"
    params: List[Any] = [tenant_id]
    if severity:
        where += " AND severity = %s"
        params.append(severity)
    if status:
        where += " AND status = %s"
        params.append(status)

    total = fetch_one(f"SELECT count(*) AS cnt FROM incidents {where}", tuple(params))[
        "cnt"
    ]

    rows = fetch_all(
        f"SELECT id, tenant_id, title, severity, status, service, environment, created_at, updated_at, resolved_at "
        f"FROM incidents {where} "
        f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    )
    return rows, total


def get_incident(incident_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    return fetch_one(
        "SELECT id, tenant_id, title, severity, status, service, environment, created_at, updated_at, resolved_at "
        "FROM incidents WHERE id = %s AND tenant_id = %s LIMIT 1",
        (incident_id, tenant_id),
    )


def update_incident_status(
    incident_id: str, tenant_id: str, status: str
) -> Optional[Dict[str, Any]]:
    now = __import__("datetime").datetime.utcnow()
    params = [status, now, incident_id, tenant_id]
    if status == "resolved":
        params.insert(2, now)  # resolved_at before incident_id
        sql = (
            "UPDATE incidents SET status = %s, updated_at = %s, resolved_at = %s "
            "WHERE id = %s AND tenant_id = %s "
            "RETURNING id, tenant_id, title, severity, status, service, environment, created_at, updated_at, resolved_at"
        )
    else:
        sql = (
            "UPDATE incidents SET status = %s, updated_at = %s "
            "WHERE id = %s AND tenant_id = %s "
            "RETURNING id, tenant_id, title, severity, status, service, environment, created_at, updated_at, resolved_at"
        )
    return fetch_one(sql, tuple(params), commit=True)


# ---------------------------------------------------------------------------
# Scan results
# ---------------------------------------------------------------------------


def create_scan_result(tenant_id: str, payload: dict) -> Dict[str, Any]:
    return fetch_one(
        "INSERT INTO scan_results (tenant_id, asset_id, scan_type, findings_count) "
        "VALUES (%s, %s, %s, %s) "
        "RETURNING id, tenant_id, asset_id, scan_type, status, findings_count, started_at, completed_at",
        (
            tenant_id,
            payload.get("asset_id"),
            payload["scan_type"],
            payload.get("findings_count", 0),
        ),
        commit=True,
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def write_audit_log(
    tenant_id: str, actor: str, action: str, resource: str, metadata: dict
) -> None:
    execute(
        "INSERT INTO audit_logs (tenant_id, actor, action, resource, metadata) "
        "VALUES (%s, %s, %s, %s, %s)",
        (tenant_id, actor, action, resource, __import__("json").dumps(metadata)),
    )
