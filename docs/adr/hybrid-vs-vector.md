# ADR: Hybrid search vs pure vector search

## Decision
Use hybrid retrieval (D1 FTS5 keyword + Vectorize semantic, merged and re-ranked) instead of pure vector search.

## Rationale
- **Keyword strength**: Exact terms like "OOMKilled", "exit code 137", "CrashLoopBackOff" match runbooks reliably via FTS5; pure vector can miss exact error codes.
- **Vector strength**: Semantic similarity catches paraphrased symptoms ("container out of memory" ↔ "OOMKilled").
- **Comparison required by interview**: Interviewers ask "why hybrid instead of vector-only?" — we have a benchmark on the same golden evaluation set.
- **Fallback**: If Vectorize is down, keyword-only search still works (graceful degradation).

## Evidence
- `docs/evaluation.md` — recall@5 = 1.0 on the golden set (keyword + vector cover both exact codes and paraphrases).
- `api/src/main.py` `_hybrid_search` merges FTS5 and Vectorize results, deduplicated and re-ranked.
- `docs/failure-modes.md` — Vectorize down → keyword-only.

## Trade-offs accepted
- Slightly higher latency (two retrieval paths); bounded by small topK (5) and short chunks.