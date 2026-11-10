# ADR: RAG vs Fine-tuning

## Decision
Use Retrieval-Augmented Generation (RAG) instead of fine-tuning for incident triage.

## Rationale
- **Citation requirement**: Incident triage must cite sources (runbook ID, version, section). RAG returns retrieved chunks with document IDs/versions; fine-tuning cannot provide verifiable citations.
- **Currency**: Runbooks and postmortems change frequently. RAG re-indexes changed documents; fine-tuning requires retraining to reflect new docs.
- **Cost**: Workers AI free tier (10,000 neurons/day). Fine-tuning is not available on Cloudflare Free and would exceed the budget.
- **Abstention**: RAG can return `insufficient_evidence` when no chunk grounds the answer. Fine-tuned models tend to hallucinate.
- **Audit**: Every retrieved chunk is logged (document_id, version, section) for interview defense.

## Trade-offs accepted
- Retrieval quality depends on chunking/embedding; mitigated by hybrid search (keyword + vector) and evaluation harness.
- Context window limits; mitigated by small chunks (max 800 chars, max 25/doc).

## Evidence
- `docs/evaluation.md` — citation validity 1.0, groundedness 1.0, hallucination rate 0.0.
- `api/src/main.py` `TRIAGE_SYSTEM_PROMPT` instructs citations and abstention.