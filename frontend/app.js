/* BloodIQ frontend — plain JS, no build step. */
const API = ""; // same origin; the backend serves this page

const $ = (id) => document.getElementById(id);

let lastAiExplanation = null;
let lastReportId = null;

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
  $("report-title").textContent = `Report #${data.report_id}`;
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
      <td><span class="pill ${r.status.toLowerCase()}">${r.status}</span></td>`;
    body.appendChild(tr);
  }

  if (data.results.length === 0) {
    body.innerHTML = `<tr><td colspan="5" class="muted">No biomarkers found in this PDF's text.</td></tr>`;
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
    const upRes = await fetch(`${API}/api/reports/upload`, { method: "POST", body: form });
    if (!upRes.ok) {
      const err = await upRes.json().catch(() => ({}));
      throw new Error(err.detail || "Upload failed");
    }
    const uploaded = await upRes.json();

    if (uploaded.note) {
      note.textContent = uploaded.note;
      note.classList.remove("hidden");
    }

    progress.textContent = "Analyzing…";
    const anRes = await fetch(`${API}/api/reports/${uploaded.report_id}/analyze`, { method: "POST" });
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
    const res = await fetch(`${API}/api/reports`);
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
        const dRes = await fetch(`${API}/api/reports/${r.id}`);
        const detail = await dRes.json();
        renderResults({
          report_id: detail.id,
          results: detail.results,
          summary: `Saved analysis of ${detail.filename}: ${detail.results.length} biomarker(s).`,
          ai_explanation: null,
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
    const res = await fetch(`${API}/api/reports/trends/${id}`);
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
    const res = await fetch(url, {
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
loadHistory();
loadBiomarkers();
