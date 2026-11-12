import asyncio
import json
from types import SimpleNamespace

import v2


class FakeStatement:
    def __init__(self, result):
        self.result = result
        self.params = None

    def bind(self, *params):
        self.params = params
        return self

    async def first(self):
        return self.result

    async def all(self):
        return self.result


def body(response):
    return json.loads(response.body)


def test_v2_incident_enforces_workspace_and_returns_version(monkeypatch):
    row = ["i-1", "w1", "t1", "Outage", "HIGH", "api", "prod", "OPEN", 1, "hash", 1, 2, None]
    statement = FakeStatement(row)
    monkeypatch.setattr(v2, "_env", lambda request: SimpleNamespace(DB=SimpleNamespace(prepare=lambda sql: statement)))
    ctx = {"tenant": {"id": "t1"}, "workspace_id": "w1"}
    response = asyncio.run(v2.v2_get_incident("i-1", None, ctx))
    assert response.status_code == 200
    assert body(response)["incident"]["api_version"] == "v2"
    assert statement.params == ("i-1", "t1")

    wrong_workspace = asyncio.run(v2.v2_get_incident("i-1", None, {**ctx, "workspace_id": "w2"}))
    assert wrong_workspace.status_code == 403
    statement.result = None
    missing = asyncio.run(v2.v2_get_incident("i-1", None, ctx))
    assert missing.status_code == 404


def test_v2_health_reports_missing_database(monkeypatch):
    monkeypatch.setattr(v2, "_env", lambda request: None)
    response = asyncio.run(v2.v2_health(None))
    assert response.status_code == 503
    assert body(response)["checks"]["d1"] == "unavailable"


def test_v2_quota_resets_expired_bucket(monkeypatch):
    now = 2 * 86400000 + 123
    statement = FakeStatement([["ai:daily", 15, 2 * 86400000], ["old", 70, 86400000]])
    monkeypatch.setattr(v2, "_now_ms", lambda: now)
    monkeypatch.setattr(v2, "_env", lambda request: SimpleNamespace(DB=SimpleNamespace(prepare=lambda sql: statement)))
    response = asyncio.run(v2.v2_metrics_quota(None, {"tenant": {"id": "t1"}}))
    data = body(response)
    assert data["ai_daily_count"] == 15
    assert data["token_budget_remaining"] == 85
    assert data["buckets"][1]["count"] == 0
