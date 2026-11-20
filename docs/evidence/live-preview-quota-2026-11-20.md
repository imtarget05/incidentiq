# Hosted preview benchmark blocked by Workers AI quota — 2026-11-20

[Preview deployment run 44681344753](https://github.com/imtarget05/incidentiq/actions/runs/44681344753) succeeded on commit `3d16c49116b4`, including API and MCP smoke. [Live benchmark run 44681557905](https://github.com/imtarget05/incidentiq/actions/runs/44681557905) then used the isolated preview with real D1, Workers AI, and Vectorize. Its [unaltered raw artifact](live-preview-quota-2026-11-20.json) has `complete=false`: 14 of 30 cases reached triage; one returned HTTP 200 and 13 returned HTTP 429 `ai_quota_exceeded`. The next incident creation returned HTTP 503. The single successful response did not cite the expected document.

This incomplete run cannot establish hosted Recall@5, MRR, abstention, or a keyword-versus-hybrid comparison. The old artifact's zero-valued retrieval scores include HTTP failures and must not be interpreted as retrieval quality. Main's current evaluator separately reports quality for available responses and the HTTP error rate. This change stops a run at the first 429, preserving quota and recording it as incomplete. The raw artifact has not been rescored or rewritten.

Run a complete benchmark when Workers AI quota is available. Preview results must not be presented as production traffic or user adoption.
