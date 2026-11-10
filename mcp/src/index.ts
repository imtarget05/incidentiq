/// <reference types="@cloudflare/workers-types" />

interface Env {
  DB: D1Database;
  API_WORKER_URL: string;
  VECTORIZE_INDEX: VectorizeIndex;
  AI?: any;
}

type JsonRpcRequest = {
  jsonrpc?: string;
  id?: string | number | null;
  method: string;
  params?: Record<string, unknown>;
};

function jsonRpc(id: JsonRpcRequest["id"], result: unknown) {
  return { jsonrpc: "2.0", id, result };
}

function jsonRpcError(id: JsonRpcRequest["id"], code: number, message: string) {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

const TOOL_NAMES = new Set([
  "search_runbooks",
  "get_incident",
  "find_similar_incidents",
  "get_triage_report",
  "upload_document",
  "ask_question",
  "list_documents",
]);

const INPUT_SCHEMAS: Record<string, { required: string[]; properties: Record<string, { type: string }> }> = {
  search_runbooks: { required: ["query", "tenant_id"], properties: { query: { type: "string" }, topK: { type: "number" }, tenant_id: { type: "string" } } },
  get_incident: { required: ["incident_id", "tenant_id"], properties: { incident_id: { type: "string" }, tenant_id: { type: "string" } } },
  find_similar_incidents: { required: ["service", "tenant_id"], properties: { service: { type: "string" }, limit: { type: "number" }, tenant_id: { type: "string" } } },
  get_triage_report: { required: ["incident_id", "tenant_id"], properties: { incident_id: { type: "string" }, tenant_id: { type: "string" } } },
  upload_document: { required: ["filename", "content", "idempotency_key", "tenant_id"], properties: { filename: { type: "string" }, content: { type: "string" }, idempotency_key: { type: "string" }, tenant_id: { type: "string" } } },
  ask_question: { required: ["question", "idempotency_key", "tenant_id"], properties: { question: { type: "string" }, idempotency_key: { type: "string" }, tenant_id: { type: "string" } } },
  list_documents: { required: ["tenant_id"], properties: { tenant_id: { type: "string" } } },
};

function validateInput(tool: string, params: unknown): { ok: true; params: Record<string, unknown> } | { ok: false; error: { code: number; message: string } } {
  const schema = INPUT_SCHEMAS[tool];
  if (!schema) {
    return { ok: false, error: { code: -32602, message: `Unknown tool: ${tool}` } };
  }
  const p = params as Record<string, unknown> | null;
  if (!p || typeof p !== "object") {
    return { ok: false, error: { code: -32602, message: "params must be an object" } };
  }
  for (const req of schema.required) {
    if (!(req in p) || p[req] === undefined || p[req] === null) {
      return { ok: false, error: { code: -32602, message: `Missing required param: ${req}` } };
    }
  }
  for (const [key, spec] of Object.entries(schema.properties)) {
    const val = p[key];
    if (val === undefined) continue;
    if (spec.type === "string" && typeof val !== "string") {
      return { ok: false, error: { code: -32602, message: `Param ${key} must be a string` } };
    }
    if (spec.type === "number" && typeof val !== "number") {
      return { ok: false, error: { code: -32602, message: `Param ${key} must be a number` } };
    }
  }
  return { ok: true, params: p };
}

const rateLimitStore = new Map<string, { count: number; windowStart: number }>();
const RATE_LIMIT_MAX = 60;
const RATE_LIMIT_WINDOW_MS = 60000;

function checkRateLimit(tenantId: string, tool: string): { ok: true } | { ok: false; retryAfter: number } {
  const key = tenantId + ":" + tool;
  const now = Date.now();
  const entry = rateLimitStore.get(key);
  if (!entry || now - entry.windowStart > RATE_LIMIT_WINDOW_MS) {
    rateLimitStore.set(key, { count: 1, windowStart: now });
    return { ok: true };
  }
  entry.count += 1;
  if (entry.count > RATE_LIMIT_MAX) {
    return { ok: false, retryAfter: RATE_LIMIT_WINDOW_MS - (now - entry.windowStart) };
  }
  return { ok: true };
}

async function auditToolExecution(env: Env, tenantId: string, tool: string, params: Record<string, unknown>, success: boolean, error?: string): Promise<void> {
  try {
    await env.DB.prepare(
      "INSERT INTO audit_logs (id, tenant_id, actor, action, resource, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
    ).bind(crypto.randomUUID(), tenantId, "mcp", "tool." + tool, tool,
      JSON.stringify({ parameter_names: Object.keys(params), success, error: error ? "tool_failed" : undefined }), Date.now()).run();
  } catch { }
}

function jsonResponse(payload: unknown, status?: number, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(payload), { status: status ?? 200, headers: { "Content-Type": "application/json", ...headers } });
}

async function authenticateTenantKey(env: Env, apiKey: string): Promise<string | null> {
  if (apiKey.length < 8) return null;
  try {
    const row = await env.DB.prepare(
      "SELECT t.id, k.key_hash, t.is_active, k.is_active AS key_active " +
      "FROM tenants t JOIN api_keys k ON k.tenant_id = t.id " +
      "WHERE k.key_prefix = ? LIMIT 1",
    ).bind(apiKey.slice(0, 8)).first() as Record<string, unknown> | null;
    if (!row || Number(row.is_active) !== 1 || Number(row.key_active) !== 1) return null;
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(apiKey));
    const hash = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
    return hash === row.key_hash ? String(row.id) : null;
  } catch {
    return null;
  }
}

async function callApiWorker(env: Env, path: string, method: "GET" | "POST", body: unknown,
                             tenantApiKey: string, idempotencyKey?: string): Promise<Response> {
  const headers: Record<string, string> = { "X-Api-Key": tenantApiKey };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const isMultipart = typeof FormData !== "undefined" && body instanceof FormData;
  if (method === "POST" && body && !isMultipart) headers["Content-Type"] = "application/json";
  const init: RequestInit = { method, headers };
  if (method === "POST" && body) init.body = isMultipart ? body as FormData : JSON.stringify(body);
  return fetch(env.API_WORKER_URL + path, init);
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname !== "/mcp") {
      return new Response("MCP Server", { status: 200 });
    }

    const auth = request.headers.get("Authorization") || "";
    const token = auth.replace(/^Bearer\s/i, "").trim();
    const authenticatedTenantId = token ? await authenticateTenantKey(env, token) : null;
    if (!authenticatedTenantId) {
      return jsonResponse({ error: "unauthorized" }, 401);
    }

    let body: JsonRpcRequest;
    try {
      body = (await request.json()) as JsonRpcRequest;
    } catch {
      return jsonResponse(jsonRpcError(null, -32700, "Parse error"), 400);
    }

    const { method, id, params } = body;

    if (method === "tools/list") {
      const tools = [
        { name: "search_runbooks", description: "Search runbooks (tenant-scoped)", inputSchema: { type: "object", properties: { query: { type: "string" }, topK: { type: "number" }, tenant_id: { type: "string" } }, required: ["query", "tenant_id"] } },
        { name: "get_incident", description: "Get an incident by id (tenant-scoped)", inputSchema: { type: "object", properties: { incident_id: { type: "string" }, tenant_id: { type: "string" } }, required: ["incident_id", "tenant_id"] } },
        { name: "find_similar_incidents", description: "Find similar incidents by service (tenant-scoped)", inputSchema: { type: "object", properties: { service: { type: "string" }, limit: { type: "number" }, tenant_id: { type: "string" } }, required: ["service", "tenant_id"] } },
        { name: "get_triage_report", description: "Get latest triage report for an incident (tenant-scoped)", inputSchema: { type: "object", properties: { incident_id: { type: "string" }, tenant_id: { type: "string" } }, required: ["incident_id", "tenant_id"] } },
        { name: "upload_document", description: "Upload a document", inputSchema: { type: "object", properties: { filename: { type: "string" }, content: { type: "string" }, idempotency_key: { type: "string" }, tenant_id: { type: "string" } }, required: ["filename", "content", "idempotency_key", "tenant_id"] } },
        { name: "ask_question", description: "Ask a question with citations", inputSchema: { type: "object", properties: { question: { type: "string" }, idempotency_key: { type: "string" }, tenant_id: { type: "string" } }, required: ["question", "idempotency_key", "tenant_id"] } },
        { name: "list_documents", description: "List documents for the tenant", inputSchema: { type: "object", properties: { tenant_id: { type: "string" } }, required: ["tenant_id"] } },
      ];
      return jsonResponse(jsonRpc(id, { tools }));
    }

    if (method !== "tools/call") {
      return jsonResponse(jsonRpcError(id, -32601, "Method not found: " + method), 404);
    }

    const args = (params || {}) as Record<string, unknown>;
    const toolName = (args as { name?: string }).name;
    const toolArgs = (args as { arguments?: Record<string, unknown> }).arguments || {};
    const requestedTenantId = typeof toolArgs.tenant_id === "string" ? toolArgs.tenant_id : "";
    const tenantId = authenticatedTenantId;

    if (!toolName || typeof toolName !== "string" || !TOOL_NAMES.has(toolName)) {
      await auditToolExecution(env, tenantId, String(toolName ?? "unknown"), toolArgs, false, "unknown_tool");
      return jsonResponse(jsonRpcError(id, -32601, "Method not found: " + toolName), 404);
    }

    const limit = checkRateLimit(tenantId, toolName);
    if (!limit.ok) {
      await auditToolExecution(env, tenantId, toolName, toolArgs, false, "rate_limited");
      return jsonResponse(jsonRpcError(id, -32603, "Rate limit exceeded for tool " + toolName), 429, { "Retry-After": String(Math.ceil(limit.retryAfter / 1000)) });
    }

    const validation = validateInput(toolName, toolArgs);
    if (!validation.ok) {
      await auditToolExecution(env, tenantId, toolName, toolArgs, false, validation.error.message);
      return jsonResponse(jsonRpcError(id, validation.error.code, validation.error.message), 400);
    }
    const p = validation.params;
    if (requestedTenantId !== authenticatedTenantId) {
      await auditToolExecution(env, tenantId, toolName, toolArgs, false, "tenant_mismatch");
      return jsonResponse(jsonRpcError(id, -32001, "Tenant does not match authenticated API key"), 403);
    }

    try {
      let result: unknown;
      switch (toolName) {
        case "search_runbooks": {
          const query = String(p.query);
          const topK = Math.max(1, Math.min(20, Number(p.topK) || 5));
          let vector: number[] | null = null;
          if (env.AI) {
            try {
              const embed = await env.AI.run("@cf/qwen/qwen3-embedding-0.6b", { text: [query] });
              const v = (embed as any).vectors?.[0];
              if (Array.isArray(v)) vector = v as number[];
            } catch { }
          }
          const matches: Array<{ document_id: string; chunk_id: string | null; content: string; score: number; version: number }> = [];
          const seen = new Set<string>();
          if (vector) {
            try {
              const raw = await env.VECTORIZE_INDEX.query({ vector, topK, returnMetadata: true, filter: { tenant_id: tenantId } } as any);
              for (const m of (raw as any).matches ?? []) {
                const meta = m.metadata ?? {};
                const docId = meta.document_id;
                const key = "vec:" + docId + ":" + meta.chunk_id;
                if (seen.has(key)) continue;
                seen.add(key);
                matches.push({ document_id: docId, chunk_id: meta.chunk_id, content: meta.content ?? "", score: Number(m.score ?? 0), version: Number(meta.version ?? 1) });
              }
            } catch { }
          }
          try {
            const fts = await env.DB.prepare("SELECT d.id, d.filename, d.content, bm25(documents_fts) AS rank FROM documents_fts JOIN documents d ON d.rowid = documents_fts.rowid WHERE documents_fts MATCH ? AND d.tenant_id = ? ORDER BY rank LIMIT ?").bind(query, tenantId, topK).all();
            const rows = (fts as any).results as Array<[string, string, string, number]>;
            for (const r of rows) {
              const key = "fts:" + r[0];
              if (seen.has(key)) continue;
              seen.add(key);
              matches.push({ document_id: r[0], chunk_id: null, content: r[2], score: 1 / (1 + r[3]), version: 1 });
            }
          } catch { }
          matches.sort((a, b) => b.score - a.score);
          result = { matches: matches.slice(0, topK), count: matches.length };
          break;
        }
        case "get_incident": {
          const res = await callApiWorker(env, "/api/v1/incidents/" + String(p.incident_id), "GET", null, token);
          const data = (await res.json()) as { incident?: unknown; error?: unknown };
          if (!res.ok) { result = { error: data.error ?? { code: res.status, message: "failed" }, status: res.status }; }
          else { result = { incident: data.incident }; }
          break;
        }
        case "find_similar_incidents": {
          const service = String(p.service);
          const limit = Math.max(1, Math.min(50, Number(p.limit) || 5));
          const res = await env.DB.prepare("SELECT id FROM incidents WHERE tenant_id = ? AND service = ? ORDER BY created_at DESC LIMIT ?").bind(tenantId, service, limit).all();
          const rows = (res as any).results as Array<[string]>;
          result = { service, similar_incidents: rows.map((r) => r[0]), count: rows.length };
          break;
        }
        case "get_triage_report": {
          const res = await env.DB.prepare("SELECT id, status, summary, hypotheses, evidence, read_only_checks, citations, created_at FROM triage_reports WHERE incident_id = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 1").bind(String(p.incident_id), tenantId).first();
          if (!res) { result = { error: { code: 404, message: "no triage report for incident" }, status: 404 }; }
          else {
            const row = res as unknown as [string, string, string, string, string, string, string, number];
            result = { report_id: row[0], incident_id: String(p.incident_id), status: row[1], summary: row[2], hypotheses: row[3], evidence: row[4], read_only_checks: row[5], citations: row[6], created_at: row[7] };
          }
          break;
        }
        case "upload_document": {
          const form = new FormData();
          form.append("file", new Blob([String(p.content)], { type: "text/plain" }), String(p.filename));
          const res = await callApiWorker(env, "/api/v1/documents", "POST", form,
            token, String(p.idempotency_key));
          const data = (await res.json()) as { status?: string; document_id?: string; error?: unknown };
          if (!res.ok) { result = { error: data.error ?? { code: res.status, message: "failed" }, status: res.status }; }
          else { result = { status: data.status, document_id: data.document_id }; }
          break;
        }
        case "ask_question": {
          const res = await callApiWorker(env, "/api/v1/question", "POST",
            { question: String(p.question) }, token, String(p.idempotency_key));
          const data = (await res.json()) as { answer?: string; citations?: unknown[]; tokens_used?: number; error?: unknown };
          if (!res.ok) { result = { error: data.error ?? { code: res.status, message: "failed" }, status: res.status }; }
          else { result = { answer: data.answer, citations: data.citations, tokens_used: data.tokens_used }; }
          break;
        }
        case "list_documents": {
          const res = await callApiWorker(env, "/api/v1/documents", "GET", null, token);
          const data = (await res.json()) as { documents?: unknown[]; error?: unknown };
          if (!res.ok) { result = { error: data.error ?? { code: res.status, message: "failed" }, status: res.status }; }
          else { result = { documents: data.documents }; }
          break;
        }
        default: {
          await auditToolExecution(env, tenantId, toolName, toolArgs, false, "unknown_tool");
          return jsonResponse(jsonRpcError(id, -32601, "Method not found: " + toolName), 404);
        }
      }
      await auditToolExecution(env, tenantId, toolName, toolArgs, true);
      return jsonResponse(jsonRpc(id, result));
    } catch (err) {
      await auditToolExecution(env, tenantId, toolName, toolArgs, false, String(err));
      return jsonResponse(jsonRpcError(id, -32603, "Internal error: " + (err instanceof Error ? err.message : String(err))), 500);
    }
  }
};
