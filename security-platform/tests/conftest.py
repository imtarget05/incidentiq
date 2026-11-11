"""security-platform — pytest configuration and fixtures."""

from __future__ import annotations

import os
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    """FastAPI TestClient. Requires DATABASE_URL pointing to a test Postgres."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def api_key(client: TestClient) -> str:
    """Create a test tenant and return its API key."""
    resp = client.post(
        "/api/v1/tenants",
        json={"name": "test-tenant", "api_key": "test_live_abcd1234"},
    )
    assert resp.status_code in (200, 409), resp.text
    return "test_live_abcd1234"


@pytest.fixture
def auth_headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key}


def pytest_configure(config: object) -> None:
    # Ensure the app can import src modules when tests run from repo root.
    import sys

    src_path = os.path.join(os.path.dirname(__file__), "..", "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
