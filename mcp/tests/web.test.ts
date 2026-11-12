// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

const ids = [
  "apiKeyStatus", "docList", "docListLoading", "tab-main", "tab-health",
  "healthDashboard", "healthLoading", "quotaDashboard", "quotaLoading",
  "btnRefreshHealth", "btnSaveKey", "btnClearKey", "apiKeyInput",
];

async function startApp() {
  vi.resetModules();
  await import("../../web/app.js");
  await vi.waitFor(() => expect(document.getElementById("docListLoading")?.hidden).toBe(true));
}

beforeEach(() => {
  localStorage.clear();
  document.body.innerHTML = ids.map((id) => `<div id="${id}"></div>`).join("");
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
});
