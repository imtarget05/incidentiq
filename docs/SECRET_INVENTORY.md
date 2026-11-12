# Secret Inventory — IncidentIQ

Generated: 2026-11-12
Source: `.env.example`, `wrangler.toml`, `wrangler.preview.toml`, `wrangler.etl.toml`
Convention: set via `wrangler secret put` for production; never committed to git.

## Cloudflare Workers / D1 / Vectorize
| Key | Source | Status | Notes |
|-----|--------|--------|-------|
| CLOUDFLARE_ACCOUNT_ID | .env.example | placeholder | your_account_id |
| CLOUDFLARE_API_TOKEN | .env.example | placeholder | deployment only |
| D1_DATABASE_ID | .env.example | placeholder | your_d1_database_id |
| D1_DATABASE_NAME | .env.example | value | ai-knowledge-platform |
| VECTORIZE_INDEX_NAME | .env.example | value | ai-knowledge-vectors |
| API_WORKER_URL | .env.example | value | https://...workers.dev |

## MCP (OAuth)
| Key | Source | Status | Notes |
|-----|--------|--------|-------|
| MCP_BASE_URL | .env.example | value | https://...workers.dev |
| MCP_CLIENT_ID | .env.example | placeholder | your_mcp_client_id |
| MCP_CLIENT_SECRET | .env.example | placeholder | your_mcp_client_secret |

## Limits (free-tier guardrails, not secrets)
MAX_DOCUMENTS_PER_TENANT=50, MAX_DOCUMENT_SIZE_MB=1, MAX_QUESTIONS_PER_DAY=100, MAX_TOKENS_PER_ANSWER=512, MAX_CHUNK_CHARS=800, MAX_CHUNKS_PER_DOCUMENT=25, TOP_K=5, ETL_MODE=inline.

## Hardcode check
No hardcoded token/password found in source tree outside `.env.example` placeholders.
