import asyncio
import json
from types import SimpleNamespace

import pytest

import main


def test_startup_rejects_missing_cloudflare_bindings() -> None:
    with pytest.raises(RuntimeError, match="D1_DATABASE_ID.*VECTORIZE_INDEX_NAME.*ETL_QUEUE_NAME.*ETL_DLQ_NAME"):
        main._validate_startup_config(SimpleNamespace())


def test_startup_accepts_all_required_bindings() -> None:
    env = SimpleNamespace(**{name: "configured" for name in main._REQUIRED_ENV_VARS})
    main._validate_startup_config(env)


def test_readiness_degrades_when_binding_access_raises(monkeypatch) -> None:
    class BrokenBindings:
        def __getattr__(self, name):
            raise RuntimeError("binding unavailable")

    monkeypatch.setattr(main, "_env", lambda request: BrokenBindings())
    response = asyncio.run(main.health_ready(None))
    assert response.status_code == 503
    assert set(json.loads(response.body)["checks"].values()) == {"unavailable"}
