// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

const ids = [
  "apiKeyStatus", "docList", "docListLoading", "tab-main", "tab-health",
  "healthDashboard", "healthLoading", "quotaDashboard", "quotaLoading",
  "btnRefreshHealth", "btnSaveKey", "btnClearKey", "apiKeyInput",
  "btnAsk", "questionInput", "answer", "citations", "answerLoading", "answerError", "btnRetryAsk",
  "btnCreateInc", "incTitle", "incSeverity", "incService", "incEnv", "incIdem", "incMsg", "incResult", "incLookupId",
  "btnLookupInc", "incDetail", "incTimeline", "incLookupError", "btnRetryLookup",
  "btnUpload", "fileInput", "uploadMsg", "btnList",
];

async function startApp() {
  vi.resetModules();
  await import("../../web/app.js");
  await new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
  localStorage.clear();
  document.body.innerHTML = ids.map((id) => {
    const tag = id === "docList" || id === "incTimeline" ? "ul" : id.startsWith("btn") ? "button" :
      id.endsWith("Input") || ["incTitle", "incSeverity", "incService", "incEnv", "incIdem", "incLookupId"].includes(id) ? "input" : "div";
    return `<${tag} id="${id}"></${tag}>`;
  }).join("");
  vi.stubGlobal("crypto", { randomUUID: () => "uuid-123" });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("/documents")) return { json: async () => ({ documents: [] }) };
    if (url.includes("/health/ready")) return { json: async () => ({ status: "ok", checks: { d1: "ok" } }) };
    if (url.includes("/metrics/quota")) return { json: async () => ({ ai_daily_count: 25, daily_ai_limit: 100 }) };
    throw new Error(`Unexpected URL: ${url}`);
  }));
});

describe("web dashboard", () => {
  it("renders remote document fields as text nodes", async () => {
    localStorage.setItem("incidentiq_api_key", "secret-key");
    const malicious = '<img src=x onerror="alert(1)">';
    vi.stubGlobal("fetch", vi.fn(async () => ({
      json: async () => ({ documents: [{ filename: malicious, status: malicious, error: malicious }] }),
    })));
    await startApp();
    const item = document.querySelector("#docList li");
    expect(item?.querySelector("strong")?.textContent).toBe(malicious);
    expect(item?.querySelector(".meta")?.textContent).toContain(malicious);
    expect(item?.querySelector("img")).toBeNull();
  });

  it("shows health and quota with authenticated request", async () => {
    localStorage.setItem("incidentiq_api_key", "secret-key");
    await startApp();
    document.getElementById("btnRefreshHealth")?.click();
    await vi.waitFor(() => expect(document.getElementById("healthDashboard")?.textContent).toContain("Overall"));
    expect(document.getElementById("quotaDashboard")?.textContent).toContain("25 / 100");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining("/metrics/quota"),
      expect.objectContaining({ headers: expect.objectContaining({ "Idempotency-Key": "req-uuid-123" }) }),
    );
  });

  it("keeps the API key out of the page and clears it on request", async () => {
    await startApp();
    const input = document.getElementById("apiKeyInput") as HTMLInputElement;
    input.value = "abcdef123456";
    document.getElementById("btnSaveKey")?.click();
    expect(localStorage.getItem("incidentiq_api_key")).toBe("abcdef123456");
    expect(input.value).toBe("");
    expect(document.getElementById("apiKeyStatus")?.textContent).toContain("abcd…3456");
    document.getElementById("btnClearKey")?.click();
    expect(localStorage.getItem("incidentiq_api_key")).toBeNull();
  });

  it("renders an answer and citations as text", async () => {
    localStorage.setItem("incidentiq_api_key", "secret-key");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true,
      json: async () => url.includes("/question") ?
        { answer: "Recovered service", citations: [{ id: "runbook-1" }] } : { documents: [] },
    })));
    await startApp();
    (document.getElementById("questionInput") as HTMLInputElement).value = "How to recover?";
    document.getElementById("btnAsk")?.click();
    await vi.waitFor(() => expect(document.getElementById("answer")?.textContent).toBe("Recovered service"));
    expect(document.getElementById("citations")?.textContent).toContain("[runbook-1]");
  });

  it("creates and looks up an incident", async () => {
    localStorage.setItem("incidentiq_api_key", "secret-key");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/documents")) return { ok: true, json: async () => ({ documents: [] }) };
      if (url.endsWith("/timeline")) return { ok: true, json: async () => ({ events: [{ created_at: 1, event_type: "created" }] }) };
      if (url.endsWith("/incidents/i-1")) return { ok: true, json: async () => ({ incident: { id: "i-1", title: "Outage", severity: "HIGH", status: "OPEN", service: "api", environment: "prod", version: 1, created_at: 1 } }) };
      return { ok: true, json: async () => ({ incident_id: "i-1", status: "OPEN" }) };
    }));
    await startApp();
    for (const [id, value] of Object.entries({ incTitle: "Outage", incSeverity: "HIGH", incService: "api", incEnv: "prod", incIdem: "idem-1" })) {
      (document.getElementById(id) as HTMLInputElement).value = value;
    }
    document.getElementById("btnCreateInc")?.click();
    await vi.waitFor(() => expect(document.getElementById("incResult")?.textContent).toContain("i-1"));
    document.getElementById("btnLookupInc")?.click();
    await vi.waitFor(() => expect(document.getElementById("incDetail")?.textContent).toContain("Outage"));
    expect(document.getElementById("incTimeline")?.textContent).toContain("created");
  });

  it("does not submit protected actions without an API key", async () => {
    await startApp();
    document.getElementById("btnUpload")?.click();
    document.getElementById("btnAsk")?.click();
    document.getElementById("btnCreateInc")?.click();
    document.getElementById("btnLookupInc")?.click();
    expect(document.getElementById("uploadMsg")?.textContent).toContain("API key");
    expect(document.getElementById("answerError")?.textContent).toContain("API key");
    expect(document.getElementById("incMsg")?.textContent).toContain("API key");
    expect(document.getElementById("incLookupError")?.textContent).toContain("API key");
  });

  it("uploads a selected file with a unique idempotency key", async () => {
    localStorage.setItem("incidentiq_api_key", "secret-key");
    const requests = vi.fn(async (url: string, options?: RequestInit) => ({
      ok: true,
      json: async () => options?.method === "POST" ? { document_id: "d-1" } : { documents: [] },
    }));
    vi.stubGlobal("fetch", requests);
    await startApp();
    const input = document.getElementById("fileInput") as HTMLInputElement;
    Object.defineProperty(input, "files", { value: [new File(["runbook"], "runbook.txt")] });
    document.getElementById("btnUpload")?.click();
    await vi.waitFor(() => expect(document.getElementById("uploadMsg")?.textContent).toContain("d-1"));
    expect(requests).toHaveBeenCalledWith(
      expect.stringContaining("/documents"),
      expect.objectContaining({ method: "POST", headers: expect.objectContaining({ "Idempotency-Key": "doc-uuid-123" }) }),
    );
  });

  it("shows server errors and offers to retry a question", async () => {
    localStorage.setItem("incidentiq_api_key", "secret-key");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: !url.includes("/question"), status: 503,
      json: async () => url.includes("/question") ? { error: { message: "Unavailable" } } : { documents: [] },
    })));
    await startApp();
    (document.getElementById("questionInput") as HTMLInputElement).value = "What happened?";
    document.getElementById("btnAsk")?.click();
    await vi.waitFor(() => expect(document.getElementById("answerError")?.textContent).toContain("503: Unavailable"));
    expect(document.getElementById("btnRetryAsk")?.hidden).toBe(false);
  });
});
