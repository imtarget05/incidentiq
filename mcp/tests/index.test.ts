import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

type Env = {
  DB: any;
  API_WORKER_URL: string;
  VECTORIZE_INDEX: any;
  AI: any;
};

const handler = (await import("../src/index.ts")).default as any;

function makeEnv(overrides: Partial<Env> = {}): Env {
  const db = {
    prepared: [] as Array<{ sql: string; params: unknown[] }>,
    allResult: [] as unknown[],
    firstResult: {
      id: "t1",
      key_hash: "c37ceaee4eb09aadeecf0076a7a7fbefbe3f31564f4c0c7a6de7f563102135f8",
      is_active: 1,
      key_active: 1,
    } as unknown | null,
    prepare(sql: string) {
      return {
        bind: (...params: unknown[]) => {
          this.prepared.push({ sql, params });
          return {
            all: () => this.allResult,
            first: () => this.firstResult,
            run: () => ({}),
          };
        },
      };
    },
  };
  const vectorize = {
    queryResult: { matches: [] as unknown[] },
    query(args: any) {
      return this.queryResult;
    },
  };
  const ai = {
    runResult: { vectors: [[0.1, 0.2, 0.3]] },
    run(model: string, inputs: any) {
      return this.runResult;
    },
  };
  return {
    DB: db,
    API_WORKER_URL: "https://api.workers.dev",
    VECTORIZE_INDEX: vectorize,
    AI: ai,
    ...overrides,
  };
}

const fetchCalls: Array<{ url: string; init: RequestInit }> = [];
let fetchImpl: ((input: string, init?: RequestInit) => Promise<Response>) | null = null;

const originalFetch = globalThis.fetch;

const AUTH_KEY_HASH = "c37ceaee4eb09aadeecf0076a7a7fbefbe3f31564f4c0c7a6de7f563102135f8";

type RateLimitBucket = { tenant_id: string; bucket_key: string; count: number; window_start: number };

// Stateful fake D1 for rate-limit tests: emulates the rate_limit_buckets table
// (UNIQUE(tenant_id, bucket_key)) including the INSERT ... ON CONFLICT ...
// RETURNING upsert and the plain SELECT fallback, backed by a Map that
// simulates a persistent D1 database shared across "isolates".
function makeRateLimitEnv(options: { seed?: RateLimitBucket[]; failRateLimit?: boolean } = {}): Env {
  const buckets = new Map<string, RateLimitBucket>();
  for (const b of options.seed ?? []) {
    buckets.set(`${b.tenant_id}|${b.bucket_key}`, { ...b });
  }
  const db = {
    buckets,
    prepared: [] as Array<{ sql: string; params: unknown[] }>,
    allResult: [] as unknown[],
    firstResult: { id: "t1", key_hash: AUTH_KEY_HASH, is_active: 1, key_active: 1 } as unknown | null,
    prepare(sql: string) {
      return {
        bind: (...params: unknown[]) => {
          this.prepared.push({ sql, params });
          if (sql.includes("rate_limit_buckets")) {
            if (options.failRateLimit) {
              const boom = () => { throw new Error("d1 unavailable"); };
              return { all: boom, first: boom, run: boom };
            }
            if (sql.includes("RETURNING")) {
              // INSERT ... VALUES (?, ?, ?, 1, ?) ... RETURNING count, window_start
              const key = `${params[1]}|${params[2]}`;
              const windowStart = Number(params[3]);
              const prev = buckets.get(key);
              const count = prev && prev.window_start === windowStart ? prev.count + 1 : 1;
              const row = { count, window_start: windowStart };
              buckets.set(key, row);
              return { all: () => ({}), first: () => row, run: () => ({}) };
            }
            // SELECT count, window_start WHERE tenant_id = ? AND bucket_key = ?
            const row = buckets.get(`${params[0]}|${params[1]}`) ?? null;
            return { all: () => ({}), first: () => row, run: () => ({}) };
          }
          return {
            all: () => this.allResult,
            first: () => this.firstResult,
            run: () => ({}),
          };
        },
      };
    },
  };
  const vectorize = {
    queryResult: { matches: [] as unknown[] },
    query(args: any) {
      return this.queryResult;
    },
  };
  const ai = {
    runResult: { vectors: [[0.1, 0.2, 0.3]] },
    run(model: string, inputs: any) {
      return this.runResult;
    },
  };
  return {
    DB: db,
    API_WORKER_URL: "https://api.workers.dev",
    VECTORIZE_INDEX: vectorize,
    AI: ai,
  } as Env;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

beforeEach(() => {
  fetchCalls.length = 0;
  fetchImpl = null;
  vi.stubGlobal(
    "fetch",
    async (input: string, init?: RequestInit) => {
      fetchCalls.push({ url: String(input), init });
      if (!fetchImpl) {
        return new Response(JSON.stringify({ documents: [] }), { status: 200 });
      }
      return fetchImpl(input, init);
    },
  );
});

afterEach(() => {
  vi.stubGlobal("fetch", originalFetch);
});

function rpcCall(env: Env, method: string, params: unknown, id = 1) {
  return handler.fetch(
    new Request("https://mcp.workers.dev/mcp", {
      method: "POST",
      headers: {
        Authorization: "Bearer tenant-key-123456",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
    }),
    env,
    {} as ExecutionContext,
  );
}

describe("MCP server", () => {
  it("tools/list returns all required tools", async () => {
    const env = makeEnv();
    const res = await rpcCall(env, "tools/list", {}, 1);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.jsonrpc).toBe("2.0");
    expect(body.id).toBe(1);
    const names = (body.result.tools as any[]).map((t) => t.name);
    for (const t of ["search_runbooks", "get_incident", "find_similar_incidents", "get_triage_report"]) {
      expect(names).toContain(t);
    }
  });

  it("rejects missing bearer token", async () => {
    const env = makeEnv();
    const res = await handler.fetch(
      new Request("https://mcp.workers.dev/mcp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
      }),
      env,
      {} as ExecutionContext,
    );
    expect(res.status).toBe(401);
  });

  it("rejects wrong bearer token", async () => {
    const env = makeEnv();
    const res = await handler.fetch(
      new Request("https://mcp.workers.dev/mcp", {
        method: "POST",
        headers: {
          Authorization: "Bearer wrong-secret",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
      }),
      env,
      {} as ExecutionContext,
    );
    expect(res.status).toBe(401);
  });

  it("search_runbooks calls Vectorize with tenant filter and returns matches", async () => {
    const env = makeEnv({
      VECTORIZE_INDEX: {
        queryResult: {
          matches: [
            {
              id: "vec-1",
              score: 0.9,
              metadata: {
                document_id: "doc-1",
                tenant_id: "t1",
                chunk_id: "doc-1-v1-0",
                content: "OOMKilled check memory limit",
                version: 1,
              },
            },
          ],
        },
        query(args: any) {
          expect(args.filter.tenant_id).toBe("t1");
          return this.queryResult;
        },
      },
    });
    const res = await rpcCall(
      env,
      "tools/call",
      { name: "search_runbooks", arguments: { query: "OOMKilled", topK: 5, tenant_id: "t1" } },
      2,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.error).toBeUndefined();
    const matches = (body.result.matches ?? []) as any[];
    expect(matches.length).toBeGreaterThanOrEqual(0);
  });

  it("search_runbooks missing required param returns -32602", async () => {
    const env = makeEnv();
    const res = await rpcCall(
      env,
      "tools/call",
      { name: "search_runbooks", arguments: { query: "OOMKilled" } },
      3,
    );
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error.code).toBe(-32602);
  });

  it("get_incident returns incident from API worker", async () => {
    fetchImpl = async () => {
      return new Response(
        JSON.stringify({ incident: { id: "inc-1", service: "payment-api", status: "OPEN" } }),
        { status: 200 },
      );
    };
    const env = makeEnv();
    env.DB.firstResult = { id: "t1", key_hash: await sha256Hex("tenant-key-123456"), is_active: 1, key_active: 1 };
    const res = await rpcCall(
      env,
      "tools/call",
      { name: "get_incident", arguments: { incident_id: "inc-1", tenant_id: "t1" } },
      4,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.result.incident.id).toBe("inc-1");
    expect(fetchCalls[0].url).toContain("/api/v1/incidents/inc-1");
    expect((fetchCalls[0].init.headers as any)["X-Api-Key"]).toBe("tenant-key-123456");
  });

  it("uploads documents as multipart and forwards the caller's idempotency key", async () => {
    fetchImpl = async () => new Response(
      JSON.stringify({ status: "uploaded", document_id: "doc-1" }),
      { status: 202 },
    );
    const env = makeEnv();
    const res = await rpcCall(env, "tools/call", {
      name: "upload_document",
      arguments: {
        filename: "runbook.md", content: "private runbook text",
        idempotency_key: "upload-request-1", tenant_id: "t1",
      },
    });

    expect(res.status).toBe(200);
    const headers = new Headers(fetchCalls[0].init.headers);
    expect(headers.get("Idempotency-Key")).toBe("upload-request-1");
    expect(headers.get("Content-Type")).toBeNull();
    const form = fetchCalls[0].init.body as FormData;
    const file = form.get("file") as File;
    expect(file.name).toBe("runbook.md");
    expect(await file.text()).toBe("private runbook text");
  });

  it("rejects a tool tenant that differs from the authenticated API-key tenant", async () => {
    const env = makeEnv();
    env.DB.firstResult = { id: "t1", key_hash: await sha256Hex("tenant-key-123456"), is_active: 1, key_active: 1 };
    const res = await rpcCall(env, "tools/call", {
      name: "search_runbooks",
      arguments: { query: "runbook", tenant_id: "tenant-2" },
    });

    expect(res.status).toBe(403);
    expect(fetchCalls).toHaveLength(0);
    expect(env.DB.prepared.some((entry) => entry.sql.includes("documents_fts"))).toBe(false);
  });

  it("rejects a tenant API key whose stored hash does not match", async () => {
    const env = makeEnv();
    env.DB.firstResult = { id: "t1", key_hash: "wrong-hash", is_active: 1, key_active: 1 };
    const res = await rpcCall(env, "tools/list", {});

    expect(res.status).toBe(401);
  });

  it("find_similar_incidents queries DB scoped by tenant", async () => {
    const env = makeEnv({
      DB: {
        ...makeEnv().DB,
        allResult: [["inc-2"], ["inc-3"]],
        prepare(sql: string) {
          if (sql.includes("api_keys")) return makeEnv().DB.prepare(sql);
          const all = this.allResult;
          return {
            bind: (...params: unknown[]) => {
              expect(params[0]).toBe("t1");
              expect(params[1]).toBe("payment-api");
              return {
                all: () => ({ results: all }),
                first: () => this.firstResult,
                run: () => ({}),
              };
            },
          };
        },
      },
    });
    const res = await rpcCall(
      env,
      "tools/call",
      { name: "find_similar_incidents", arguments: { service: "payment-api", tenant_id: "t1", limit: 5 } },
      5,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.result.similar_incidents).toEqual(["inc-2", "inc-3"]);
  });

  it("get_triage_report returns report from DB", async () => {
    const env = makeEnv({
      DB: {
        ...makeEnv().DB,
        firstResult: [
          "report-1",
          "ok",
          "summary text",
          "[]",
          "[]",
          "[]",
          "[]",
          Date.now(),
        ],
        prepare(sql: string) {
          if (sql.includes("api_keys")) return makeEnv().DB.prepare(sql);
          return {
            bind: (...params: unknown[]) => {
              expect(params[0]).toBe("inc-1");
              expect(params[1]).toBe("t1");
              return {
                all: () => this.allResult,
                first: () => this.firstResult,
                run: () => ({}),
              };
            },
          };
        },
      },
    });
    const res = await rpcCall(
      env,
      "tools/call",
      { name: "get_triage_report", arguments: { incident_id: "inc-1", tenant_id: "t1" } },
      6,
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.result.report_id).toBe("report-1");
    expect(body.result.status).toBe("ok");
  });

  it("unknown tool returns -32601", async () => {
    const env = makeEnv();
    const res = await rpcCall(
      env,
      "tools/call",
      { name: "delete_production", arguments: {} },
      7,
    );
    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.error.code).toBe(-32601);
  });

  it("rate limit returns 429 after exceeding max", async () => {
    const env = makeRateLimitEnv();
    const baseArgs = { name: "get_incident", arguments: { incident_id: "inc-1", tenant_id: "t1" } };
    // First 60 calls in the window are allowed.
    for (let i = 0; i < 60; i++) {
      const res = await rpcCall(env, "tools/call", baseArgs, 100 + i);
      expect(res.status).not.toBe(429);
    }
    const res = await rpcCall(env, "tools/call", baseArgs, 200);
    expect(res.status).toBe(429);
    const body = await res.json();
    expect(body.error.code).toBe(-32603);
    expect(res.headers.get("Retry-After")).toBeTruthy();
  });

  it("new rate limit window resets the counter", async () => {
    const base = 1_700_000_000_000;
    const baseWindow = base - (base % 60_000);
    const nextWindow = baseWindow + 60_000;
    const env = makeRateLimitEnv();
    const nowSpy = vi.spyOn(Date, "now").mockReturnValue(base);
    try {
      const baseArgs = { name: "get_incident", arguments: { incident_id: "inc-1", tenant_id: "t1" } };
      for (let i = 0; i < 60; i++) {
        const res = await rpcCall(env, "tools/call", baseArgs, 300 + i);
        expect(res.status).not.toBe(429);
      }
      const blocked = await rpcCall(env, "tools/call", baseArgs, 400);
      expect(blocked.status).toBe(429);
      expect(env.DB.buckets.get("t1|mcp:get_incident")).toEqual({ count: 61, window_start: baseWindow });

      // Advance into the next fixed window: counter resets.
      nowSpy.mockReturnValue(base + 61_000);
      const after = await rpcCall(env, "tools/call", baseArgs, 401);
      expect(after.status).toBe(200);
      expect(env.DB.buckets.get("t1|mcp:get_incident")).toEqual({ count: 1, window_start: nextWindow });
    } finally {
      nowSpy.mockRestore();
    }
  });

  it("rate limiter fails open when D1 is unavailable", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => { });
    try {
      const env = makeRateLimitEnv({ failRateLimit: true });
      const res = await rpcCall(
        env,
        "tools/call",
        { name: "get_incident", arguments: { incident_id: "inc-1", tenant_id: "t1" } },
        500,
      );
      // D1 failure must not block the tool call.
      expect(res.status).toBe(200);
      const warnLines = warnSpy.mock.calls.map((c) => String(c[0]));
      const dbErrorLine = warnLines.find((line) => line.includes("rate_limit.db_error"));
      expect(dbErrorLine).toBeTruthy();
      const parsed = JSON.parse(dbErrorLine as string);
      expect(parsed).toMatchObject({ event: "rate_limit.db_error", tenant_id: "t1", tool: "get_incident" });
    } finally {
      warnSpy.mockRestore();
    }
  });

  it("rate limit count persists across isolate restarts (D1 row is respected)", async () => {
    const base = 1_700_000_000_000;
    const baseWindow = base - (base % 60_000);
    const baseArgs = { name: "get_incident", arguments: { incident_id: "inc-1", tenant_id: "t1" } };
    const nowSpy = vi.spyOn(Date, "now").mockReturnValue(base);
    try {
      // Isolate A consumes 59 calls of the 60-call budget.
      const envA = makeRateLimitEnv();
      for (let i = 0; i < 59; i++) {
        const res = await rpcCall(envA, "tools/call", baseArgs, 600 + i);
        expect(res.status).toBe(200);
      }
      const stored = envA.DB.buckets.get("t1|mcp:get_incident");
      expect(stored).toEqual({ count: 59, window_start: baseWindow });

      // Isolate B is a brand-new env (fresh memory) whose D1 contains the
      // row written by isolate A: the persisted count must be respected.
      const envB = makeRateLimitEnv({
        seed: [{ tenant_id: "t1", bucket_key: "mcp:get_incident", ...(stored as RateLimitBucket) }],
      });
      const allowed = await rpcCall(envB, "tools/call", baseArgs, 700);
      expect(allowed.status).toBe(200); // 60th call still fits the budget
      const blocked = await rpcCall(envB, "tools/call", baseArgs, 701);
      expect(blocked.status).toBe(429); // 61st call rejected via persisted count
      expect(envB.DB.buckets.get("t1|mcp:get_incident")).toEqual({ count: 61, window_start: baseWindow });
    } finally {
      nowSpy.mockRestore();
    }
  });

  it("audit writes to DB for tool execution", async () => {
    const env = makeEnv({
      DB: {
        ...makeEnv().DB,
        runResult: null,
        prepare(sql: string) {
          if (sql.includes("audit_logs")) {
            return {
              bind: (...params: unknown[]) => {
                expect(params[2]).toBe("mcp");
                expect(params[3]).toBe("tool.search_runbooks");
                const metadata = JSON.parse(String(params[5]));
                expect(metadata).toEqual({ parameter_names: ["query", "tenant_id"], success: true });
                return {
                  all: () => [],
                  first: () => null,
                  run: () => ({}),
                };
              },
            };
          }
          return makeEnv().DB.prepare(sql);
        },
      },
    });
    const res = await rpcCall(
      env,
      "tools/call",
      { name: "search_runbooks", arguments: { query: "x", tenant_id: "t1" } },
      8,
    );
    expect(res.status).toBe(200);
  });

  it("unsupported JSON-RPC method returns -32601", async () => {
    const env = makeEnv();
    const res = await handler.fetch(
      new Request("https://mcp.workers.dev/mcp", {
        method: "POST",
        headers: {
          Authorization: "Bearer tenant-key-123456",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 9, method: "unknown.method", params: {} }),
      }),
      env,
      {} as ExecutionContext,
    );
    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.error.code).toBe(-32601);
  });
});
