"""Pydantic schemas for input validation in IncidentIQ API.

Enforces schema-based validation on all mutation endpoints and queries.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class IncidentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Brief summary of the incident")
    severity: str = Field(..., description="Severity level: LOW, MEDIUM, HIGH, CRITICAL")
    service: str = Field(..., min_length=1, max_length=100, description="Affected service name")
    environment: str = Field(..., min_length=1, max_length=50, description="Deployment environment")

    @field_validator("title", "service", "environment")
    @classmethod
    def strip_text(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Field cannot be empty or whitespace only")
        return s

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        s = v.strip().upper()
        if s not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise ValueError("severity must be one of LOW, MEDIUM, HIGH, CRITICAL")
        return s


class IncidentStatusUpdate(BaseModel):
    status: str = Field(..., description="Target status: OPEN, INVESTIGATING, RESOLVED")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        s = v.strip().upper()
        if s not in {"OPEN", "INVESTIGATING", "RESOLVED"}:
            raise ValueError("invalid status")
        return s


class IncidentEventCreate(BaseModel):
    event_type: str = Field(default="event_added", max_length=100)
    severity: str | None = Field(default=None, max_length=20)
    service: str | None = Field(default=None, max_length=100)
    environment: str | None = Field(default=None, max_length=50)
    timestamp: int | None = Field(default=None)
    logs: str | None = Field(default=None, max_length=10000)
    deploy_context: str | None = Field(default=None, max_length=500)


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="Natural language question to ask")

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("question field cannot be empty")
        return s


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="Workspace name")

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("workspace name cannot be empty")
        return s


class DocumentUpdate(BaseModel):
    content: str = Field(..., description="UTF-8 plain text or Markdown document content")
    filename: str | None = Field(default=None, max_length=255)
