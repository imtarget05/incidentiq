# Incomplete preview benchmark — 2026-11-17

[Run 44098795797](https://github.com/imtarget05/incidentiq/actions/runs/44098795797) produced a [raw report](live-benchmark-incomplete-2026-11-17.json) at commit `fdb934f5e413d4c82050c7c4e9418fe31ff68259` before HTTP 503 on incident creation for `gc-20` stopped the runner. Only 19 of 30 cases completed, so the summary is **not** a full-dataset score and must not be compared as a replacement for the 30-case run.

The completed subset had fresh-ID recall@5 of 0.263 and exact-content recall@5 of 0.579. The gap confirms duplicate runbook content from prior runs affects the fresh-ID metric, while content retrieval still needs improvement. The runner now records a per-case error and continues when incident creation fails, preserving the remaining cases. A new full run is required.
