# Preview benchmark after retrieval change — 2026-11-17

Run: [GitHub Actions 44061633095](https://github.com/imtarget05/incidentiq/actions/runs/44061633095). The [raw report](live-benchmark-post-retrieval-2026-11-17.json) was produced against preview commit `4448f8ceb067684809cfceb346e972b94d3f0176`; the preview deployment [succeeded](https://github.com/imtarget05/incidentiq/actions/runs/44061372783).

| Metric | Before | After |
| --- | ---: | ---: |
| HTTP error rate | 6.67% | 0% |
| Recall@5 by freshly uploaded document ID | 0.45 | 0.35 |
| Citation MRR@5 by fresh ID | 0.1925 | 0.1033 |
| Abstention on insufficient cases | 0% | 100% |
| Status accuracy | 60% | 100% |
| Hypothesis substring match | 0% | 5% |
| Mean / p95 latency (ms) | 7,508 / 11,831 | 6,762 / 9,616 |

**Readiness: failed.** The safety behavior improved, but the document-ID recall regressed. The preview database retained synthetic documents from previous benchmark runs. Each run uploads identical runbook content under new document IDs, so a citation to an older equivalent copy is counted as a miss by the current ID metric. A second content-equivalence metric has been added to the runner for future runs; this report predates that metric. The 5% hypothesis substring match remains far below a useful quality bar. These comparisons are directional because the two live runs had different transient HTTP outcomes and corpus sizes.
