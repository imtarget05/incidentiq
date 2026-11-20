# Hosted preview benchmark blocked by Workers AI quota — 2026-11-20

[Deploy preview run 44681344753](https://github.com/imtarget05/incidentiq/actions/runs/44681344753)
succeeded on PR #16 head `3d16c49116b4`, including API and MCP smoke. The
[live benchmark run 44681557905](https://github.com/imtarget05/incidentiq/actions/runs/44681557905)
used that same head and the isolated preview URL. Its [unaltered raw artifact](live-preview-quota-2026-11-20.json)
has `complete=false`: only 14 of 30 cases reached triage; 13 returned HTTP 429
`ai_quota_exceeded` and the next incident creation returned HTTP 503. The one
HTTP 200 case had no expected citation. These observations **do not establish**
hosted Recall@5, MRR, abstention, or a keyword-versus-hybrid comparison.

The old summary assigned zero retrieval quality to every HTTP failure. The
evaluator now excludes non-200 responses from quality denominators, reports
their rate separately, and stops after a 429 to avoid spending the remaining
daily quota on a run that cannot finish. The raw artifact is preserved as
produced by the old evaluator; no scores were rewritten. Re-run a complete
benchmark only when the preview Workers AI quota is available. Do not infer
production behavior from preview or from this incomplete run.
