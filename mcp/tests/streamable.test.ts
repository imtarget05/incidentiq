import { describe, it, expect } from "vitest";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import worker from "../src/index";

const key = "tenant-key-123456";
function env() {
  return {
    API_WORKER_URL: "https://api.invalid",
    VECTORIZE_INDEX: {},
    DB: {
      prepare(sql: string) {
        return {
          bind() {
            return {
              first: async () =>
                sql.includes("rate_limit_buckets")
                  ? { count: 1 }
                  : {
                      id: "t1",
                      key_hash:
                        "c37ceaee4eb09aadeecf0076a7a7fbefbe3f31564f4c0c7a6de7f563102135f8",
                      is_active: 1,
                      key_active: 1,
                    },
              run: async () => ({}),
              all: async () => ({ results: [] }),
            };
          },
        };
      },
    },
  } as any;
}
function connect(token = key) {
  const environment = env();
  const fetcher: typeof fetch = async (input, init) =>
    worker.fetch(new Request(input, init), environment, {} as any);
  const transport = new StreamableHTTPClientTransport(
    new URL("https://tools.invalid/mcp/v1"),
    {
      fetch: fetcher,
      requestInit: { headers: { Authorization: `Bearer ${token}` } },
    },
  );
  const client = new Client({ name: "interoperability-test", version: "1" });
  return { client, transport };
}
describe("official Streamable HTTP client", () => {
  it("initializes and lists legacy tools through the SDK", async () => {
    const { client, transport } = connect();
    await client.connect(transport);
    try {
      expect((await client.listTools()).tools.map((t) => t.name)).toContain(
        "search_runbooks",
      );
    } finally {
      await client.close();
    }
  });
  it("rejects invalid credentials during initialize", async () => {
    const { client, transport } = connect("wrong-key");
    await expect(client.connect(transport)).rejects.toThrow();
    await client.close();
  });
  it("preserves tenant rejection on call", async () => {
    const { client, transport } = connect();
    await client.connect(transport);
    try {
      const result = await client.callTool({
        name: "search_runbooks",
        arguments: { query: "secret", tenant_id: "foreign" },
      });
      expect(result.isError).toBe(true);
    } finally {
      await client.close();
    }
  });
  it("calls a tool using real SDK protocol and the existing dispatcher", async () => {
    const { client, transport } = connect();
    await client.connect(transport);
    try {
      const result = await client.callTool({
        name: "find_similar_incidents",
        arguments: { service: "api", tenant_id: "t1" },
      });
      expect(result.isError).not.toBe(true);
      expect(JSON.parse((result.content as any)[0].text)).toMatchObject({
        service: "api",
        similar_incidents: [],
      });
    } finally {
      await client.close();
    }
  });
  it("retains the deprecated custom adapter", async () => {
    const response = await worker.fetch(
      new Request("https://tools.invalid/mcp", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      }),
      env(),
      {} as any,
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("Deprecation")).toBe("true");
  });
});
