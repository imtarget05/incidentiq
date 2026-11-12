# Contributing — IncidentIQ

Conventions: ECC (TDD, immutability, 80%+ coverage, conventional commits, security review, code review).

## Branch & commit
- Create branch from `main`: `feat/<scope>`, `fix/<scope>`, `refactor/<scope>`, `docs/<scope>`, `test/<scope>`, `chore/<scope>`, `ci/<scope>`.
- Commit message: `type(scope): summary` + optional body + `Signed-off-by: Name <email>`.
- No direct push to `main` — PR required, reviewed, CI green.

## TDD workflow
1. Write a failing test (RED).
2. Implement the smallest change to pass (GREEN).
3. Refactor (IMPROVE), keep coverage ≥ 80%.
4. Run `python -m pytest --cov=api/src --cov-report=xml --cov-report=term-missing tests/api` (Python) and `npm run typecheck && npm run test:coverage` (MCP/TS).

## Immutability
- Do not mutate input models; return a new copy.
- Python: return new dict/list, avoid in-place ops on inputs.
- TypeScript: spread / immutable helpers, no `push`/`splice` on inputs.

## Security
- No hardcoded secrets. Set via `wrangler secret put` for production; `.env.example` only contains placeholders.
- MCP bearer token, tenant binding, and write tools (document upload, incident operations) require independent security review before merge.
- Validate input at API boundary (Pydantic schema, Zod schema).
- CI runs Trivy (vuln/secret/misconfig HIGH/CRITICAL, exit-code 1) and pip-audit/npm audit.

## Code review
- Every PR needs ≥ 1 approval (`ecc:code-reviewer`).
- Auth / tenant-boundary / write-tool changes additionally need `ecc:security-reviewer`.
- No merge with CI red or open security findings.

## File size
- Source file < 800 lines; split module if exceeded.

## Error handling
- Never swallow exceptions silently. Log detailed context server-side; return safe, generic messages to the client.

## Repo-specific commands
- Python: `pip install -r api/requirements.txt ruff pytest-cov && ruff check --select E4,E7,E9,F api/src tests/api scripts && python -m pytest --cov=api/src --cov-report=xml tests/api`
- MCP: `cd mcp && npm ci && npm run typecheck && npm run test:coverage`
- Wrangler dry-run: `uv run pywrangler deploy --dry-run --outdir /tmp/...`
