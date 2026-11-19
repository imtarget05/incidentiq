# IncidentIQ local SQLite FTS5 + live Workers AI benchmark — 2026-11-19

This exercise ran the **real FastAPI incident creation and triage routes** through `TestClient`, with all four D1 SQL migrations applied to an in-memory SQLite database. All 30 synthetic runbook cases from `data/rag_eval_dataset.json` were preseeded into SQLite FTS5. The AI binding called Cloudflare `@cf/openai/gpt-oss-20b` with real inference. Vectorize and the asynchronous ETL worker were deliberately absent; the retrieval path was **keyword-only**. This is not a hosted preview, production, hybrid retrieval, or customer-data result.

The evaluator is [`eval/run_local_fts_ai_benchmark.py`](../../eval/run_local_fts_ai_benchmark.py). It records the dataset SHA-256, tested Git commit, per-case citations/status/latency/token counts, and estimated inference cost. To reproduce with a scoped Cloudflare token supplied through the environment:

```sh
CLOUDFLARE_ACCOUNT_ID=<account-id> CLOUDFLARE_API_TOKEN=<token> \
  python3 eval/run_local_fts_ai_benchmark.py \
  --output eval/results/local_fts_ai_recheck.json
```

The recorded runs used a local Wrangler OAuth config through `--wrangler-oauth-config`; the token was not copied into the report. No Azure resource was used.

| Measure | 1024 output token run | 1536 output token run |
| --- | ---: | ---: |
| Tested source commit | `7495801abc7ec65e0df6268c4027574a10003fd2` | `40a09942` (full SHA in report) |
| Completed cases / HTTP errors | 30 / 0 | 30 / 0 |
| Fresh document ID Recall@5, 20 evidence cases | 20/20 | 20/20 |
| Citation MRR@5, 20 evidence cases | 0.583 | 0.583 |
| Correct abstention, 10 no-evidence cases | 10/10 | 10/10 |
| Expected API status | 28/30 | 30/30 |
| Literal hypothesis substring match | 0/20 | 1/20 |
| Mean / p95 triage latency | 7.05s / 14.12s | 9.72s / 34.06s |
| Estimated Workers AI inference cost | $0.005196 | $0.005380 |

Raw reports: [1024-token run](../../eval/results/local_fts_ai_2026-11-19_1024.json), [1536-token run](../../eval/results/local_fts_ai_2026-11-19_1536.json). The estimated cost uses Cloudflare's [listed GPT-OSS-20B token prices](https://developers.cloudflare.com/workers-ai/models/gpt-oss-20b/) and recorded prompt/completion counts; it is not a billing export.

In the first run, `gc-17` exhausted the output budget and returned empty content. The API now reported `ai_unavailable` and retained citations instead of claiming a synthesized answer. `gc-19` had a 90-second provider timeout and also returned `ai_unavailable`. Both returned `ok` in the later 1536-token run. The runs were sequential and the model/provider is variable, so the status and latency difference cannot be attributed solely to the higher token limit. The 1536-token run had a substantially slower p95, including a 57-second successful call. No latency target is claimed.

The literal substring metric checks fixed English phrases against generated hypothesis text; it is deliberately kept as a strict reproducible signal but does **not** measure semantic correctness. Several generated excerpts use paraphrases; the metric should not be quoted as answer accuracy. Groundedness and hallucination still require a separate reviewed answer set. The local FTS result does not resolve the preview hybrid-retrieval result, where fresh-document ID Recall@5 was 0.35 on a different run. Rerun the hosted preview after PR merge before making a hybrid retrieval claim.
