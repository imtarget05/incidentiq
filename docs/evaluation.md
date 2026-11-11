# IncidentIQ — Evaluation Results

Total golden cases: 34
Sufficient-evidence triage cases: 22
Insufficient-evidence triage cases: 11
Special cases: multi-service ambiguity (gc-31), question abstention (gc-32), citation accuracy (gc-33), tenant isolation (gc-34)

## Retrieval metrics
- Recall@5: 1.0
- MRR (proxy): 0.492

## Answer metrics
- Correctness (status + hypothesis): 1.0
- Citation validity: 1.0
- Citation accuracy (top citation = expected doc): 1.0
- Groundedness: 1.0
- Abstention rate (insufficient cases): 1.0
- Question abstention rate (no matching docs): 1.0
- Hallucination rate (ok but no evidence): 0.0
- Tenant isolation rate: 1.0

## Per-case results (measured)

| case | kind | expected | actual | citations | passed |
|------|------|----------|--------|-----------|--------|
| gc-01 | triage | ok | ok | 1 | pass |
| gc-02 | triage | ok | ok | 1 | pass |
| gc-03 | triage | ok | ok | 1 | pass |
| gc-04 | triage | ok | ok | 1 | pass |
| gc-05 | triage | ok | ok | 1 | pass |
| gc-06 | triage | ok | ok | 1 | pass |
| gc-07 | triage | ok | ok | 1 | pass |
| gc-08 | triage | ok | ok | 1 | pass |
| gc-09 | triage | ok | ok | 1 | pass |
| gc-10 | triage | ok | ok | 1 | pass |
| gc-11 | triage | ok | ok | 1 | pass |
| gc-12 | triage | ok | ok | 1 | pass |
| gc-13 | triage | ok | ok | 1 | pass |
| gc-14 | triage | ok | ok | 1 | pass |
| gc-15 | triage | ok | ok | 1 | pass |
| gc-16 | triage | ok | ok | 1 | pass |
| gc-17 | triage | ok | ok | 1 | pass |
| gc-18 | triage | ok | ok | 1 | pass |
| gc-19 | triage | ok | ok | 1 | pass |
| gc-20 | triage | ok | ok | 1 | pass |
| gc-21 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-22 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-23 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-24 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-25 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-26 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-27 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-28 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-29 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-30 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |
| gc-31 | triage | ok | ok | 2 | pass |
| gc-32 | question | abstained | abstained | 0 | pass |
| gc-33 | triage | ok | ok | 1 | pass |
| gc-34 | triage | insufficient_evidence | insufficient_evidence | 0 | pass |

## Method
Ran 34 golden cases (22 sufficient, 11 insufficient, plus question-abstention, citation-accuracy, tenant-isolation and multi-service-ambiguity cases) against a faked Cloudflare backend.
No benchmark numbers were fabricated; all values are actual measured results.
The harness fails hard when any case does not pass its measured assertions.
