import asyncio
import json
from types import SimpleNamespace

import main


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


class FakeDB:
    def __init__(self):
        self.writes = []

    def prepare(self, sql):
        self.sql = sql
        return self

    def bind(self, *params):
        self.writes.append((self.sql, params))
        return self

    async def run(self):
        return None


def test_workspace_creation_writes_membership_and_audit(monkeypatch):
    db = FakeDB()
    audits = []

    async def audit(*args):
        audits.append(args)

    monkeypatch.setattr(main, "_env", lambda request: SimpleNamespace(DB=db))
    monkeypatch.setattr(main, "_audit", audit)
    response = asyncio.run(main.create_workspace(FakeRequest({"name": "  Operations  "}), {"id": "tenant-1"}))
    assert response.status_code == 201
    assert json.loads(response.body)["name"] == "Operations"
    assert len(db.writes) == 2
    assert db.writes[1][1][2] == "tenant-1"
    assert audits[0][3] == "workspace.create"


def test_workspace_creation_rejects_missing_and_oversized_names(monkeypatch):
    monkeypatch.setattr(main, "_env", lambda request: SimpleNamespace(DB=FakeDB()))
    for name, code in [(" ", "missing_name"), ("x" * 101, "name_too_long")]:
        response = asyncio.run(main.create_workspace(FakeRequest({"name": name}), {"id": "tenant-1"}))
        assert response.status_code == 400
        assert json.loads(response.body)["error"]["code"] == code
