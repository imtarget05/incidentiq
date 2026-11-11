"""security-platform — Pydantic models for the Cybersecurity Dashboard API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=8, max_length=128)


class TenantOut(BaseModel):
    id: UUID
    name: str
    api_key_prefix: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=50)
    ip_address: Optional[str] = None
    environment: str = Field(default="production", max_length=50)
    is_active: bool = True


class AssetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    ip_address: Optional[str] = None
    environment: Optional[str] = Field(default=None, max_length=50)
    is_active: Optional[bool] = None


class AssetOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    type: str
    ip_address: Optional[str]
    environment: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Vulnerability
# ---------------------------------------------------------------------------


class VulnerabilityCreate(BaseModel):
    asset_id: Optional[UUID] = None
    cve_id: Optional[str] = Field(default=None, max_length=50)
    severity: str = Field(pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$")
    status: str = Field(
        default="open", pattern=r"^(open|in_progress|remediated|false_positive)$"
    )
    description: Optional[str] = None


class VulnerabilityUpdate(BaseModel):
    severity: Optional[str] = Field(
        default=None, pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$"
    )
    status: Optional[str] = Field(
        default=None, pattern=r"^(open|in_progress|remediated|false_positive)$"
    )
    description: Optional[str] = None


class VulnerabilityOut(BaseModel):
    id: UUID
    tenant_id: UUID
    asset_id: Optional[UUID]
    cve_id: Optional[str]
    severity: str
    status: str
    description: Optional[str]
    detected_at: datetime
    remediated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------


class AlertCreate(BaseModel):
    asset_id: Optional[UUID] = None
    vulnerability_id: Optional[UUID] = None
    severity: str = Field(pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$")
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class AlertUpdate(BaseModel):
    severity: Optional[str] = Field(
        default=None, pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$"
    )
    status: Optional[str] = Field(
        default=None, pattern=r"^(new|acknowledged|resolved|dismissed)$"
    )
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None


class AlertOut(BaseModel):
    id: UUID
    tenant_id: UUID
    asset_id: Optional[UUID]
    vulnerability_id: Optional[UUID]
    severity: str
    status: str
    title: str
    description: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Incident
# ---------------------------------------------------------------------------


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    severity: str = Field(pattern=r"^(LOW|MEDIUM|HIGH|CRITICAL)$")
    service: str = Field(min_length=1, max_length=100)
    environment: str = Field(min_length=1, max_length=50)


class IncidentUpdate(BaseModel):
    status: Optional[str] = Field(
        default=None, pattern=r"^(open|investigating|resolved)$"
    )


class IncidentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    title: str
    severity: str
    status: str
    service: str
    environment: str
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# ScanResult
# ---------------------------------------------------------------------------


class ScanResultCreate(BaseModel):
    asset_id: Optional[UUID] = None
    scan_type: str = Field(min_length=1, max_length=50)
    findings_count: int = Field(default=0, ge=0)


class ScanResultOut(BaseModel):
    id: UUID
    tenant_id: UUID
    asset_id: Optional[UUID]
    scan_type: str
    status: str
    findings_count: int
    started_at: datetime
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class AuthOut(BaseModel):
    tenant_id: UUID
    name: str


# ---------------------------------------------------------------------------
# Generic
# ---------------------------------------------------------------------------


class ErrorOut(BaseModel):
    code: str
    message: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"code": "not_found", "message": "resource not found"}
        }
    )


class PaginationMeta(BaseModel):
    limit: int
    offset: int
    total: int
