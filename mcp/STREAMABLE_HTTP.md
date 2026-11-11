# Standard MCP transport

`/mcp/v1` uses pinned official `@modelcontextprotocol/sdk@1.32.2`, stateless Streamable HTTP with JSON responses. SDK handles initialize/initialized, list and call without Worker-isolate session state. [SDK v1 server docs](https://ts.sdk.modelcontextprotocol.io/server).

`/mcp` retains its custom JSON-RPC contract with `Deprecation: true` and a successor link. `/mcp/v1` delegates discovery/calls to the same handler, preserving tenant key authentication, principal binding, D1 quota, audit and business rules. Cross-origin browser requests are rejected; SDK caps bodies at 1 MiB. Tenant keys remain the machine-to-machine auth contract; OAuth discovery is not implemented.

Run `npm ci`, `npm run typecheck`, `npm test -- --run`. Real SDK client tests initialize/list/call, reject bad credentials and preserve tenant mismatch. Bindings are fake: no live D1/Vectorize/Cloudflare claim. Existing development toolchain advisories remain unresolved; report production dependency audit separately.
