"""security-platform — API integration tests.

These tests require a running PostgreSQL reachable via DATABASE_URL
(or the default local DSN). In CI, a PostgreSQL service container is provided.
"""

from __future__ import annotations

from typing import Dict

from fastapi.testclient import TestClient


def _headers(api_key: str) -> Dict[str, str]:
    return {"X-Api-Key": api_key}


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_register_tenant(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/tenants",
        json={"name": "integration-tenant", "api_key": "int_live_abcd1234"},
    )
    assert resp.status_code in (200, 409), resp.text
    body = resp.json()
    assert body["name"] == "integration-tenant"
    assert "id" in body


def test_missing_api_key_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/assets")
    assert resp.status_code == 401


def test_invalid_api_key_rejected(client: TestClient) -> None:
    resp = client.get("/api/v1/assets", headers=_headers("bad_key_1234"))
    assert resp.status_code == 401


def test_asset_crud(client: TestClient, auth_headers: Dict[str, str]) -> None:
    # Create
    resp = client.post(
        "/api/v1/assets",
        headers=auth_headers,
        json={
            "name": "web-prod-01",
            "type": "server",
            "ip_address": "10.0.1.10",
            "environment": "production",
        },
    )
    assert resp.status_code == 201, resp.text
    asset = resp.json()
    assert asset["name"] == "web-prod-01"
    asset_id = asset["id"]

    # List
    resp = client.get("/api/v1/assets", headers=auth_headers)
    assert resp.status_code == 200
    assert any(a["id"] == asset_id for a in resp.json())

    # Get
    resp = client.get(f"/api/v1/assets/{asset_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == asset_id

    # Update
    resp = client.put(
        f"/api/v1/assets/{asset_id}",
        headers=auth_headers,
        json={"environment": "staging"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["environment"] == "staging"

    # Delete
    resp = client.delete(f"/api/v1/assets/{asset_id}", headers=auth_headers)
    assert resp.status_code == 204, resp.text

    # Confirm deleted
    resp = client.get(f"/api/v1/assets/{asset_id}", headers=auth_headers)
    assert resp.status_code == 404


def test_alert_crud(client: TestClient, auth_headers: Dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/alerts",
        headers=auth_headers,
        json={
            "severity": "HIGH",
            "title": "Test alert",
            "description": "Integration test alert",
        },
    )
    assert resp.status_code == 201, resp.text
    alert = resp.json()
    assert alert["title"] == "Test alert"
    assert alert["status"] == "new"
    alert_id = alert["id"]

    # List
    resp = client.get("/api/v1/alerts", headers=auth_headers)
    assert resp.status_code == 200
    assert any(a["id"] == alert_id for a in resp.json())

    # Get
    resp = client.get(f"/api/v1/alerts/{alert_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == alert_id

    # Update status
    resp = client.put(
        f"/api/v1/alerts/{alert_id}",
        headers=auth_headers,
        json={"status": "acknowledged"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "acknowledged"

    # Delete
    resp = client.delete(f"/api/v1/alerts/{alert_id}", headers=auth_headers)
    assert resp.status_code == 204, resp.text


def test_incident_crud(client: TestClient, auth_headers: Dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/incidents",
        headers=auth_headers,
        json={
            "title": "Integration incident",
            "severity": "CRITICAL",
            "service": "web-api",
            "environment": "production",
        },
    )
    assert resp.status_code == 201, resp.text
    incident = resp.json()
    assert incident["title"] == "Integration incident"
    incident_id = incident["id"]

    # List
    resp = client.get("/api/v1/incidents", headers=auth_headers)
    assert resp.status_code == 200
    assert any(i["id"] == incident_id for i in resp.json())

    # Get
    resp = client.get(f"/api/v1/incidents/{incident_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == incident_id

    # Update status to resolved
    resp = client.put(
        f"/api/v1/incidents/{incident_id}/status",
        headers=auth_headers,
        json={"status": "resolved"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "resolved"


def test_vulnerability_crud(client: TestClient, auth_headers: Dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/vulnerabilities",
        headers=auth_headers,
        json={
            "cve_id": "CVE-2024-TEST",
            "severity": "HIGH",
            "status": "open",
            "description": "Test vulnerability",
        },
    )
    assert resp.status_code == 201, resp.text
    vuln = resp.json()
    assert vuln["cve_id"] == "CVE-2024-TEST"
    assert vuln["severity"] == "HIGH"


def test_scan_result(client: TestClient, auth_headers: Dict[str, str]) -> None:
    resp = client.post(
        "/api/v1/scan-results",
        headers=auth_headers,
        json={
            "scan_type": "full",
            "findings_count": 5,
        },
    )
    assert resp.status_code == 201, resp.text
    result = resp.json()
    assert result["scan_type"] == "full"
    assert result["findings_count"] == 5

    # List
    resp = client.get("/api/v1/scan-results", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_tenant_isolation(client: TestClient, auth_headers: Dict[str, str]) -> None:
    """Data created under one tenant must not leak to another."""
    # Create a second tenant
    resp = client.post(
        "/api/v1/tenants",
        json={"name": "tenant-two", "api_key": "tenant2_live_abcd1234"},
    )
    assert resp.status_code in (200, 409), resp.text
    headers_two = _headers("tenant2_live_abcd1234")

    # Create an asset under tenant-one
    resp = client.post(
        "/api/v1/assets",
        headers=auth_headers,
        json={"name": "tenant-one-asset", "type": "server"},
    )
    assert resp.status_code == 201
    asset_id = resp.json()["id"]

    # Tenant-two should not see it
    resp = client.get(f"/api/v1/assets/{asset_id}", headers=headers_two)
    assert resp.status_code == 404

    # Tenant-two list should not contain it
    resp = client.get("/api/v1/assets", headers=headers_two)
    assert resp.status_code == 200
    assert all(a["id"] != asset_id for a in resp.json())
