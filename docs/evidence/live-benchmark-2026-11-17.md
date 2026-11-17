# Preview triage benchmark — 2026-11-17

Run: [GitHub Actions 44059197926](https://github.com/imtarget05/incidentiq/actions/runs/44059197926). The [raw report](live-benchmark-2026-11-17.json) records the preview URL, dataset hash, tested commit `cd9f68bb55497c6c463f2846e0326543cecdcb1e`, per-case results, and HTTP errors.

This is a **live preview** run on a synthetic 30-case dataset, not a production accuracy claim. The benchmark uploaded case documents, waited for ETL, created incidents, and called the real triage endpoint. Twenty cases had expected evidence; ten were intended to test abstention.

| Metric | Observed |
| --- | ---: |
| HTTP error rate | 2/30 (6.67%; both 503) |
| Recall@5 on sufficient cases | 0.45 |
| Citation MRR@5 | 0.1925 |
| Abstention rate on insufficient cases | 0 |
| Status accuracy | 0.60 |
| Hypothesis substring match | 0 |
| Mean / p95 latency | 7,508 / 11,831 ms |

The baseline fails the portfolio readiness bar. The retrieval path previously filled all five result slots with Vectorize neighbors before FTS matches, and treated every neighbor as evidence. The follow-up change uses the incident title for a safe FTS query, promotes keyword matches, deduplicates documents, and rejects weak title overlap. It is a conservative lexical filter and may reject valid semantic matches; a new live run is needed to measure the tradeoff. Hypothesis substring matching is narrow and must not be presented as a semantic quality score.
