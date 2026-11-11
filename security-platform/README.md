# security-platform — Cybersecurity Dashboard backend

RESTful API for the Cybersecurity Dashboard, built with **Python + FastAPI** on **PostgreSQL**.
Part of the IncidentIQ repository, added to close the gaps identified against the
TrustLine Backend Engineer Intern JD: PostgreSQL & SQL, Docker, CI/CD running on a
host, dependency security, and seed/benchmark data.

## Stack (matches JD requirements)

| Requirement | Implementation |
|-------------|----------------|
| RESTful API | FastAPI, OpenAPI 3.0.3 (`openapi.yaml`) |
| Language | Python 3.11 (+ TypeScript MCP endpoint in `mcp/`) |
| Database | PostgreSQL 15 (schema + indexes in `migrations/`) |
| SQL | Parameterized queries, tenant-scoped indexes, `EXPLAIN`-friendly |
| Seed & benchmark data | `seed/seed.sql`, `seed/benchmark.sql` |
| Container | `Dockerfile` (multi-stage, non-root user) + `docker-compose.yml` |
| CI/CD | `.github/workflows/security-platform.yml` (lint, test, build, scan) |
| Auth | API key (SHA-256 hash), tenant binding, 401 on invalid key |
| Tests | `pytest` unit + integration (Postgres service container in CI) |

## Quick start (local)

```bash
cd security-platform

# 1. Copy env example and review values
cp .env.example .env

# 2. Start Postgres + app
docker compose up --build -d

# 3. Seed data (optional)
psql "$DATABASE_URL" -f seed/seed.sql

# 4. Call the API
curl -H "X-Api-Key: acme_live" http://localhost:8000/health
curl -H "X-Api-Key: acme_live" http://localhost:8000/api/v1/assets
```

`/health` now reports `database: down` when PostgreSQL is unreachable. Default local DSN
comes from `DATABASE_URL` (see `.env.example`); no credentials are hard-coded in the image.

The seed database includes three tenants (`acme_live`, `globex_live`, `soylent_live`)
with assets, vulnerabilities, alerts, incidents, scan results, and audit logs —
tenant-isolated so one tenant never sees another's data.

## Google Sign-In (OAuth2)

`security-platform` supports Google Sign-In via OAuth2 for production-grade user
authentication. Two endpoints are provided under `/auth`:

- `GET /auth/google/authorize` — redirects the user to Google's consent screen.
- `GET /auth/google/callback` — exchanges the authorization code, verifies the Google
  ID token, creates/links a tenant + user, and returns a signed JWT session token.

Required environment variables:

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | Google OAuth2 client ID (from `client_secret_*.json`) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth2 client secret (from `client_secret_*.json`) |
| `GOOGLE_REDIRECT_URI` | Redirect URI registered in Google Cloud Console (default: `http://localhost:8000/auth/google/callback`) |
| `JWT_SECRET_KEY` | Secret used to sign session JWTs (change in production) |

Flow:

1. Client calls `GET /auth/google/authorize` → redirected to Google.
2. User signs in and consents → Google redirects back to `/auth/google/callback?code=...`.
3. Server exchanges the code for an ID token, verifies the signature/audience,
   creates or links a tenant + user, and returns `{"access_token": "..."}`.
4. Client sends `Authorization: Bearer <access_token>` on subsequent API requests.
   Endpoints resolve the tenant from the JWT (falling back to `X-Api-Key`).

All credential files (`client_secret_*.json`, `*_api_key.txt`, `.env`) are gitignored
and must never be committed.

## API docs

OpenAPI spec: `security-platform/openapi.yaml` (servable by any Swagger UI).

## Tests

```bash
cd security-platform
pip install -r requirements.txt pytest pytest-asyncio httpx ruff
export DATABASE_URL="postgresql://security:security@localhost:5432/security_dashboard"
python -m pytest tests -q
```

CI runs the same suite against a PostgreSQL service container (see
`.github/workflows/security-platform.yml`).

## Security

- API keys are stored as SHA-256 hashes keyed by an 8-char prefix (never plaintext).
- Every mutating/read endpoint is bound to the authenticated tenant.
- `pip-audit` runs in CI on `requirements.txt`.
- `mcp/` runs `npm audit --fix` to clear critical/high advisories.

## CI

Workflow: `.github/workflows/security-platform.yml`
- Lint: `ruff check` + `ruff format --check`
- Test: `pytest` against Postgres service container
- Build: `docker build`
- Scan: `pip-audit`
