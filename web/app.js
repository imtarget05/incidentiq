(() => {
  "use strict";
  const API = window.location.origin;
  const $ = (id) => document.getElementById(id);

  // ── Tab navigation ────────────────────────────────────────────────────────
  function showTab(tabId) {
    document.querySelectorAll("main.wrap").forEach((el) => {
      el.hidden = el.id !== tabId;
    });
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      const active = btn.dataset.tab === tabId;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", String(active));
    });
  }

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });

  // ── API Key management ──────────────────────────────────────────────────
  const API_KEY_STORAGE_KEY = "incidentiq_api_key";

  function getApiKey() {
    return localStorage.getItem(API_KEY_STORAGE_KEY) || "";
  }
  function setApiKey(key) {
    if (key) {
      localStorage.setItem(API_KEY_STORAGE_KEY, key);
    } else {
      localStorage.removeItem(API_KEY_STORAGE_KEY);
    }
    updateApiKeyStatus();
  }
  function updateApiKeyStatus() {
    const el = $("apiKeyStatus");
    const key = getApiKey();
    if (!el) return;
    if (key) {
      el.textContent = "✓ Key đã lưu (" + key.slice(0, 4) + "…" + key.slice(-4) + ")";
      el.className = "hint ok";
    } else {
      el.textContent = "⚠ Chưa có API key";
      el.className = "hint err";
    }
  }

  function authHeaders(idem) {
    return {
      "X-Api-Key": getApiKey(),
      "Idempotency-Key": idem || "req-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8),
    };
  }

  // ── Loading / UI helpers ────────────────────────────────────────────────
  function setLoading(btnEl, loadingEl, loading) {
    if (btnEl) btnEl.disabled = loading;
    const spinner = btnEl && btnEl.querySelector(".spinner");
    if (spinner) spinner.hidden = !loading;
    if (loadingEl) loadingEl.hidden = !loading;
  }
  function msg(id, text, kind) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "msg" + (kind ? " " + kind : "");
    if (el.hasAttribute("hidden")) el.removeAttribute("hidden");
  }
  function hideEl(id) {
    const el = $(id);
    if (el) el.hidden = true;
  }
  function showEl(id) {
    const el = $(id);
    if (el) el.removeAttribute("hidden");
  }

  // ── API fetch with retry ────────────────────────────────────────────────
  async function apiFetch(url, options = {}, retries = 1) {
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const r = await fetch(url, options);
        return r;
      } catch (err) {
        if (attempt >= retries) throw err;
        await new Promise((res) => setTimeout(res, 800 * (attempt + 1)));
      }
    }
  }

  // ── Tab navigation ──────────────────────────────────────────────────────
  const tabs = { main: $("tab-main"), health: $("tab-health") };
  const tabBtns = document.querySelectorAll(".tab-btn");

  function switchTab(name) {
    Object.entries(tabs).forEach(([k, el]) => { if (el) el.hidden = k !== name; });
    tabBtns.forEach((btn) => {
      const active = btn.dataset.tab === name;
      btn.classList.toggle("active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    if (name === "health") {
      loadHealth();
      loadQuota();
    }
  }
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // ── Health status ───────────────────────────────────────────────────────
  function statusClass(s) {
    if (s === "ok") return "status-ok";
    if (s === "degraded" || s === "unavailable") return "status-degraded";
    return "status-err";
  }
  function statusIcon(s) {
    if (s === "ok") return "✅";
    if (s === "degraded") return "⚠️";
    return "❌";
  }

  async function loadHealth() {
    setLoading(null, $("healthLoading"), true);
    $("healthDashboard").innerHTML = "";
    try {
      const r = await apiFetch(`${API}/health/ready`);
      const d = await r.json();
      const checks = d.checks || {};
      const cards = [
        { label: "Overall", value: d.status || "unknown" },
        ...Object.entries(checks).map(([k, v]) => ({ label: k, value: v })),
      ];
      $("healthDashboard").innerHTML = cards
        .map(({ label, value }) =>
          `<div class="health-card">
            <div class="label">${esc(label)}</div>
            <div class="value ${statusClass(value)}">${statusIcon(value)} ${esc(value)}</div>
          </div>`
        )
        .join("");
    } catch (e) {
      $("healthDashboard").innerHTML = `<p class="msg err">Không thể kết nối tới health endpoint: ${esc(e.message)}</p>`;
    } finally {
      setLoading(null, $("healthLoading"), false);
    }
  }

  async function loadQuota() {
    if (!getApiKey()) {
      $("quotaDashboard").innerHTML = `<p class="msg warn">Cần API key để xem quota.</p>`;
      return;
    }
    setLoading(null, $("quotaLoading"), true);
    $("quotaDashboard").innerHTML = "";
    try {
      const r = await apiFetch(`${API}/api/v1/metrics/quota`, { headers: authHeaders() });
      const d = await r.json();
      const used = d.ai_daily_count || 0;
      const limit = d.daily_ai_limit || 100;
      const pct = Math.min(100, Math.round((used / limit) * 100));
      const fillClass = pct >= 90 ? "err" : pct >= 70 ? "warn" : "";
      $("quotaDashboard").innerHTML = `
        <div class="health-card">
          <div class="label">AI Calls Today</div>
          <div class="value ${pct >= 90 ? "status-err" : pct >= 70 ? "status-degraded" : "status-ok"}">${used} / ${limit}</div>
          <div class="quota-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="AI quota">
            <div class="quota-bar-fill ${fillClass}" style="width:${pct}%"></div>
          </div>
          <div class="meta">${pct}% đã dùng hôm nay</div>
        </div>`;
    } catch (e) {
      $("quotaDashboard").innerHTML = `<p class="msg err">Không thể tải quota: ${esc(e.message)}</p>`;
    } finally {
      setLoading(null, $("quotaLoading"), false);
    }
  }

  // ── Upload ──────────────────────────────────────────────────────────────
  async function uploadFile() {
    if (!getApiKey()) { msg("uploadMsg", "Vui lòng nhập API key trước.", "err"); return; }
    const input = $("fileInput");
    const file = input.files && input.files[0];
    if (!file) { msg("uploadMsg", "Chọn file trước.", "err"); return; }
    const btn = $("btnUpload");
    setLoading(btn, null, true);
    msg("uploadMsg", "Đang tải lên…", "");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await apiFetch(`${API}/api/v1/documents`, {
        method: "POST",
        headers: authHeaders("doc-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8)),
        body: fd,
      }, 1);
      const d = await r.json();
      if (r.ok) {
        msg("uploadMsg", "✅ Đã tải lên: " + (d.document_id || ""), "ok");
        input.value = "";
        listDocs();
      } else {
        msg("uploadMsg", "❌ Lỗi: " + ((d.error && d.error.message) || r.status), "err");
      }
    } catch (e) {
      msg("uploadMsg", "❌ Lỗi kết nối: " + e.message, "err");
    } finally {
      setLoading(btn, null, false);
    }
  }

  // ── Ask ─────────────────────────────────────────────────────────────────
  let _lastQuestion = "";
  async function ask() {
    if (!getApiKey()) { showError("answerError", "Vui lòng nhập API key trước."); return; }
    const input = $("questionInput");
    const q = input.value.trim();
    if (!q) return;
    _lastQuestion = q;
    const btn = $("btnAsk");
    setLoading(btn, $("answerLoading"), true);
    $("answer").textContent = "";
    $("citations").textContent = "";
    hideEl("answerError");
    hideEl("btnRetryAsk");
    try {
      const r = await apiFetch(`${API}/api/v1/question`, {
        method: "POST",
        headers: { ...authHeaders("q-" + Date.now()), "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      }, 1);
      const d = await r.json();
      if (r.ok) {
        $("answer").textContent = d.answer || "(không có câu trả lời)";
        const cites = d.citations || [];
        $("citations").textContent = cites.length
          ? "Nguồn: " + cites.map((c) => "[" + c.id + "]").join(" ")
          : "";
      } else {
        showError("answerError", "Lỗi " + r.status + ": " + ((d.error && d.error.message) || "Unknown error"));
        showEl("btnRetryAsk");
      }
    } catch (e) {
      showError("answerError", "Lỗi kết nối: " + e.message);
      showEl("btnRetryAsk");
    } finally {
      setLoading(btn, $("answerLoading"), false);
    }
  }

  // ── List docs ───────────────────────────────────────────────────────────
  async function listDocs() {
    if (!getApiKey()) return;
    const ul = $("docList");
    const loadingEl = $("docListLoading");
    if (!ul) return;
    ul.innerHTML = "";
    setLoading(null, loadingEl, true);
    try {
      const r = await apiFetch(`${API}/api/v1/documents`, { headers: authHeaders() });
      const d = await r.json();
      setLoading(null, loadingEl, false);
      ul.innerHTML = "";
      (d.documents || []).forEach((doc) => {
        const li = document.createElement("li");
        const statusIcon = doc.status === "processed" ? "✅" : doc.status === "failed" ? "❌" : "⏳";
        li.innerHTML = `<strong>${esc(doc.filename)}</strong> <span class="meta">${statusIcon} ${esc(doc.status)}${doc.error ? " — " + esc(doc.error) : ""}</span>`;
        ul.appendChild(li);
      });
      if (!d.documents || !d.documents.length) {
        ul.innerHTML = "<li>Chưa có tài liệu nào.</li>";
      }
    } catch (e) {
      setLoading(null, loadingEl, false);
      ul.innerHTML = "<li class='msg err'>Lỗi tải danh sách: " + esc(e.message) + "</li>";
    }
  }

  // ── Incidents ───────────────────────────────────────────────────────────
  async function createIncident() {
    if (!getApiKey()) { msg("incMsg", "Vui lòng nhập API key trước.", "err"); return; }
    const title = $("incTitle").value.trim();
    const severity = $("incSeverity").value.trim();
    const service = $("incService").value.trim();
    const envv = $("incEnv").value.trim();
    const idem = $("incIdem").value.trim();
    if (!title || !severity || !service || !envv || !idem) {
      msg("incMsg", "Vui lòng điền đầy đủ các trường.", "err");
      return;
    }
    const btn = $("btnCreateInc");
    setLoading(btn, null, true);
    msg("incMsg", "Đang tạo sự cố…", "");
    try {
      const r = await apiFetch(`${API}/api/v1/incidents`, {
        method: "POST",
        headers: { ...authHeaders(idem), "Content-Type": "application/json" },
        body: JSON.stringify({ title, severity, service, environment: envv }),
      }, 1);
      const d = await r.json();
      if (r.ok) {
        msg("incResult", "✅ Đã tạo: " + d.incident_id + " (" + d.status + ")", "ok");
        msg("incMsg", "", "");
        $("incLookupId").value = d.incident_id || "";
      } else {
        msg("incMsg", "❌ Lỗi: " + ((d.error && d.error.message) || r.status), "err");
      }
    } catch (e) {
      msg("incMsg", "❌ Lỗi kết nối: " + e.message, "err");
    } finally {
      setLoading(btn, null, false);
    }
  }

  let _lastLookupId = "";
  async function lookupIncident() {
    if (!getApiKey()) { showError("incLookupError", "Vui lòng nhập API key trước."); return; }
    const id = $("incLookupId").value.trim();
    if (!id) { msg("incMsg", "Nhập ID sự cố cần xem.", "err"); return; }
    _lastLookupId = id;
    $("incDetail").textContent = "Đang tải…";
    $("incTimeline").innerHTML = "<li>Đang tải timeline…</li>";
    hideEl("incLookupError");
    hideEl("btnRetryLookup");
    try {
      const r = await apiFetch(`${API}/api/v1/incidents/${encodeURIComponent(id)}`, {
        headers: authHeaders(),
      });
      const d = await r.json();
      if (r.ok && d.incident) {
        const inc = d.incident;
        $("incDetail").innerHTML =
          `<strong>ID:</strong> ${esc(inc.id)}<br>` +
          `<strong>Tiêu đề:</strong> ${esc(inc.title)}<br>` +
          `<strong>Severity:</strong> ${esc(inc.severity)}&nbsp;&nbsp;<strong>Status:</strong> ${esc(inc.status)}<br>` +
          `<strong>Dịch vụ:</strong> ${esc(inc.service)}&nbsp;&nbsp;<strong>Môi trường:</strong> ${esc(inc.environment)}<br>` +
          `<strong>Phiên bản:</strong> ${esc(String(inc.version))}&nbsp;&nbsp;<strong>Tạo:</strong> ${esc(String(inc.created_at))}`;
        // Timeline
        const tr = await apiFetch(`${API}/api/v1/incidents/${encodeURIComponent(id)}/timeline`, {
          headers: authHeaders(),
        });
        const td = await tr.json();
        $("incTimeline").innerHTML = "";
        (td.events || []).forEach((ev) => {
          const li = document.createElement("li");
          li.textContent =
            String(ev.created_at) + " · " + ev.event_type +
            (ev.severity ? " · " + ev.severity : "") +
            (ev.service ? " · " + ev.service : "") +
            (ev.logs ? " · logs: " + ev.logs : "");
          $("incTimeline").appendChild(li);
        });
        if (!(td.events || []).length) $("incTimeline").innerHTML = "<li>(chưa có sự kiện)</li>";
      } else {
        $("incDetail").textContent = "";
        $("incTimeline").innerHTML = "";
        showError("incLookupError", "Lỗi " + r.status + ": " + ((d.error && d.error.message) || "Unknown"));
        showEl("btnRetryLookup");
      }
    } catch (e) {
      $("incDetail").textContent = "";
      $("incTimeline").innerHTML = "";
      showError("incLookupError", "Lỗi kết nối: " + e.message);
      showEl("btnRetryLookup");
    }
  }

  // ── Utilities ───────────────────────────────────────────────────────────
  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showError(id, text) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.removeAttribute("hidden");
  }

  // ── Event wiring ────────────────────────────────────────────────────────
  $("btnUpload")     && $("btnUpload").addEventListener("click", uploadFile);
  $("btnAsk")        && $("btnAsk").addEventListener("click", ask);
  $("btnList")       && $("btnList").addEventListener("click", listDocs);
  $("btnCreateInc")  && $("btnCreateInc").addEventListener("click", createIncident);
  $("btnLookupInc")  && $("btnLookupInc").addEventListener("click", lookupIncident);
  $("btnRetryAsk")   && $("btnRetryAsk").addEventListener("click", ask);
  $("btnRetryLookup") && $("btnRetryLookup").addEventListener("click", lookupIncident);
  $("btnRefreshHealth") && $("btnRefreshHealth").addEventListener("click", () => { loadHealth(); loadQuota(); });

  $("questionInput") && $("questionInput").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
  $("incIdem")       && $("incIdem").addEventListener("keydown", (e) => { if (e.key === "Enter") createIncident(); });
  $("incLookupId")   && $("incLookupId").addEventListener("keydown", (e) => { if (e.key === "Enter") lookupIncident(); });

  $("btnSaveKey") && $("btnSaveKey").addEventListener("click", () => {
    const key = $("apiKeyInput").value.trim();
    if (!key) { return; }
    setApiKey(key);
    $("apiKeyInput").value = "";
  });
  $("btnClearKey") && $("btnClearKey").addEventListener("click", () => {
    setApiKey("");
    $("apiKeyInput").value = "";
  });
  $("apiKeyInput") && $("apiKeyInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const key = $("apiKeyInput").value.trim();
      if (key) { setApiKey(key); $("apiKeyInput").value = ""; }
    }
  });

  // ── Init ────────────────────────────────────────────────────────────────
  updateApiKeyStatus();
  listDocs();
  // Auto-check health status every 60 s while on health tab.
  setInterval(() => {
    if (!$("tab-health").hidden) { loadHealth(); loadQuota(); }
  }, 60000);
})();
