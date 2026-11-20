import importlib.util
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "eval_harness", Path(__file__).resolve().parents[2] / "scripts/eval_harness.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_live_url_accepts_bare_cloudflare_preview():
    assert MODULE.validate_live_url("https://incidentiq-preview.example.workers.dev/") == (
        "https://incidentiq-preview.example.workers.dev")


@pytest.mark.parametrize("url", [
    "http://incidentiq-preview.example.workers.dev",
    "https://127.0.0.1",
    "https://incidentiq-preview.example.workers.dev.evil.test",
    "https://user@incidentiq-preview.example.workers.dev",
    "https://incidentiq-preview.example.workers.dev:8443",
    "https://incidentiq-preview.example.workers.dev/path",
])
def test_live_url_rejects_ssrf_and_ambiguous_targets(url):
    with pytest.raises(ValueError):
        MODULE.validate_live_url(url)
