NGUYEN BINH TAN
Ho Chi Minh City, Vietnam | +84 xxx xxx xxx | nguyenbinhtan@email.com
linkedin.com/in/nguyenbinhtan | github.com/nguyenbinhtan

OBJECTIVE
Motivated 4th-year Information Technology student seeking a Business Analysis / Development / Testing
internship (3+ months). Hands-on experience building RESTful APIs with Python/FastAPI and TypeScript,
designing PostgreSQL schemas, writing automated tests, and integrating AI agents (MCP / RAG). Eager to turn
business needs into working solutions while validating AI outputs responsibly.

EDUCATION
Bachelor of Science in Information Technology / Computer Science
[University Name], Ho Chi Minh City, Vietnam
Expected graduation: [Month Year]  |  GPA: [7.5+ / 10]
Relevant coursework: Software Engineering, Database Systems, Web Application Development,
API Design & Integration, Quality Assurance & Testing, AI/ML Fundamentals, Git & Version Control.

TECHNICAL SKILLS
Languages: Python 3.11+, TypeScript, JavaScript, SQL (PostgreSQL), Bash
Frameworks & Libraries: FastAPI, Pydantic v2, psycopg2, FastAPI TestClient, Vitest, httpx
Databases: PostgreSQL (schema design, indexes, migrations), Cloudflare D1, Vectorize, Qdrant
API: RESTful API design, OpenAPI 3.0 (Swagger), JSON-RPC 2.0 (MCP), SSE streaming
Testing & Quality: pytest (unit + integration), ruff, Trivy (fs/secret/misconfig scan), SonarQube,
npm audit, Testcontainers patterns, coverage reporting
AI / Agents: Model Context Protocol (MCP) server, hybrid retrieval (dense + BM25 + RRF),
Workers AI embeddings, RAG eval harness, responsible AI output validation
DevOps & Tools: Git, GitHub Actions CI/CD, Docker (multi-stage, non-root user), Wrangler,
Cloudflare Workers, Linux CLI, uv, npm

PROJECTS

IncidentIQ — Document-Grounded Incident Triage  |  Python · TypeScript · Cloudflare Workers · D1 · Vectorize · MCP
github.com/nguyenbinhtan/incidentiq
Backend API and MCP tool endpoint for retrieving operational knowledge during incident triage.

- Designed and implemented a FastAPI-compatible Python Worker API with document upload, lexical + vector
  retrieval, Workers AI embeddings, and an ETL consumer (inline + queue modes) with idempotency keys.
- Built a TypeScript MCP server (JSON-RPC 2.0) exposing 7 tenant-scoped tools: search_runbooks,
  get_incident, find_similar_incidents, get_triage_report, upload_document, ask_question, list_documents.
- Enforced multi-tenant security: API keys stored as SHA-256 hashes with 8-char prefix lookup; every tool
  call binds the authenticated tenant and rejects tenant_id mismatches (403).
- Wrote D1 schema migrations (001–005): tenants, documents, workspaces, incidents, triage reports,
  triage metrics, atomic idempotency tables.
- Achieved 60/60 passing API tests under Python 3.13; MCP: 15 passing tests + typecheck.
- Configured GitHub Actions CI: lint (ruff), pytest with coverage, MCP typecheck/tests, Trivy fs scan
  (HIGH/CRITICAL), SonarQube quality gate, Wrangler dry-run validation.
- Wrote and validated OpenAPI 3.0.3 spec (openapi.yaml) documenting all REST endpoints.

security-platform — Cybersecurity Dashboard API  |  Python · FastAPI · PostgreSQL · psycopg2 · Pydantic
github.com/nguyenbinhtan/incidentiq (security-platform/)
RESTful backend for a cybersecurity dashboard with tenant-isolated assets, vulnerabilities, alerts,
incidents, and scan results.

- Designed PostgreSQL schema (gen_random_uuid UUIDs, foreign keys, CHECK constraints, 12+ optimized
  indexes on tenant_id/severity/status/created_at) and migration 0001_initial.sql.
- Implemented CRUD + filtered list endpoints (/api/v1/{assets,vulnerabilities,alerts,incidents,scan_results})
  with pagination, severity/status filtering, and tenant-scoped queries.
- Enforced tenant isolation via SHA-256-hashed API key authentication; every request binds to a single
  tenant, verified by a dedicated tenant-isolation integration test.
- Wrote audit logging for alert/incident create/update/status-change actions (JSONB metadata).
- Wrote unit tests with mocked database connections and integration tests using FastAPI TestClient
  against PostgreSQL (CRUD lifecycle for assets, alerts, incidents, vulnerabilities, scan results).
- Provided seed.sql and benchmark.sql for reproducible test data loading.

Enterprise Document Intelligence — Corrective RAG Platform  |  Python · Java · TypeScript · Kubernetes · Qdrant
github.com/nguyenbinhtan/Enterprise-Document-Intelligence-Corrective-RAG-Platform
Enterprise RAG platform with hybrid retrieval, SSE streaming, and eval harness.

- Contributed to RAG agent with hybrid retrieval (Qdrant dense + BM25 + Reciprocal Rank Fusion) and
  Spring Boot PostgreSQL lexical fallback.
- Implemented SSE streaming (status → metadata → chunk → complete) with incremental frontend rendering.
- Built eval harness: 28 fixture smoke tests (passing) + live benchmark script (Hit@K/Recall@K/MRR).
- Frontend test suite: 104 passing tests; production dependencies: 0 npm vulnerabilities.
- Defined Kubernetes topology (Deployments, Services, HPA, readiness/liveness probes, non-root
  securityContext); all k8s YAMLs validated.

EXPERIENCE
[Internship / Part-time role]  |  [Company Name]  |  [Month Year] – [Month Year]
[Role: Business Analyst / Developer / QA Intern]
- [Clarified requirements and documented user stories + acceptance criteria with stakeholders.]
- [Assisted in developing features, APIs, and integrations; wrote unit/integration tests.]
- [Investigated issues, verified fixes, and shared progress with business and engineering teams.]

HONORS & ACTIVITIES
- [Hackathon / competition award, if any]
- [Relevant certification, if any]
- [Student club / community activity, if any]

LANGUAGES
English: fluent (spoken and written) — comfortable in team and stakeholder discussions
Vietnamese: native
