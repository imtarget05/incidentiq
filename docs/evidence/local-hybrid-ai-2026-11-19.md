# IncidentIQ local hybrid benchmark — 2026-11-19

The [raw 30-case report](../../eval/results/local_hybrid_ai_2026-11-19.json)
was produced from clean source `2c5788057f254fdd83c009ae535d423b83381323`
using the same synthetic dataset SHA-256
`9e3dcda1df31e8087cd7628034d711908b11a66b69b2be48c02331ef852a34d7`
as the [keyword run](../../eval/results/local_fts_ai_2026-11-19_1536.json).
It exercised the real FastAPI incident creation and triage routes. Documents
were preseeded into in-memory SQLite FTS5. Cloudflare Workers AI generated one
embedding batch for the 20 documents, 30 query embeddings and 30 LLM answers.
The embeddings were searched through an **in-memory cosine index** matching
the Vectorize query shape; no hosted Vectorize index or ETL worker was used.

To reproduce, run the evaluator with `--hybrid` as well as the account ID and
scoped local Wrangler OAuth config described in
[the keyword benchmark](local-fts-ai-2026-11-19.md). Use a different `--output`
path to preserve this report. The OAuth token stays outside the report.

| Measurement | Local hybrid result | Keyword-only result, same dataset and max tokens |
|---|---:|---:|
| Cases / HTTP errors | 30 / 0 | 30 / 0 |
| Document ID Recall@5, sufficient cases | 20/20 | 20/20 |
| Citation MRR@5 | 0.5833 | 0.5833 |
| Abstention, insufficient cases | 10/10 | 10/10 |
| Status match | 30/30 | 30/30 |
| Literal hypothesis phrase hits | 2/20 | 1/20 |
| Mean / p95 triage latency | 4.848s / 12.362s | 9.721s / 34.055s |
| Generation-only estimated inference cost | $0.005730 | $0.005380 |

Every case had the **same document recall and reciprocal rank** as the keyword
run. The corpus contains close lexical matches, and the merge ranks keyword
candidates first, so this run does **not** demonstrate a retrieval gain from
vectors. The differing literal phrase hit and latency figures come from
separate live model calls and are not evidence that hybrid search improved
answer quality or speed. The cost estimate excludes embeddings and is not a
billing export. The literal phrase metric is not semantic answer accuracy.

The preview deployment's earlier fresh-document Recall@5 of 0.35 remains a
separate unresolved result. This localhost run cannot validate hosted
Vectorize, asynchronous ETL, tenant configuration in preview, or production
readiness. The next evaluation needs paraphrased queries and independently
reviewed answer labels to measure semantic retrieval and groundedness.
