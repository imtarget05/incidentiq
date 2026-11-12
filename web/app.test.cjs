const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

test("document metadata from the API is rendered as text", async () => {
  const elements = new Map();
  const makeElement = () => ({
    children: [],
    hidden: false,
    append(...children) { this.children.push(...children); },
    appendChild(child) { this.children.push(child); },
    hasAttribute() { return false; },
    removeAttribute() {},
  });
  for (const id of ["docList", "docListLoading", "apiKeyStatus"]) {
    elements.set(id, makeElement());
  }
  const document = {
    getElementById: (id) => elements.get(id) || null,
    querySelectorAll: () => [],
    createElement: () => makeElement(),
  };
  const payload = '<img src=x onerror="alert(1)">';
  const context = {
    document,
    window: { location: { origin: "https://example.test" } },
    localStorage: { getItem: () => "test-key" },
    fetch: async () => ({ json: async () => ({ documents: [{ filename: payload, status: payload, error: payload }] }) }),
    setInterval: () => 0,
    setTimeout,
    crypto,
  };
  vm.runInNewContext(readFileSync(path.join(__dirname, "app.js"), "utf8"), context);
  await new Promise(setImmediate);
  const [item] = elements.get("docList").children;
  assert.equal(item.innerHTML, undefined);
  assert.equal(item.children[0].textContent, payload);
  assert.equal(item.children[2].textContent, `⏳ ${payload} — ${payload}`);
});
