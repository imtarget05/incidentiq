(() => {
  "use strict";
  const API = window.location.origin;
  const $ = (id) => document.getElementById(id);
  const API_KEY_STORAGE_KEY = "incidentiq_api_key";

  // ── Tenant API key (sessionStorage mặc định; localStorage khi người dùng chọn) ──
  function readStoredKey() {
    try {
      // Ưu tiên key đã lưu trên máy (tương thích dữ liệu cũ), sau đó phiên hiện tại.
      return localStorage.getItem(API_KEY_STORAGE_KEY) || sessionStorage.getItem(API_KEY_STORAGE_KEY) || "";
    } catch (e) { return ""; }
  }
  function keyStoreIsLocal() {
    try { return !!localStorage.getItem(API_KEY_STORAGE_KEY); } catch (e) { return false; }
  }
  function persistKey(key, remember) {
    try {
      (remember ? localStorage : sessionStorage).setItem(API_KEY_STORAGE_KEY, key);
      // Xoá ở store còn lại để không bị lệch nguồn.
      (remember ? sessionStorage : localStorage).removeItem(API_KEY_STORAGE_KEY);
    } catch (e) { /* chế độ riêng tư có thể chặn storage */ }
  }
  function clearStoredKey() {
    try {
      localStorage.removeItem(API_KEY_STORAGE_KEY);
      sessionStorage.removeItem(API_KEY_STORAGE_KEY);
    } catch (e) { /* noop */ }
  }
  function getApiKey() { return readStoredKey(); }

  function updateApiKeyStatus() {
    const el = $("apiKeyStatus");
    if (el) {
      const key = getApiKey();
      if (key) {
        // Không bao giờ hiện full key — chỉ tiền tố/hậu tố đã che.
        el.textContent = "Đã cấu hình API key (" + key.slice(0, 4) + "…" + key.slice(-4) + ")";
        el.className = "hint ok";
      } else {
        el.textContent = "⚠ Chưa có API key — các yêu cầu sẽ bị từ chối (401)";
        el.className = "hint err";
      }
    }
    const cb = $("rememberKey");
    if (cb) cb.checked = keyStoreIsLocal();
  }

  function authHeaders(idem) {
    const key = getApiKey();
    if (!key) {
      const el = $("apiKeyMsg");
      if (el) { el.textContent = "Vui lòng nhập Tenant API key trước khi sử dụng."; el.className = "msg err"; }
    }
    return {
      "X-Api-Key": key,
      "Idempotency-Key": idem || "req-" + Date.now(),
    };
  }

  // ── Helpers chung ──────────────────────────────────────────────────────────
  function setStatus(text) { const el = $("status"); if (el) el.textContent = text; }

  function msg(id, text, kind) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "msg " + (kind || "");
  }

  function setBusy(btn, busy) {
    if (!btn) return;
    btn.disabled = busy;
    btn.classList.toggle("loading", busy);
    if (busy) btn.setAttribute("aria-busy", "true");
    else btn.removeAttribute("aria-busy");
  }

  // ── apiFetch: helper thống nhất cho mọi panel ─────────────────────────────
  // - Thử lại 1 lần sau 800ms khi lỗi mạng (retries, mặc định 1).
  // - Parse chuẩn lỗi {"error":{"code","message","request_id"}}.
  // - Trả về {ok:true,status,data} hoặc {ok:false,status?,error?|networkError?}.
  async function apiFetch(path, opts = {}, { retries = 1 } = {}) {
    let res;
    for (let attempt = 0; ; attempt++) {
      try {
        res = await fetch(API + path, opts);
        break;
      } catch (e) {
        if (attempt < retries) {
          await new Promise((r) => setTimeout(r, 800));
          continue;
        }
        return { ok: false, networkError: e };
      }
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* body rỗng / không phải JSON */ }
    if (res.ok) return { ok: true, status: res.status, data };
    const e = (data && data.error) || {};
    return {
      ok: false,
      status: res.status,
      error: {
        code: e.code || "HTTP_" + res.status,
        message: e.message || "Lỗi máy chủ (HTTP " + res.status + ")",
        request_id: e.request_id,
      },
    };
  }

  function errorLine(res) {
    if (res && res.networkError) {
      return "Lỗi kết nối: " + ((res.networkError && res.networkError.message) || "mạng");
    }
    let line = "Lỗi: " + ((res && res.error && res.error.message) || "không xác định");
    if (res && res.error && res.error.request_id) line += " (request_id: " + res.error.request_id + ")";
    return line;
  }

  function makeRetryBtn(retryFn) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn-retry";
    b.textContent = "Thử lại";
    b.addEventListener("click", retryFn);
    return b;
  }

  // Render lỗi vào một container div (span + nút Thử lại).
  function renderError(container, res, retryFn) {
    if (!container) return;
    container.textContent = "";
    const span = document.createElement("span");
    span.textContent = errorLine(res);
    container.appendChild(span);
    container.appendChild(makeRetryBtn(retryFn));
  }

  // Render lỗi vào một <ul> (dạng li, dùng cho docList / incTimeline).
  function renderListError(ul, res, retryFn) {
    if (!ul) return;
    ul.textContent = "";
    const li = document.createElement("li");
    li.className = "error-item";
    const span = document.createElement("span");
    span.textContent = errorLine(res);
    li.appendChild(span);
    li.appendChild(makeRetryBtn(retryFn));
    ul.appendChild(li);
  }

  async function health() {
    try {
      const r = await fetch(`${API}/health`);
      const d = await r.json();
      setStatus(d.status || "unknown");
    } catch (e) {
      setStatus("error");
    }
  }

  // ── Lưu / xoá API key ─────────────────────────────────────────────────────
  async function saveApiKey() {
    const key = $("apiKeyInput").value.trim();
    if (!key) { msg("apiKeyMsg", "Vui lòng nhập API key.", "err"); return; }
    const remember = !!( $("rememberKey") && $("rememberKey").checked );
    const btn = $("btnSaveKey");
    setBusy(btn, true);
    msg("apiKeyMsg", "Đang xác thực...", "");

    let outcome; // "ok" | "invalid" | "unverified"
    try {
      const r = await fetch(`${API}/api/v1/documents`, {
        headers: { "X-Api-Key": key, "Idempotency-Key": "val-" + Date.now() },
      });
      if (r.ok) outcome = "ok";
      else if (r.status === 401 || r.status === 403) outcome = "invalid";
      else outcome = "unverified"; // lỗi máy chủ bất ngờ → không coi là hợp lệ nhưng cho phép lưu
    } catch (e) {
      outcome = "unverified"; // lỗi mạng → cho phép lưu kèm cảnh báo
    }

    setBusy(btn, false);
    if (outcome === "ok") {
      persistKey(key, remember);
      $("apiKeyInput").value = "";
      msg("apiKeyMsg", "API key hợp lệ — đã lưu " + (remember ? "trên máy này (localStorage)." : "trong phiên này (sessionStorage)."), "ok");
      listDocs();
    } else if (outcome === "invalid") {
      msg("apiKeyMsg", "API key không hợp lệ (401) — chưa lưu.", "err");
    } else {
      persistKey(key, remember);
      $("apiKeyInput").value = "";
      msg("apiKeyMsg", "⚠ Không xác thực được (lỗi kết nối/máy chủ) — đã lưu nhưng chưa kiểm chứng.", "err");
    }
    updateApiKeyStatus();
  }

  function clearApiKey() {
    clearStoredKey();
    const input = $("apiKeyInput");
    if (input) input.value = "";
    msg("apiKeyMsg", "Đã xoá API key khỏi máy.", "ok");
    updateApiKeyStatus();
  }

  // ── Upload ────────────────────────────────────────────────────────────────
  async function uploadFile() {
    const input = $("fileInput");
    const file = input.files && input.files[0];
    if (!file) { msg("uploadMsg", "Chọn file trước.", "err"); return; }
    const btn = $("btnUpload");
    setBusy(btn, true);
    msg("uploadMsg", "Đang tải lên...", "");

    const fd = new FormData();
    fd.append("file", file);
    const idem = "doc-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);

    const res = await apiFetch(`/api/v1/documents`, {
      method: "POST",
      headers: authHeaders(idem),
      body: fd,
    }, { retries: 1 });
    setBusy(btn, false);

    if (res.ok) {
      msg("uploadMsg", "Đã tải lên: " + ((res.data && res.data.document_id) || ""), "ok");
      input.value = "";
      listDocs();
    } else {
      renderError($("uploadMsg"), res, uploadFile);
    }
  }

  // ── Hỏi đáp ───────────────────────────────────────────────────────────────
  async function ask() {
    const input = $("questionInput");
    const q = input.value.trim();
    if (!q) return;
    const btn = $("btnAsk");
    setBusy(btn, true);
    $("answer").textContent = "Đang xử lý...";
    $("citations").textContent = "";

    const res = await apiFetch(`/api/v1/question`, {
      method: "POST",
      headers: { ...authHeaders("q-" + Date.now()), "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    }, { retries: 1 });
    setBusy(btn, false);

    if (res.ok) {
      $("answer").textContent = (res.data && res.data.answer) || "(không có câu trả lời)";
      const cites = (res.data && res.data.citations) || [];
      $("citations").textContent = cites.length ? "Nguồn: " + cites.map((c) => "[" + c.id + "]").join(" ") : "";
    } else {
      $("answer").textContent = "";
      renderError($("answer"), res, ask);
    }
  }

  // ── Danh sách tài liệu ────────────────────────────────────────────────────
  async function listDocs() {
    const ul = $("docList");
    if (!ul) return;
    const btn = $("btnList");
    setBusy(btn, true);
    ul.textContent = "";
    const li = document.createElement("li");
    li.textContent = "Đang tải...";
    ul.appendChild(li);

    const res = await apiFetch(`/api/v1/documents`, { headers: authHeaders() }, { retries: 1 });
    setBusy(btn, false);
    if (!res.ok) { renderListError(ul, res, listDocs); return; }

    ul.textContent = "";
    const docs = (res.data && res.data.documents) || [];
    if (!docs.length) {
      const empty = document.createElement("li");
      empty.textContent = "(chưa có tài liệu)";
      ul.appendChild(empty);
      return;
    }
    docs.forEach((doc) => {
      const li = document.createElement("li");
      li.textContent = doc.filename + "  ·  " + doc.status;
      if (doc.error) li.textContent += "  ·  lỗi: " + doc.error;
      ul.appendChild(li);
    });
  }

  // ── Sự cố ─────────────────────────────────────────────────────────────────
  async function createIncident() {
    const title = ($("incTitle") && $("incTitle").value.trim()) || "";
    const severity = ($("incSeverity") && $("incSeverity").value.trim()) || "";
    const service = ($("incService") && $("incService").value.trim()) || "";
    const envv = ($("incEnv") && $("incEnv").value.trim()) || "";
    const idem = ($("incIdem") && $("incIdem").value.trim()) || "";
    const btn = $("btnCreateInc");
    setBusy(btn, true);
    msg("incMsg", "Đang tạo sự cố...", "");

    const res = await apiFetch(`/api/v1/incidents`, {
      method: "POST",
      headers: { ...authHeaders(idem), "Content-Type": "application/json" },
      body: JSON.stringify({ title, severity, service, environment: envv }),
    }, { retries: 1 });
    setBusy(btn, false);

    if (res.ok) {
      msg("incMsg", "", "");
      msg("incResult", "Đã tạo: " + res.data.incident_id + " (" + res.data.status + ")", "ok");
      if ($("incLookupId")) $("incLookupId").value = res.data.incident_id || "";
    } else {
      renderError($("incMsg"), res, createIncident);
    }
  }

  async function fetchTimeline(id) {
    const ul = $("incTimeline");
    if (!ul) return;
    ul.textContent = "";
    const li = document.createElement("li");
    li.textContent = "Đang tải timeline...";
    ul.appendChild(li);

    const res = await apiFetch(`/api/v1/incidents/${encodeURIComponent(id)}/timeline`, {
      headers: authHeaders(),
    }, { retries: 1 });
    ul.textContent = "";
    if (!res.ok) { renderListError(ul, res, () => fetchTimeline(id)); return; }

    const events = (res.data && res.data.events) || [];
    if (!events.length) {
      const empty = document.createElement("li");
      empty.textContent = "(chưa có sự kiện)";
      ul.appendChild(empty);
      return;
    }
    events.forEach((ev) => {
      const li = document.createElement("li");
      li.textContent = ev.created_at + " · " + ev.event_type
        + (ev.severity ? " · " + ev.severity : "")
        + (ev.service ? " · " + ev.service : "")
        + (ev.logs ? " · logs: " + ev.logs : "");
      ul.appendChild(li);
    });
  }

  async function lookupIncident() {
    const id = $("incLookupId").value.trim();
    if (!id) { msg("incMsg", "Nhập ID sự cố cần xem.", "err"); return; }
    const btn = $("btnLookupInc");
    setBusy(btn, true);
    $("incDetail").textContent = "Đang tải...";
    $("incTimeline").textContent = "";

    const res = await apiFetch(`/api/v1/incidents/${encodeURIComponent(id)}`, {
      headers: authHeaders(),
    }, { retries: 1 });
    setBusy(btn, false);

    if (!res.ok) {
      const d = $("incDetail");
      d.textContent = "";
      renderError(d, res, lookupIncident);
      $("incTimeline").textContent = "";
      return;
    }
    const inc = res.data && res.data.incident;
    if (!inc) { $("incDetail").textContent = "(không tìm thấy sự cố)"; return; }

    // Dựng DOM bằng textContent để dữ liệu từ API không được chèn như HTML.
    const d = $("incDetail");
    d.textContent = "";
    [
      ["ID", inc.id], ["Tiêu đề", inc.title], ["Severity", inc.severity],
      ["Status", inc.status], ["Dịch vụ", inc.service], ["Môi trường", inc.environment],
      ["Phiên bản", inc.version], ["Tạo", inc.created_at],
    ].forEach(([label, value]) => {
      const row = document.createElement("div");
      const b = document.createElement("b");
      b.textContent = label + ": ";
      row.appendChild(b);
      row.appendChild(document.createTextNode(value == null ? "" : String(value)));
      d.appendChild(row);
    });
    fetchTimeline(id);
  }

  // ── Wiring ────────────────────────────────────────────────────────────────
  const on = (id, ev, fn) => { const el = $(id); if (el) el.addEventListener(ev, fn); };

  on("btnUpload", "click", uploadFile);
  on("btnAsk", "click", ask);
  on("questionInput", "keydown", (e) => { if (e.key === "Enter") ask(); });
  on("btnList", "click", listDocs);
  on("btnCreateInc", "click", createIncident);
  on("incIdem", "keydown", (e) => { if (e.key === "Enter") createIncident(); });
  on("btnLookupInc", "click", lookupIncident);
  on("incLookupId", "keydown", (e) => { if (e.key === "Enter") lookupIncident(); });

  on("btnSaveKey", "click", saveApiKey);
  on("apiKeyInput", "keydown", (e) => { if (e.key === "Enter") saveApiKey(); });
  on("btnClearKey", "click", clearApiKey);
  on("btnShowKey", "click", () => {
    const input = $("apiKeyInput");
    if (!input) return;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    const btn = $("btnShowKey");
    if (btn) btn.textContent = show ? "🙈" : "👁";
  });

  health();
  updateApiKeyStatus();
  listDocs();
})();
