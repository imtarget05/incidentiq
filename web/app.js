(() => {
  const API = window.location.origin;
  const $ = (id) => document.getElementById(id);

  function setStatus(text) { const el = $("status"); if (el) el.textContent = text; }
  function msg(id, text, kind) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "msg " + (kind || "");
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

  async function uploadFile() {
    const input = $("fileInput");
    const file = input.files && input.files[0];
    if (!file) { msg("uploadMsg", "Chọn file trước.", "err"); return; }
    const btn = $("btnUpload"); btn.disabled = true;
    msg("uploadMsg", "Đang tải lên...", "");

    const idempotencyKey = "doc-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);
    const fd = new FormData();
    fd.append("file", file);

    try {
      const r = await fetch(`${API}/api/v1/documents`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: fd,
      });
      const d = await r.json();
      if (r.ok) {
        msg("uploadMsg", "Đã tải lên: " + (d.document_id || ""), "ok");
        input.value = "";
        listDocs();
      } else {
        msg("uploadMsg", "Lỗi: " + (d.error && d.error.message || r.status), "err");
      }
    } catch (e) {
      msg("uploadMsg", "Lỗi kết nối: " + e.message, "err");
    } finally {
      btn.disabled = false;
    }
  }

  async function ask() {
    const input = $("questionInput");
    const q = input.value.trim();
    if (!q) return;
    const btn = $("btnAsk"); btn.disabled = true;
    $("answer").textContent = "Đang xử lý...";
    $("citations").textContent = "";
    const idempotencyKey = "q-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8);

    try {
      const r = await fetch(`${API}/api/v1/question`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: JSON.stringify({ question: q }),
      });
      const d = await r.json();
      if (r.ok) {
        $("answer").textContent = d.answer || "(không có câu trả lời)";
        const cites = d.citations || [];
        $("citations").textContent = cites.length ? "Nguồn: " + cites.map(c => "[" + c.id + "]").join(" ") : "";
      } else {
        $("answer").textContent = "Lỗi: " + (d.error && d.error.message || r.status);
      }
    } catch (e) {
      $("answer").textContent = "Lỗi kết nối: " + e.message;
    } finally {
      btn.disabled = false;
    }
  }

  async function listDocs() {
    const ul = $("docList");
    if (!ul) return;
    ul.innerHTML = "<li>Đang tải...</li>";
    try {
      const r = await fetch(`${API}/api/v1/documents`);
      const d = await r.json();
      ul.innerHTML = "";
      (d.documents || []).forEach(doc => {
        const li = document.createElement("li");
        li.textContent = doc.filename + "  ·  " + doc.status;
        if (doc.error) li.textContent += "  ·  lỗi: " + doc.error;
        ul.appendChild(li);
      });
    } catch (e) {
      ul.innerHTML = "<li>Lỗi tải danh sách.</li>";
    }
  }

  $("btnUpload") && $("btnUpload").addEventListener("click", uploadFile);
  $("btnAsk") && $("btnAsk").addEventListener("click", ask);
  $("btnList") && $("btnList").addEventListener("click", listDocs);
  $("questionInput") && $("questionInput").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });

  // Incident wiring
  const API_KEY = ""; // set your tenant API key here to use incident features end-to-end
  function incHeaders(idem) {
    return {
      "X-Api-Key": API_KEY,
      "Idempotency-Key": idem || "inc-" + Date.now(),
    };
  }
  async function createIncident() {
    const title = $("incTitle").value.trim();
    const severity = $("incSeverity").value.trim();
    const service = $("incService").value.trim();
    const envv = $("incEnv").value.trim();
    const idem = $("incIdem").value.trim();
    const btn = $("btnCreateInc"); btn.disabled = true;
    msg("incMsg", "Đang tạo sự cố...", "");
    try {
      const r = await fetch(`${API}/api/v1/incidents`, {
        method: "POST",
        headers: { ...incHeaders(idem), "Content-Type": "application/json" },
        body: JSON.stringify({ title, severity, service, environment: envv }),
      });
      const d = await r.json();
      if (r.ok) {
        msg("incResult", "Đã tạo: " + d.incident_id + " (" + d.status + ")", "ok");
        $("incLookupId").value = d.incident_id || "";
      } else {
        msg("incMsg", "Lỗi: " + ((d.error && d.error.message) || r.status), "err");
      }
    } catch (e) {
      msg("incMsg", "Lỗi kết nối: " + e.message, "err");
    } finally {
      btn.disabled = false;
    }
  }
  async function lookupIncident() {
    const id = $("incLookupId").value.trim();
    if (!id) { msg("incMsg", "Nhập ID sự cần xem.", "err"); return; }
    $("incDetail").textContent = "Đang tải...";
    $("incTimeline").innerHTML = "<li>Đang tải timeline...</li>";
    try {
      const r = await fetch(`${API}/api/v1/incidents/${id}`, {
        headers: incHeaders(),
      });
      const d = await r.json();
      if (r.ok && d.incident) {
        const inc = d.incident;
        $("incDetail").innerHTML =
          "<b>ID:</b> " + inc.id + "<br>" +
          "<b>Tiêu đề:</b> " + inc.title + "<br>" +
          "<b>Severity:</b> " + inc.severity + "  <b>Status:</b> " + inc.status + "<br>" +
          "<b>Dịch vụ:</b> " + inc.service + "  <b>Môi trường:</b> " + inc.environment + "<br>" +
          "<b>Phiên bản:</b> " + inc.version + "  <b>Tạo:</b> " + inc.created_at;
        // timeline
        const tr = await fetch(`${API}/api/v1/incidents/${id}/timeline`, { headers: incHeaders() });
        const td = await tr.json();
        $("incTimeline").innerHTML = "";
        (td.events || []).forEach(ev => {
          const li = document.createElement("li");
          li.textContent = ev.created_at + " · " + ev.event_type + (ev.severity ? " · " + ev.severity : "") + (ev.service ? " · " + ev.service : "");
          if (ev.logs) li.textContent += " · logs: " + ev.logs;
          $("incTimeline").appendChild(li);
        });
        if (!(td.events || []).length) $("incTimeline").innerHTML = "<li>(chưa có sự kiện)</li>";
      } else {
        $("incDetail").textContent = "Lỗi: " + ((d.error && d.error.message) || r.status);
        $("incTimeline").innerHTML = "";
      }
    } catch (e) {
      $("incDetail").textContent = "Lỗi kết nối: " + e.message;
      $("incTimeline").innerHTML = "";
    }
  }
  $("btnCreateInc") && $("btnCreateInc").addEventListener("click", createIncident);
  $("btnLookupInc") && $("btnLookupInc").addEventListener("click", lookupIncident);
  $("incIdem") && $("incIdem").addEventListener("keydown", (e) => { if (e.key === "Enter") createIncident(); });
  $("incLookupId") && $("incLookupId").addEventListener("keydown", (e) => { if (e.key === "Enter") lookupIncident(); });

  health();
  listDocs();
})();
