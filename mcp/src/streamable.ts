import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";

type LegacyCall = (method: string, params?: unknown) => Promise<Response>;

/** Official v1 SDK stateless transport: https://ts.sdk.modelcontextprotocol.io/server */
export async function streamableRequest(
  request: Request,
  call: LegacyCall,
): Promise<Response> {
  // Reuse existing authentication and discovery before accepting initialize.
  const discovery = await call("tools/list");
  if (!discovery.ok) return discovery;
  if (
    request.headers.has("Origin") &&
    request.headers.get("Origin") !== new URL(request.url).origin
  ) {
    return new Response("Origin forbidden", { status: 403 });
  }
  const listing = (await discovery.json()) as { result: { tools: Tool[] } };
  const server = new Server(
    { name: "incidentiq", version: "1.0.0" },
    { capabilities: { tools: {} } },
  );
  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: listing.result.tools,
  }));
  server.setRequestHandler(CallToolRequestSchema, async ({ params }) => {
    const response = await call("tools/call", params);
    const payload = (await response.json()) as {
      result?: unknown;
      error?: unknown;
    };
    const result = payload.result as
      | { error?: unknown; status?: number }
      | undefined;
    return {
      content: [
        { type: "text", text: JSON.stringify(payload.result ?? payload.error) },
      ],
      isError: !response.ok || !!payload.error || !!result?.error,
    };
  });
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
    maxRequestBodySize: 1024 * 1024,
  });
  await server.connect(transport);
  try {
    return await transport.handleRequest(request);
  } finally {
    await server.close();
  }
}
