/* BloodIQ frontend — plain JS, no build step. */
const API = ""; // same origin; the backend serves this page

const $ = (id) => document.getElementById(id);

const TOKEN_KEY = "bloodiq_token";
let currentUser = null;
let lastAiExplanation = null;
let lastReportId = null;

function authHeaders() {
  const t = localStorage.getItem(TOKEN_KEY);
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** Authenticated fetch. A 401 mid-session drops back to the login screen. */
async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: { ...(opts.headers || {}), ...authHeaders() },
  });
  if (res.status === 401 && currentUser) {
    logout();
    throw new Error("Session expired — please log in again.");
  }
  return res;
}

/* ---- Auth ---- */

function showAuth() {
  $("auth-view").classList.remove("hidden");
  $("app-view").classList.add("hidden");
  $("user-chip").classList.add("hidden");
}

function showApp(user) {
  currentUser = user;
  $("auth-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("user-chip").classList.remove("hidden");
  $("user-name").textContent = `👤 ${user.name}`;
  loadHistory();
  loadTrend();
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  currentUser = null;
  lastReportId = null;
  showAuth();
}

function authError(msg) {
  const el = $("auth-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

async function handleAuth(event, mode) {
  event.preventDefault();
  $("auth-error").classList.add("hidden");
  const btn = mode === "login" ? $("login-btn") : $("signup-btn");
  btn.disabled = true;
  try {
    const body =
      mode === "login"
        ? { email: $("login-email").value.trim(), password: $("login-password").value }
        : {
            name: $("signup-name").value.trim(),
            email: $("signup-email").value.trim(),
            password: $("signup-password").value,
          };
    const res = await fetch(`${API}/api/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `${mode} failed`);
    localStorage.setItem(TOKEN_KEY, data.access_token);
    showApp(data.user);
  } catch (err) {
    authError(err.message);
  } finally {
    btn.disabled = false;
  }
}

function switchAuthTab(mode) {
  const login = mode === "login";
  $("tab-login").classList.toggle("active", login);
  $("tab-signup").classList.toggle("active", !login);
  $("login-form").classList.toggle("hidden", !login);
  $("signup-form").classList.toggle("hidden", login);
  $("auth-error").classList.add("hidden");
}

async function initAuth() {
  $("tab-login").addEventListener("click", () => switchAuthTab("login"));
  $("tab-signup").addEventListener("click", () => switchAuthTab("signup"));
  $("login-form").addEventListener("submit", (e) => handleAuth(e, "login"));
  $("signup-form").addEventListener("submit", (e) => handleAuth(e, "signup"));
  $("logout-btn").addEventListener("click", logout);

  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    showAuth();
    return;
  }
  try {
    const res = await api("/api/auth/me");
    if (!res.ok) throw new Error("bad token");
    showApp(await res.json());
  } catch {
    localStorage.removeItem(TOKEN_KEY);
    showAuth();
  }
}

async function checkHealth() {
  const el = $("api-status");
  try {
    const res = await fetch(`${API}/api/health`);
    const data = await res.json();
    if (data.status === "ok") {
      el.textContent = "● connected";
      el.classList.add("ok");
    } else {
      throw new Error("bad status");
    }
  } catch {
    el.textContent = "● backend unreachable";
    el.classList.add("bad");
  }
}

function fmtRange(r) {
  if (r.ref_low == null && r.ref_high == null) return "—";
  if (r.ref_low == null) return `< ${r.ref_high}`;
  if (r.ref_high == null) return `> ${r.ref_low}`;
  return `${r.ref_low} – ${r.ref_high}`;
}

function renderResults(data) {
  $("results-card").classList.remove("hidden");
  const detail = data.extraction_detail || {};
  const failed = detail.failed_chunks || 0;
  const failNote = failed
    ? ` ${failed}/${detail.chunks || "?"} chunk(s) fell back to rule parsing (${(detail.fail_reasons || []).join(", ")}).`
    : "";
  const srcBadge =
    data.extraction_source === "ai"
      ? ` <span class="src-badge" title="Values transcribed by AI from the report's printed text; statuses computed deterministically.${failNote}">AI-extracted${failed ? "*" : ""}</span>`
      : ` <span class="src-badge" title="Values matched by the rule-based parser.${failNote}">rule-parsed</span>`;
  $("report-title").innerHTML = `Report #${data.report_id}${srcBadge}`;
  lastReportId = data.report_id;
  $("summary").textContent = data.summary;
  lastAiExplanation = data.ai_explanation;
  $("ai-panel").classList.add("hidden");

  const body = $("results-body");
  body.innerHTML = "";
  for (const r of data.results) {
    const nameCell =
      `${escapeHtml(r.original_name)} → <strong>${escapeHtml(r.standard_name)}</strong>` +
      (r.source === "calculated"
        ? ` <span class="src-badge" title="${escapeHtml(r.method || "calculated")}">calculated</span>`
        : "");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${nameCell}</td>
      <td><strong>${r.value}</strong></td>
      <td>${escapeHtml(r.unit)}</td>
      <td>${escapeHtml(fmtRange(r))}</td>
      <td>${r.flag ? escapeHtml(r.flag) : "—"}</td>
      <td><span class="pill ${r.status.toLowerCase()}">${r.status}</span></td>`;
    body.appendChild(tr);
  }

  if (data.results.length === 0) {
    body.innerHTML = `<tr><td colspan="6" class="muted">No biomarkers found in this PDF's text.</td></tr>`;
  }
  $("results-card").scrollIntoView({ behavior: "smooth" });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function handleUpload(event) {
  event.preventDefault();
  const file = $("file-input").files[0];
  if (!file) return;

  const btn = $("upload-btn");
  const progress = $("progress");
  const note = $("upload-note");
  btn.disabled = true;
  progress.classList.remove("hidden");
  note.classList.add("hidden");

  try {
    const form = new FormData();
    form.append("file", file);
    const upRes = await api(`/api/reports/upload`, { method: "POST", body: form });
    if (!upRes.ok) {
      const err = await upRes.json().catch(() => ({}));
      throw new Error(err.detail || "Upload failed");
    }
    const uploaded = await upRes.json();

    const srcLabel = { image: "Source: photo/scan (OCR).", scanned_pdf: "Source: scanned PDF (OCR).", pdf: null }[uploaded.source_type];
    const noteText = [srcLabel, uploaded.note].filter(Boolean).join(" ");
    if (noteText) {
      note.textContent = noteText;
      note.classList.remove("hidden");
    }

    progress.textContent = "Analyzing… (AI extraction takes ~3–4 min for a full report)";
    const anRes = await api(`/api/reports/${uploaded.report_id}/analyze`, { method: "POST" });
    if (!anRes.ok) throw new Error("Analysis failed");
    const analyzed = await anRes.json();

    renderResults(analyzed);
    await loadHistory();
    await loadTrend(); // a new report may add trend points
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    btn.disabled = false;
    progress.classList.add("hidden");
    progress.textContent = "Working…";
  }
}

async function handleExplain() {
  const panel = $("ai-panel");
  const text = $("ai-text");
  if (lastAiExplanation) {
    text.textContent = lastAiExplanation;
  } else {
    text.textContent =
      "AI explanation unavailable. Set the GROQ_API_KEY environment variable " +
      "(free tier) or run Ollama locally (ollama pull llama3.1, then ollama serve), " +
      "then upload again. The rule-based summary above still applies.";
  }
  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth" });
}

async function loadHistory() {
  const list = $("history-list");
  try {
    const res = await api(`/api/reports`);
    const reports = await res.json();
    list.innerHTML = "";
    if (reports.length === 0) {
      list.innerHTML = `<li class="muted">No reports yet.</li>`;
      return;
    }
    for (const r of reports) {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = "#";
      const when = r.report_date ? ` · ${r.report_date}` : "";
      link.textContent = `#${r.id} ${r.filename}${when} (${r.result_count} results)`;
      link.addEventListener("click", async (e) => {
        e.preventDefault();
        const dRes = await api(`/api/reports/${r.id}`);
        const detail = await dRes.json();
        renderResults({
          report_id: detail.id,
          results: detail.results,
          summary: `Saved analysis of ${detail.filename}: ${detail.results.length} biomarker(s).`,
          ai_explanation: null,
          extraction_source: detail.extraction_source || "rules",
        });
      });
      li.appendChild(link);
      list.appendChild(li);
    }
  } catch {
    list.innerHTML = `<li class="muted">Could not load history.</li>`;
  }
}

/* ---- Trends ---- */

async function loadBiomarkers() {
  const sel = $("trend-select");
  try {
    const res = await fetch(`${API}/api/biomarkers`);
    const specs = await res.json();
    sel.innerHTML = "";
    for (const b of specs) {
      const opt = document.createElement("option");
      opt.value = b.biomarker_id;
      opt.textContent = `${b.standard_name} (${b.biomarker_id})`;
      sel.appendChild(opt);
    }
    if ([...sel.options].some((o) => o.value === "BM001")) sel.value = "BM001";
    await loadTrend();
  } catch {
    sel.innerHTML = `<option value="">Could not load biomarkers</option>`;
  }
}

async function loadTrend() {
  const id = $("trend-select").value;
  const result = $("trend-result");
  const empty = $("trend-empty");
  if (!id) {
    result.classList.add("hidden");
    empty.classList.remove("hidden");
    return;
  }
  try {
    const res = await api(`/api/reports/trends/${id}`);
    if (!res.ok) throw new Error("no data");
    const trend = await res.json();
    result.classList.remove("hidden");
    empty.classList.add("hidden");
    const dir = $("trend-direction");
    dir.textContent = `${trend.standard_name}: ${trend.direction}`;
    dir.className = `trend-direction ${trend.direction}`;
    drawTrend(trend);
    const note = $("trend-note");
    note.textContent = trend.excluded.length
      ? `${trend.excluded.length} point(s) excluded: ${trend.excluded.map((p) => p.reason).join("; ")}`
      : "";
  } catch {
    result.classList.add("hidden");
    empty.classList.remove("hidden");
    empty.textContent = "No trend data yet for this biomarker — upload reports containing it first.";
  }
}

function drawTrend(trend) {
  const canvas = $("trend-chart");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const pts = trend.points;
  if (pts.length === 0) return;

  const vals = pts.map((p) => p.value);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { min -= 1; max += 1; }
  const padL = 52, padR = 16, padT = 16, padB = 40;
  const xs = (i) => padL + (i * (W - padL - padR)) / Math.max(pts.length - 1, 1);
  const ys = (v) => H - padB - ((v - min) / (max - min)) * (H - padT - padB);

  // Gridlines + y labels.
  ctx.font = "11px system-ui";
  ctx.fillStyle = "#94a3b8";
  ctx.strokeStyle = "#243145";
  ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const v = min + ((max - min) * g) / 4;
    const y = ys(v);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillText(v.toFixed(1), 6, y + 4);
  }

  // Line.
  ctx.strokeStyle = "#38bdf8";
  ctx.lineWidth = 2;
  ctx.beginPath();
  pts.forEach((p, i) => (i ? ctx.lineTo(xs(i), ys(p.value)) : ctx.moveTo(xs(i), ys(p.value))));
  ctx.stroke();

  // Points + date labels.
  pts.forEach((p, i) => {
    ctx.fillStyle = "#38bdf8";
    ctx.beginPath(); ctx.arc(xs(i), ys(p.value), 4, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#94a3b8";
    const label = (p.report_date || "").slice(5) || "?"; // MM-DD
    ctx.fillText(label, xs(i) - 14, H - 22);
    ctx.fillText(String(p.value), xs(i) - 14, H - 8);
  });

  ctx.fillStyle = "#94a3b8";
  ctx.fillText(trend.unit || "", W - padR - 30, padT + 4);
}

/* ---- Chat ---- */

const chatHistory = [];

function chatMode() {
  const el = document.querySelector('input[name="chat-mode"]:checked');
  return el ? el.value : "hybrid";
}

function addChatBubble(role, text) {
  const log = $("chat-log");
  const div = document.createElement("div");
  div.className = `chat-bubble ${role}`;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function handleChat(e) {
  e.preventDefault();
  const input = $("chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  addChatBubble("user", message);
  chatHistory.push({ role: "user", content: message });

  const mode = chatMode();
  const thinking = document.createElement("div");
  thinking.className = "chat-bubble assistant thinking";
  thinking.textContent = "Thinking…";
  $("chat-log").appendChild(thinking);

  try {
    const url = mode === "baseline" ? `${API}/api/chat/baseline` : `${API}/api/chat`;
    const body = mode === "baseline"
      ? { message }
      : { message, report_id: lastReportId, history: chatHistory.slice(0, -1) };
    const res = await api(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    thinking.remove();
    addChatBubble("assistant", data.answer);
    chatHistory.push({ role: "assistant", content: data.answer });
    const srcs = (data.sources || []).map((s) => s.title).join(", ");
    $("chat-meta").textContent =
      `mode: ${data.mode}` +
      (data.model ? ` · model: ${data.model}` : " · model: unavailable") +
      (srcs ? ` · sources: ${srcs}` : "") +
      (data.numbers_grounded === false ? " · ⚠ some numbers not found in context" : "");
  } catch (err) {
    thinking.remove();
    addChatBubble("assistant", `Sorry — could not get an answer (${err.message}).`);
  }
}

$("chat-form").addEventListener("submit", handleChat);

$("upload-form").addEventListener("submit", handleUpload);
$("explain-btn").addEventListener("click", handleExplain);
$("trend-form").addEventListener("submit", (e) => { e.preventDefault(); loadTrend(); });
$("trend-select").addEventListener("change", loadTrend);
checkHealth();
loadBiomarkers();
initAuth();
