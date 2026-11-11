"""IncidentIQ — Azure backend HTTP client.

Client for the hybrid Option B deployment: the Cloudflare Workers API proxies
data-plane requests to the IncidentIQ backend running on Azure Container Apps.
Used only when USE_AZURE_BACKEND=1; otherwise the existing Cloudflare D1 /
Vectorize / Queues bindings remain the canonical data plane.

All requests carry X-Api-Key (caller tenant key) and X-Edge-Secret (shared
Cloudflare <-> Azure secret) so the Azure backend can authenticate the edge.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


class AzureBackendError(RuntimeError):
    """Raised when the Azure backend returns an error or is unreachable."""


class AzureBackendClient:
    def __init__(
        self,
        base_url: str,
        edge_secret: str,
        api_key: Optional[str] = None,
        timeout_s: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.edge_secret = edge_secret
        self.api_key = api_key
        self.timeout_s = timeout_s

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Edge-Secret": self.edge_secret,
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        if extra:
            headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=self._headers(headers), method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
                try:
                    return resp.status, json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    return resp.status, {"raw": raw}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                return exc.code, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return exc.code, {"raw": raw}
        except Exception as exc:
            raise AzureBackendError(str(exc)) from exc

    # ── health ──────────────────────────────────────────────────────────────

    def health_live(self) -> Tuple[int, Dict[str, Any]]:
        return self._request("GET", "/health/live")

    def health_ready(self) -> Tuple[int, Dict[str, Any]]:
        return self._request("GET", "/health/ready")

    # ── documents ───────────────────────────────────────────────────────────

    def list_documents(self, tenant_id: str) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "GET",
            "/api/v1/documents",
            headers={"X-Tenant-Id": tenant_id},
        )

    def create_document(
        self,
        tenant_id: str,
        workspace_id: str,
        filename: str,
        content: str,
        idempotency_key: str,
    ) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "POST",
            "/api/v1/documents",
            body={
                "filename": filename,
                "content": content,
                "idempotency_key": idempotency_key,
            },
            headers={
                "X-Tenant-Id": tenant_id,
                "X-Workspace-Id": workspace_id,
            },
        )

    def get_document(self, document_id: str, tenant_id: str) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/v1/documents/{document_id}",
            headers={"X-Tenant-Id": tenant_id},
        )

    def update_document(
        self,
        document_id: str,
        tenant_id: str,
        workspace_id: str,
        content: str,
        filename: Optional[str],
    ) -> Tuple[int, Dict[str, Any]]:
        body: Dict[str, Any] = {"content": content}
        if filename is not None:
            body["filename"] = filename
        return self._request(
            "PUT",
            f"/api/v1/documents/{document_id}",
            body=body,
            headers={
                "X-Tenant-Id": tenant_id,
                "X-Workspace-Id": workspace_id,
            },
        )

    def delete_document(self, document_id: str, tenant_id: str) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "DELETE",
            f"/api/v1/documents/{document_id}",
            headers={"X-Tenant-Id": tenant_id},
        )

    def reindex_document(
        self,
        document_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "POST",
            f"/api/v1/documents/{document_id}/reindex",
            headers={
                "X-Tenant-Id": tenant_id,
                "X-Workspace-Id": workspace_id,
            },
        )

    # ── incidents ───────────────────────────────────────────────────────────

    def list_incidents(self, tenant_id: str) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "GET",
            "/api/v1/incidents",
            headers={"X-Tenant-Id": tenant_id},
        )

    def create_incident(
        self,
        tenant_id: str,
        workspace_id: str,
        title: str,
        severity: str,
        service: str,
        environment: str,
        idempotency_key: str,
    ) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "POST",
            "/api/v1/incidents",
            body={
                "title": title,
                "severity": severity,
                "service": service,
                "environment": environment,
                "idempotency_key": idempotency_key,
            },
            headers={
                "X-Tenant-Id": tenant_id,
                "X-Workspace-Id": workspace_id,
            },
        )

    def get_incident(self, incident_id: str, tenant_id: str) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/v1/incidents/{incident_id}",
            headers={"X-Tenant-Id": tenant_id},
        )

    def patch_incident(
        self,
        incident_id: str,
        tenant_id: str,
        workspace_id: str,
        status: str,
        if_match: Optional[int] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        body: Dict[str, Any] = {"status": status}
        headers: Dict[str, str] = {
            "X-Tenant-Id": tenant_id,
            "X-Workspace-Id": workspace_id,
        }
        if if_match is not None:
            headers["If-Match"] = str(if_match)
        return self._request(
            "PATCH",
            f"/api/v1/incidents/{incident_id}",
            body=body,
            headers=headers,
        )

    def add_incident_event(
        self,
        incident_id: str,
        tenant_id: str,
        workspace_id: str,
        event_type: str,
        severity: Optional[str],
        service: Optional[str],
        environment: Optional[str],
        timestamp: Optional[int],
        logs: Optional[str],
        deploy_context: Optional[str],
    ) -> Tuple[int, Dict[str, Any]]:
        body: Dict[str, Any] = {"event_type": event_type}
        if severity is not None:
            body["severity"] = severity
        if service is not None:
            body["service"] = service
        if environment is not None:
            body["environment"] = environment
        if timestamp is not None:
            body["timestamp"] = timestamp
        if logs is not None:
            body["logs"] = logs
        if deploy_context is not None:
            body["deploy_context"] = deploy_context
        return self._request(
            "POST",
            f"/api/v1/incidents/{incident_id}/events",
            body=body,
            headers={
                "X-Tenant-Id": tenant_id,
                "X-Workspace-Id": workspace_id,
            },
        )

    def get_incident_timeline(
        self, incident_id: str, tenant_id: str
    ) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/v1/incidents/{incident_id}/timeline",
            headers={"X-Tenant-Id": tenant_id},
        )

    # ── triage / question ───────────────────────────────────────────────────

    def triage_incident(
        self,
        incident_id: str,
        tenant_id: str,
        workspace_id: str,
    ) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "POST",
            f"/api/v1/incidents/{incident_id}/triage",
            headers={
                "X-Tenant-Id": tenant_id,
                "X-Workspace-Id": workspace_id,
            },
        )

    def get_incident_report(
        self, incident_id: str, tenant_id: str
    ) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/v1/incidents/{incident_id}/report",
            headers={"X-Tenant-Id": tenant_id},
        )

    def ask_question(
        self,
        tenant_id: str,
        question: str,
        idempotency_key: str,
    ) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "POST",
            "/api/v1/question",
            body={"question": question},
            headers={
                "X-Tenant-Id": tenant_id,
                "X-Idempotency-Key": idempotency_key,
            },
        )

    def list_workspaces(self, tenant_id: str) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "GET",
            "/api/v1/workspaces",
            headers={"X-Tenant-Id": tenant_id},
        )

    def metrics_quota(self, tenant_id: str) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            "GET",
            "/api/v1/metrics/quota",
            headers={"X-Tenant-Id": tenant_id},
        )
