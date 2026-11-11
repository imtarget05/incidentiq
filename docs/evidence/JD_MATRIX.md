# JD evidence matrix

The acceptance backlog is [../../tasks/todo.md](../../tasks/todo.md). Status is conservative: code presence alone is not cloud verification.

| Capability | Implementation / probe | Evidence required | Current tier |
|---|---|---|---|
| AI API, REST contracts | API/OpenAPI and contract tests | test output + versioned schema | unproven for complete JD scope |
| MCP lifecycle / auth | real client initialize/list/call and tenant negatives | client transcript, redacted trace | unproven |
| RAG / embedding / vector | real upload/query/reindex/delete | labelled 100-case run, raw retrieval | unproven live |
| ETL reliability | concurrent retries, outages, DLQ/replay | failure-injection/restart record | unproven pending Mốc1 |
| Data Foundation / DWH | separate analytics DB, dbt, incremental replay | dbt/quality/reconciliation output | unproven |
| Authz / security | tenant/owner tests and dependency scans | raw test + scan reports | unproven complete gate |
| Testing / reproducibility | `python3 scripts/jd.py collect --suite <name>` | revision-bound local JSON | verified_local only where baseline records a pass |
| Monitoring / tracing | dependency probe + end-to-end trace | dashboard and delivered alert | unproven |
| Performance / cost | fixed workload 1/5/10 users | p50/p95/errors and measured billing window | unproven |
| Cloud / recovery | isolated deploy, 24h observation, restore/rollback | cloud artifact + runbook execution | unproven; cost cap not set |
| Teamwork / experience | real employment and individual ownership | CV/contribution history | outside repository verification |

No cloud deployment, budget approval, human dataset review, permanent uptime or employment experience is asserted by this matrix.
