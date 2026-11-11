"""security-platform — unit tests for query helpers (mocked database)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def test_list_assets_uses_tenant_isolation(fake_conn):
    conn, cur = fake_conn
    cur.fetchone.return_value = {"cnt": 2}
    cur.fetchall.return_value = [
        {
            "id": "a1",
            "tenant_id": "t1",
            "name": "web-01",
            "type": "server",
            "ip_address": None,
            "environment": "production",
            "is_active": True,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        },
    ]

    with patch("db.get_conn", return_value=conn), patch("db.put_conn"):
        from queries import list_assets

        rows, total = list_assets("t1", limit=10, offset=0)
        assert total == 2
        assert len(rows) == 1
        # Verify tenant_id is in the query
        args = cur.execute.call_args[0]
        sql = args[0]
        assert "tenant_id = %s" in sql
        assert "ORDER BY created_at DESC" in sql


def test_create_alert_returns_row(fake_conn):
    conn, cur = fake_conn
    cur.fetchone.return_value = {
        "id": "alert-1",
        "tenant_id": "t1",
        "asset_id": None,
        "vulnerability_id": None,
        "severity": "HIGH",
        "status": "new",
        "title": "Test",
        "description": None,
        "created_at": "2024-01-01T00:00:00",
        "resolved_at": None,
    }

    with patch("db.get_conn", return_value=conn), patch("db.put_conn"):
        from queries import create_alert

        result = create_alert(
            "t1",
            {
                "severity": "HIGH",
                "title": "Test",
                "description": None,
                "asset_id": None,
                "vulnerability_id": None,
            },
        )
        assert result["severity"] == "HIGH"
        assert result["status"] == "new"
