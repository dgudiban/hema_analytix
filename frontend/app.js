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
  loadCompareReports();
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

const GROUPS = [
  { key: "below", icon: "🔵", title: "Below range", match: (s) => s === "LOW" },
  { key: "above", icon: "🟠", title: "Above range", match: (s) => s === "HIGH" },
  { key: "within", icon: "🟢", title: "Within range", match: (s) => s === "NORMAL" },
  { key: "unknown", icon: "⚪", title: "No reference range on report", match: (s) => s !== "LOW" && s !== "HIGH" && s !== "NORMAL" },
];

const BAR_COLORS = { low: "#60a5fa", normal: "#34d399", high: "#fbbf24" };

/* Largest-remainder percentages that always sum to exactly 100. */
function pct100(counts) {
  const total = counts.reduce((a, b) => a + b, 0);
  if (total === 0) return counts.map(() => 0);
  const raw = counts.map((c) => (c / total) * 100);
  const out = raw.map(Math.floor);
  let rem = 100 - out.reduce((a, b) => a + b, 0);
  const order = raw
    .map((v, i) => [v - out[i], i])
    .sort((a, b) => b[0] - a[0]);
  for (let k = 0; k < rem && k < order.length; k++) out[order[k][1]] += 1;
  return out;
}

function donutHTML(results) {
  const segs = [
    { key: "below", label: "Below range", color: BAR_COLORS.low, n: 0 },
    { key: "within", label: "Within range", color: BAR_COLORS.normal, n: 0 },
    { key: "above", label: "Above range", color: BAR_COLORS.high, n: 0 },
    { key: "norange", label: "No range printed", color: "#64748b", n: 0 },
  ];
  for (const r of results) {
    if (r.status === "LOW") segs[0].n++;
    else if (r.status === "NORMAL") segs[1].n++;
    else if (r.status === "HIGH") segs[2].n++;
    else segs[3].n++;
  }
  const pcts = pct100(segs.map((s) => s.n));
  const total = results.length;
  let offset = 25; // start segments at 12 o'clock
  const circles = segs
    .map((s, i) => {
      const dash = `${pcts[i]} ${100 - pcts[i]}`;
      const el = `<circle r="15.9155" cx="18" cy="18" fill="none" stroke="${s.color}" stroke-width="6" stroke-dasharray="${dash}" stroke-dashoffset="${offset}" />`;
      offset -= pcts[i];
      return el;
    })
    .join("");
  const legend = segs
    .map(
      (s, i) =>
        `<li><span class="dot" style="background:${s.color}"></span>${s.label}: <strong>${s.n}</strong> (${pcts[i]}%)</li>`
    )
    .join("");
  const caption = total === 0 ? "No biomarkers" : `${total} biomarker${total === 1 ? "" : "s"}`;
  return `
    <div class="donut" role="img" aria-label="Result distribution: ${segs.map((s, i) => `${s.label} ${pcts[i]} percent`).join(", ")}">
      <svg viewBox="0 0 36 36" class="donut-svg">
        <circle r="15.9155" cx="18" cy="18" fill="none" stroke="#1e293b" stroke-width="6" />
        ${circles}
      </svg>
      <div class="donut-center"><strong>${total}</strong><span>${total === 1 ? "marker" : "markers"}</span></div>
    </div>
    <ul class="donut-legend">${legend}</ul>`;
}

function renderDonut(results) {
  $("donut-wrap").innerHTML = donutHTML(results || []);
}

/* Per-biomarker range indicator, drawn ONLY from this report's own
   printed reference range (ref_low / ref_high). Handles two-sided,
   one-sided, and missing ranges. */
function rangeIndicatorHTML(r) {
  const lo = r.ref_low;
  const hi = r.ref_high;
  const v = r.value;
  if (lo == null && hi == null) {
    return `<div class="range-bar none"><span class="muted">No reference range printed — position can't be shown.</span></div>`;
  }
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  let d0, d1, zones;
  if (lo != null && hi != null && hi > lo) {
    const span = hi - lo;
    const pad = Math.max(span * 0.6, span === 0 ? 1 : 0);
    d0 = lo - pad;
    d1 = hi + pad;
    const x = (val) => clamp01((val - d0) / (d1 - d0)) * 100;
    zones = [
      { from: 0, to: x(lo), color: BAR_COLORS.low, label: "low" },
      { from: x(lo), to: x(hi), color: BAR_COLORS.normal, label: "normal" },
      { from: x(hi), to: 100, color: BAR_COLORS.high, label: "high" },
    ];
  } else if (lo != null) {
    // One-sided: normal is [lo, ∞).
    const span = Math.max(Math.abs(v - lo), Math.abs(lo) * 0.2, 1) * 1.4;
    d0 = lo - span;
    d1 = lo + span;
    const x = (val) => clamp01((val - d0) / (d1 - d0)) * 100;
    zones = [
      { from: 0, to: x(lo), color: BAR_COLORS.low, label: "low" },
      { from: x(lo), to: 100, color: BAR_COLORS.normal, label: "≥ normal" },
    ];
  } else {
    // One-sided: normal is (−∞, hi].
    const span = Math.max(Math.abs(v - hi), Math.abs(hi) * 0.2, 1) * 1.4;
    d0 = hi - span;
    d1 = hi + span;
    const x = (val) => clamp01((val - d0) / (d1 - d0)) * 100;
    zones = [
      { from: 0, to: x(hi), color: BAR_COLORS.normal, label: "≤ normal" },
      { from: x(hi), to: 100, color: BAR_COLORS.high, label: "high" },
    ];
  }
  const pos = clamp01((v - d0) / (d1 - d0)) * 100;
  const zoneDivs = zones
    .map(
      (z) =>
        `<div class="rzone" title="${z.label}" style="left:${z.from}%;width:${Math.max(0, z.to - z.from)}%;background:${z.color}"></div>`
    )
    .join("");
  const ticks = [];
  if (lo != null) ticks.push({ at: clamp01((lo - d0) / (d1 - d0)) * 100, label: String(lo) });
  if (hi != null && hi !== lo) ticks.push({ at: clamp01((hi - d0) / (d1 - d0)) * 100, label: String(hi) });
  const tickDivs = ticks
    .map((t) => `<span class="rtick" style="left:${t.at}%"><i></i>${escapeHtml(t.label)}</span>`)
    .join("");
  const edge = pos <= 0 || pos >= 100 ? " edge" : "";
  return `
    <div class="range-bar" role="img" aria-label="Reference range ${escapeHtml(fmtRange(r))} ${escapeHtml(r.unit)}, your value ${v} ${escapeHtml(r.unit)}">
      <div class="rtrack">${zoneDivs}
        <div class="rmarker${edge}" style="left:${pos}%" title="Your value: ${v} ${escapeHtml(r.unit)}"></div>
      </div>
      <div class="rticks">${tickDivs}<span class="rvalue" style="left:${pos}%">${v}</span></div>
      <div class="rcaption">Your value: <strong>${v} ${escapeHtml(r.unit)}</strong> · ref ${escapeHtml(fmtRange(r))}</div>
    </div>`;
}

function rangeBarHTML(r) {
  return rangeIndicatorHTML(r);
}

function biomarkerRowHTML(r) {
  const calcBadge = r.source === "calculated"
    ? ` <span class="src-badge" title="${escapeHtml(r.method || "calculated")}">calculated</span>`
    : "";
  const flagLine = r.flag ? `<div class="row-detail-line">Lab flag: <strong>${escapeHtml(r.flag)}</strong></div>` : "";
  const rangeLine = (r.ref_low != null || r.ref_high != null)
    ? `<div class="row-detail-line">Reference: ${escapeHtml(fmtRange(r))} ${escapeHtml(r.unit)}</div>`
    : `<div class="row-detail-line muted">No reference range printed on this report.</div>`;
  return `
    <div class="bio-row" data-status="${r.status}">
      <button type="button" class="bio-row-head" aria-expanded="false">
        <span class="bio-name">${escapeHtml(r.standard_name)}${calcBadge}</span>
        <span class="bio-value"><strong>${r.value}</strong> ${escapeHtml(r.unit)}</span>
        <span class="pill ${r.status.toLowerCase()}">${r.status}</span>
        <span class="chev">▸</span>
      </button>
      <div class="bio-row-detail hidden">
        ${rangeBarHTML(r)}
        <div class="row-detail-line">As reported: ${escapeHtml(r.original_name)}</div>
        ${flagLine}
        ${rangeLine}
      </div>
    </div>`;
}

function renderQuickSummary(data) {
  const results = data.results || [];
  const below = results.filter((r) => r.status === "LOW");
  const above = results.filter((r) => r.status === "HIGH");
  const within = results.filter((r) => r.status === "NORMAL");

  $("count-below").textContent = below.length;
  $("count-within").textContent = within.length;
  $("count-above").textContent = above.length;

  const dateStr = data.report_date ? ` · ${data.report_date}` : "";
  $("summary-meta").textContent = `${results.length} biomarker${results.length === 1 ? "" : "s"} detected${dateStr}`;
  $("summary-text").textContent = data.summary || "";
  renderDonut(results);

  const notable = $("notable-list");
  notable.innerHTML = "";
  const flagged = [...below, ...above].slice(0, 6);
  if (flagged.length === 0) {
    notable.innerHTML = `<li class="muted">All values are within their reference ranges.</li>`;
  } else {
    for (const r of flagged) {
      const li = document.createElement("li");
      const dir = r.status === "LOW" ? "below" : "above";
      li.innerHTML = `<strong>${escapeHtml(r.standard_name)}</strong> — ${dir} range (${r.value} ${escapeHtml(r.unit)})`;
      notable.appendChild(li);
    }
  }
  $("summary-card").classList.remove("hidden");
}

function renderResults(data) {
  renderQuickSummary(data);

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
  lastAiExplanation = data.ai_explanation;
  $("ai-panel").classList.add("hidden");

  const groupsEl = $("results-groups");
  groupsEl.innerHTML = "";
  const results = data.results || [];
  for (const g of GROUPS) {
    const members = results.filter((r) => g.match(r.status));
    if (members.length === 0) continue;
    const section = document.createElement("section");
    section.className = `result-group ${g.key}`;
    section.innerHTML = `
      <h3 class="group-head">${g.icon} ${g.title} <span class="group-count">${members.length}</span></h3>
      <div class="group-body"></div>`;
    const body = section.querySelector(".group-body");
    for (const r of members) {
      const wrap = document.createElement("div");
      wrap.innerHTML = biomarkerRowHTML(r);
      body.appendChild(wrap.firstElementChild);
    }
    groupsEl.appendChild(section);
  }
  if (results.length === 0) {
    groupsEl.innerHTML = `<p class="muted">No biomarkers found in this report's text.</p>`;
  }

  // Expandable rows.
  groupsEl.querySelectorAll(".bio-row-head").forEach((btn) => {
    btn.addEventListener("click", () => {
      const detailEl = btn.nextElementSibling;
      const open = detailEl.classList.toggle("hidden");
      btn.setAttribute("aria-expanded", String(!open));
      btn.querySelector(".chev").textContent = open ? "▸" : "▾";
    });
  });

  $("summary-card").scrollIntoView({ behavior: "smooth" });
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

    analyzed.report_date = uploaded.report_date;
    renderResults(analyzed);
    await loadHistory();
    await loadTrend(); // a new report may add trend points
    await loadCompareReports();
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
          report_date: detail.report_date,
          results: detail.results,
          summary: detail.summary || `Saved analysis of ${detail.filename}: ${detail.results.length} biomarker(s).`,
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

const CHANGE_BADGE = {
  up: ["↑", "chg-up", "increased"],
  down: ["↓", "chg-down", "decreased"],
  same: ["→", "chg-same", "unchanged"],
  new: ["new", "chg-new", "present only in the later report"],
  missing: ["missing", "chg-missing", "present only in the earlier report"],
};

async function loadCompareReports() {
  const aSel = $("compare-a"), bSel = $("compare-b");
  try {
    const res = await api("/api/reports");
    const reports = (await res.json()).slice().sort((x, y) => x.id - y.id);
    aSel.innerHTML = ""; bSel.innerHTML = "";
    for (const r of reports) {
      const label = `#${r.id} ${r.filename}${r.report_date ? ` · ${r.report_date}` : ""} (${r.result_count})`;
      aSel.appendChild(new Option(label, r.id));
      bSel.appendChild(new Option(label, r.id));
    }
    if (reports.length >= 2) {
      aSel.value = reports[reports.length - 2].id;
      bSel.value = reports[reports.length - 1].id;
      $("compare-empty").classList.add("hidden");
    } else {
      $("compare-empty").classList.remove("hidden");
    }
  } catch {
    $("compare-empty").textContent = "Could not load reports.";
    $("compare-empty").classList.remove("hidden");
  }
}

async function runCompare(e) {
  e.preventDefault();
  const a = $("compare-a").value, b = $("compare-b").value;
  if (!a || !b) return;
  const resEl = $("compare-result");
  try {
    const res = await api(`/api/reports/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
    if (!res.ok) throw new Error("compare failed");
    const data = await res.json();
    const fmtSide = (s) => `#${s.id} ${s.filename}${s.report_date ? ` · ${s.report_date}` : ""}`;
    $("compare-head-a").textContent = `A — ${fmtSide(data.a)}`;
    $("compare-head-b").textContent = `B — ${fmtSide(data.b)}`;
    $("compare-title").textContent =
      `Comparing earlier ${fmtSide(data.a)} with later ${fmtSide(data.b)}.`;
    const tb = $("compare-table").querySelector("tbody");
    tb.innerHTML = "";
    const statusPill = (s) => s ? `<span class="pill ${s.toLowerCase()}">${s}</span>` : `<span class="muted">—</span>`;
    const valCell = (v, s, unit) =>
      v == null ? `<span class="muted">—</span>` : `${v} ${escapeHtml(unit || "")} ${statusPill(s)}`;
    for (const row of data.rows) {
      const [mark, cls, title] = CHANGE_BADGE[row.change] || CHANGE_BADGE.same;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${escapeHtml(row.standard_name)}</strong></td>
        <td>${valCell(row.a_value, row.a_status, row.unit)}</td>
        <td>${valCell(row.b_value, row.b_status, row.unit)}</td>
        <td><span class="chg ${cls}" title="${title}">${mark}</span></td>`;
      tb.appendChild(tr);
    }
    resEl.classList.remove("hidden");
  } catch {
    resEl.classList.add("hidden");
    $("compare-empty").textContent = "Could not compare those reports.";
    $("compare-empty").classList.remove("hidden");
  }
}

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
    const dirLabel = TREND_DIR_LABEL[trend.direction] || trend.direction;
    dir.textContent = `${trend.standard_name}: ${dirLabel} across ${trend.points.length} report${trend.points.length === 1 ? "" : "s"}`;
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

const TREND_DIR_LABEL = { improving: "trending up", declining: "trending down", stable: "stable" };

function drawTrend(trend) {
  // Bar chart, one bar per report. Bars are colored by that report's own
  // status; the shaded band is the reference range printed on the LATEST
  // report (labeled as such) — earlier reports may have printed different
  // ranges, shown per-bar in the tooltip.
  const canvas = $("trend-chart");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const pts = trend.points;
  if (pts.length === 0) return;

  const STATUS_FILL = { LOW: "#60a5fa", NORMAL: "#34d399", HIGH: "#fbbf24" };
  const vals = pts.map((p) => p.value);
  let min = Math.min(...vals), max = Math.max(...vals);
  const latest = pts[pts.length - 1];
  const bandLo = latest.ref_low, bandHi = latest.ref_high;
  if (bandLo != null) min = Math.min(min, bandLo);
  if (bandHi != null) max = Math.max(max, bandHi);
  if (min === max) { min -= 1; max += 1; }
  const spanPad = (max - min) * 0.08;
  min -= spanPad; max += spanPad;

  const padL = 52, padR = 16, padT = 16, padB = 44;
  const ys = (v) => H - padB - ((v - min) / (max - min)) * (H - padT - padB);
  const slot = (W - padL - padR) / pts.length;
  const barW = Math.min(64, slot * 0.55);
  const xs = (i) => padL + slot * i + slot / 2;

  // Normal band from the latest report's printed range.
  if (bandLo != null && bandHi != null && bandHi > bandLo) {
    ctx.fillStyle = "rgba(52, 211, 153, 0.12)";
    ctx.fillRect(padL, ys(bandHi), W - padL - padR, ys(bandLo) - ys(bandHi));
    ctx.strokeStyle = "rgba(52, 211, 153, 0.45)";
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(padL, ys(bandHi)); ctx.lineTo(W - padR, ys(bandHi)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(padL, ys(bandLo)); ctx.lineTo(W - padR, ys(bandLo)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#34d399";
    ctx.font = "10px system-ui";
    ctx.fillText(`ref on latest report: ${bandLo}–${bandHi}`, padL + 4, ys(bandHi) - 5);
  }

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

  // Bars.
  canvas._trendPts = pts.map((p, i) => ({ p, x: xs(i) - barW / 2, w: barW, yTop: ys(p.value), yBase: ys(Math.max(min, 0)) }));
  pts.forEach((p, i) => {
    const x = xs(i) - barW / 2;
    const yTop = ys(p.value);
    const yBase = ys(Math.max(min, 0));
    ctx.fillStyle = STATUS_FILL[p.status] || "#64748b";
    ctx.fillRect(x, yTop, barW, Math.max(2, yBase - yTop));
    ctx.fillStyle = "#e2e8f0";
    ctx.fillText(String(p.value), x, yTop - 6);
    ctx.fillStyle = "#94a3b8";
    const label = (p.report_date || "").slice(5) || "?";
    ctx.fillText(label, xs(i) - 14, H - 26);
    const rng = p.ref_low != null && p.ref_high != null ? `${p.ref_low}–${p.ref_high}`
      : p.ref_high != null ? `<${p.ref_high}` : p.ref_low != null ? `>${p.ref_low}` : "no range";
    ctx.fillText(rng, xs(i) - 20, H - 10);
  });

  ctx.fillStyle = "#94a3b8";
  ctx.fillText(trend.unit || "", W - padR - 30, padT + 4);
}

// Hover tooltip for the trend bars (native title via canvas redraw is
// overkill; show per-bar details in the note line on click instead).
$("trend-chart").addEventListener("click", (e) => {
  const info = e.currentTarget._trendPts;
  if (!info) return;
  const rect = e.currentTarget.getBoundingClientRect();
  const mx = (e.clientX - rect.left) * (e.currentTarget.width / rect.width);
  const hit = info.find((b) => mx >= b.x - 6 && mx <= b.x + b.w + 6);
  if (hit) {
    const p = hit.p;
    const rng = p.ref_low != null && p.ref_high != null ? `${p.ref_low} – ${p.ref_high} ${p.unit}`
      : "no reference range printed";
    $("trend-note").textContent =
      `${p.report_date || "undated"}: ${p.value} ${p.unit} — ref ${rng}, status ${p.status || "unknown"}.`;
  }
});

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
$("view-results-btn").addEventListener("click", () =>
  $("results-card").scrollIntoView({ behavior: "smooth" }));
$("ask-about-btn").addEventListener("click", () =>
  $("chat-card").scrollIntoView({ behavior: "smooth" }));
$("explain-btn").addEventListener("click", handleExplain);
$("trend-form").addEventListener("submit", (e) => { e.preventDefault(); loadTrend(); });
$("trend-select").addEventListener("change", loadTrend);
$("compare-form").addEventListener("submit", runCompare);
checkHealth();
loadBiomarkers();
initAuth();
