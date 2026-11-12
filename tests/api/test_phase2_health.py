"""Tests for Phase 2 additions: /health/live, /health/ready, and API v2 endpoints."""

import os
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "api", "src"))

import main  # noqa: E402


# ── Minimal fake env helpers ────────────────────────────────────────────────

def _make_minimal_env():
    return SimpleNamespace(
        DB=SimpleNamespace(prepare=lambda sql: None),
        VECTORIZE_INDEX=object(),
        ai=object(),
        ETL_QUEUE=object(),
        ETL_DLQ=object(),
        ETL_MODE="inline",
    )


def _client_with_env(env):
    client = TestClient(main.app)
    main._env_override = env  # type: ignore[attr-defined]
    return client


# ── /health/live ─────────────────────────────────────────────────────────────

class TestHealthLive:
    def test_always_200_without_env(self, monkeypatch):
        monkeypatch.setattr(main, "_env", lambda req: None)
        client = TestClient(main.app)
        r = client.get("/health/live")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "ts" in body

    def test_200_with_env(self, monkeypatch):
        env = _make_minimal_env()
        monkeypatch.setattr(main, "_env", lambda req: env)
        client = TestClient(main.app)
        r = client.get("/health/live")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_no_auth_required(self, monkeypatch):
        monkeypatch.setattr(main, "_env", lambda req: None)
        client = TestClient(main.app)
        r = client.get("/health/live")
        assert r.status_code == 200


# ── /health/ready ─────────────────────────────────────────────────────────────

class TestHealthReady:
    def test_degraded_without_env(self, monkeypatch):
        monkeypatch.setattr(main, "_env", lambda req: None)
        client = TestClient(main.app)
        r = client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert "checks" in body
        assert body["checks"]["d1"] == "unavailable"

    def test_ok_with_all_bindings(self, monkeypatch):
        env = _make_minimal_env()
        monkeypatch.setattr(main, "_env", lambda req: env)
        client = TestClient(main.app)
        r = client.get("/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        checks = body["checks"]
        assert checks["d1"] == "ok"
        assert checks["vectorize"] == "ok"
        assert checks["workers_ai"] == "ok"
        assert checks["etl_queue"] == "ok"

    def test_degraded_missing_db(self, monkeypatch):
        env = _make_minimal_env()
        env.DB = None  # type: ignore[assignment]
        monkeypatch.setattr(main, "_env", lambda req: env)
        client = TestClient(main.app)
        r = client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["d1"] == "unavailable"

    def test_contains_service_field(self, monkeypatch):
        monkeypatch.setattr(main, "_env", lambda req: None)
        client = TestClient(main.app)
        r = client.get("/health/ready")
        assert "service" in r.json()

    def test_no_auth_required(self, monkeypatch):
        monkeypatch.setattr(main, "_env", lambda req: None)
        client = TestClient(main.app)
        r = client.get("/health/ready")
        # Should return 503 (degraded) but not 401/403.
        assert r.status_code != 401
        assert r.status_code != 403


# ── Legacy /health ─────────────────────────────────────────────────────────────

class TestHealthLegacy:
    def test_ok_without_env_is_degraded(self, monkeypatch):
        monkeypatch.setattr(main, "_env", lambda req: None)
        client = TestClient(main.app)
        r = client.get("/health")
        assert r.status_code == 200  # /health always 200
        assert r.json()["status"] == "degraded"

    def test_ok_with_env(self, monkeypatch):
        env = _make_minimal_env()
        monkeypatch.setattr(main, "_env", lambda req: env)
        client = TestClient(main.app)
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ── Triage system prompt quality ──────────────────────────────────────────────

class TestTriagePromptQuality:
    def test_prompt_contains_key_instructions(self):
        prompt = main.TRIAGE_SYSTEM_PROMPT.lower()
        assert "triage assistant" in prompt
        assert "only" in prompt  # cite only provided context
        assert "read-only" in prompt or "read_only" in prompt or "read only" in prompt
        assert "json" in prompt  # structured output expected

    def test_prompt_forbids_production_modifications(self):
        prompt = main.TRIAGE_SYSTEM_PROMPT.lower()
        assert "not" in prompt or "never" in prompt  # has prohibition language
        assert "production" in prompt

    def test_prompt_requires_citation(self):
        assert "[n]" in main.TRIAGE_SYSTEM_PROMPT

    def test_prompt_requires_language_matching(self):
        assert "same language" in main.TRIAGE_SYSTEM_PROMPT.lower()
