# IncidentIQ — Evaluation Results

Total golden cases: 30
Sufficient-evidence cases: 20
Insufficient-evidence cases: 10

## Retrieval metrics
- Recall@5: 1.0
- Citation MRR@5: 1.0

## Answer metrics
- Correctness (status + hypothesis): 1.0
- Citation validity: 1.0
- Groundedness: 1.0
- Abstention rate (insufficient cases): 1.0
- Hallucination rate (ok but no evidence): 0.0

## Method
Ran 30 deterministic cases (20 sufficient, 10 insufficient) against faked D1, Vectorize, and AI backends.
These scores are regression-harness results, not live retrieval or answer-quality estimates.
