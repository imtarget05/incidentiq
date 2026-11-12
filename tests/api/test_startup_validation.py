import asyncio
import json
from types import SimpleNamespace

import pytest

import main


def test_startup_rejects_missing_cloudflare_bindings() -> None:
    with pytest.raises(RuntimeError, match="DB.*VECTORIZE_INDEX.*ETL_QUEUE.*ETL_DLQ.*ai"):
        main._validate_startup_config(SimpleNamespace())


def test_startup_accepts_bindings_declared_by_wrangler() -> None:
    env = SimpleNamespace(DB=object(), VECTORIZE_INDEX=object(), ETL_QUEUE=object(), ETL_DLQ=object(), ai=object())
    main._validate_startup_config(env)


def test_readiness_degrades_when_binding_access_raises(monkeypatch) -> None:
    class BrokenBindings:
        def __getattr__(self, name):
            raise RuntimeError("binding unavailable")

    monkeypatch.setattr(main, "_env", lambda request: BrokenBindings())
    response = asyncio.run(main.health_ready(None))
    assert response.status_code == 503
    assert set(json.loads(response.body)["checks"].values()) == {"unavailable"}
