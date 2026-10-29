/* LabIQ frontend — plain JS, no build step. */
const API = ""; // same origin; the backend serves this page

const $ = (id) => document.getElementById(id);

const TOKEN_KEY = "labiq_token";
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

async function showApp(user) {
  currentUser = user;
  $("auth-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("user-chip").classList.remove("hidden");
  $("member-strip").classList.remove("hidden");
  $("user-name").textContent = `👤 ${user.name}`;
  const saved = localStorage.getItem(MEMBER_KEY);
  selectedMemberId = saved ? Number(saved) : null;
  await loadFamily(); // validates the saved selection, renders chips/list/select
  loadProfile();
  switchTab("dashboard");
  await refreshProfileData();
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(MEMBER_KEY);
  currentUser = null;
  familyMembers = [];
  selectedMemberId = null;
  lastReportId = null;
  $("member-strip").classList.add("hidden");
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

const BAR_COLORS = { low: "#f5b301", normal: "#22c55e", high: "#d01a35" };
const STATUS_LABEL = { LOW: "Below", NORMAL: "Normal", HIGH: "Above" };

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
        <circle r="15.9155" cx="18" cy="18" fill="none" stroke="#0d1b31" stroke-width="6" />
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
        <span class="pill ${r.status.toLowerCase()}">${STATUS_LABEL[r.status] || r.status}</span>
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
  const total = results.length;

  renderDonut(results);
  const pct = total ? Math.round((within.length / total) * 100) : 0;
  $("glance-text").innerHTML =
    `<strong>${within.length} of ${total}</strong> results in range (${pct}%)`;

  const notable = $("notable-list");
  notable.innerHTML = "";
  const flagged = [...below, ...above].slice(0, 5);
  if (flagged.length === 0) {
    notable.innerHTML = `<li class="muted">Everything is in range. Nice.</li>`;
  } else {
    for (const r of flagged) {
      const li = document.createElement("li");
      const dir = r.status === "LOW" ? "below" : "above";
      li.innerHTML = `<strong>${escapeHtml(r.standard_name)}</strong> is ${dir} range (${r.value} ${escapeHtml(r.unit)})`;
      notable.appendChild(li);
    }
  }

  const first = profileName();
  $("dash-greeting-data").textContent = first ? `Welcome back, ${first}` : "Welcome back";

  dashboardHasData = true;
  refreshDashboardPanels();
}

function refreshDashboardPanels() {
  document.querySelectorAll('.tab-panel[data-panel="dashboard"]').forEach((p) => {
    let show = true;
    if (p.dataset.requires === "data" && !dashboardHasData) show = false;
    if (p.dataset.requires === "empty" && dashboardHasData) show = false;
    p.classList.toggle("hidden", !show);
  });
  $("dash-content").classList.toggle("hidden", !dashboardHasData);
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

}



function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

let uploading = false;

function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// Staged progress for the long analyze call. Stages are illustrative — the
// server does this work in one request, so we rotate labels while it runs.
const ANALYZE_STAGES = [
  [0, 8, "Extracting text from your report…"],
  [8, 35, "AI transcribing result rows…"],
  [35, 60, "Matching biomarkers to the lab panel…"],
  [60, 85, "Calculating statuses and summaries…"],
  [85, 99, "Finalizing your results…"],
];
let progressTimer = null;
function startProgress(kind) {
  const wrap = $("progress");
  const text = $("progress-text");
  const fill = $("progress-fill");
  wrap.classList.remove("hidden");
  const t0 = Date.now();
  clearInterval(progressTimer);
  if (kind === "upload") {
    fill.style.width = "40%";
    text.textContent = "Uploading…";
    return;
  }
  fill.style.width = "5%";
  let pct = 5;
  progressTimer = setInterval(() => {
    const el = Date.now() - t0;
    pct = Math.min(97, pct + 2);
    fill.style.width = pct + "%";
    const stage = ANALYZE_STAGES.find(([lo, hi]) => pct >= lo && pct < hi);
    text.textContent = `${stage ? stage[2] : "Working…"} (${fmtElapsed(el)} elapsed)`;
  }, 1500);
}
function stopProgress() {
  clearInterval(progressTimer);
  progressTimer = null;
  $("progress").classList.add("hidden");
  $("progress-fill").style.width = "0%";
  $("progress-text").textContent = "Working…";
}

async function handleUpload(event) {
  event.preventDefault();
  if (uploading) return; // duplicate-submit guard
  const file = $("file-input").files[0];
  if (!file) return;
  uploading = true;

  const btn = $("upload-btn");
  const note = $("upload-note");
  btn.disabled = true;
  note.classList.add("hidden");
  startProgress("upload");

  try {
    const form = new FormData();
    form.append("file", file);
    const upMember = $("upload-member").value;
    if (upMember) form.append("member_id", upMember);
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

    startProgress("analyze");
    const anRes = await api(`/api/reports/${uploaded.report_id}/analyze`, { method: "POST" });
    if (!anRes.ok) throw new Error("Analysis failed");
    const analyzed = await anRes.json();

    analyzed.report_date = uploaded.report_date;
    renderResults(analyzed);
    await loadHistory();
    await loadTrend(); // a new report may add trend points
    await loadCompareReports();
    switchTab("results");
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    stopProgress();
    btn.disabled = false;
    uploading = false;
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

async function loadReport(id) {
  const dRes = await api(`/api/reports/${id}`);
  if (!dRes.ok) throw new Error(`HTTP ${dRes.status}`);
  const detail = await dRes.json();
  renderResults({
    report_id: detail.id,
    report_date: detail.report_date,
    results: detail.results,
    summary: detail.summary || `Saved analysis of ${detail.filename}: ${detail.results.length} biomarker(s).`,
    ai_explanation: null,
    extraction_source: detail.extraction_source || "rules",
  });
}

let reportIds = []; // newest-first, for prev/next navigation

async function stepReport(dir) {
  if (!reportIds.length || lastReportId === null) return;
  const i = reportIds.indexOf(lastReportId);
  const j = i + dir;
  if (j < 0 || j >= reportIds.length) return;
  try {
    await loadReport(reportIds[j]);
  } catch (err) {
    alert(`Error: ${err.message}`);
  }
}

async function loadHistory() {
  const list = $("history-list");
  const dashList = $("dash-recent-list");
  try {
    const res = await api(`/api/reports${memberQuery()}`);
    const reports = await res.json();
    list.innerHTML = "";
    dashList.innerHTML = "";
    reportIds = reports.map((r) => r.id);
    if (reports.length === 0) {
      list.innerHTML = `<li class="muted">No reports yet.</li>`;
      dashList.innerHTML = `<li class="muted">No reports yet.</li>`;
      return;
    }
    const addRow = (r, idx, target) => {
      const li = document.createElement("li");
      const link = document.createElement("a");
      link.href = "#";
      const when = r.report_date ? ` · ${r.report_date}` : "";
      link.textContent = `#${r.id} ${r.filename}${when} (${r.result_count} results)`;
      if (idx === 0) {
        const badge = document.createElement("span");
        badge.className = "latest-badge";
        badge.textContent = " Latest";
        link.appendChild(badge);
      }
      link.addEventListener("click", async (e) => {
        e.preventDefault();
        try {
          await loadReport(r.id);
          switchTab("results");
        } catch (err) {
          alert(`Error: ${err.message}`);
        }
      });
      li.appendChild(link);
      target.appendChild(li);
    };
    for (const [idx, r] of reports.entries()) addRow(r, idx, list);
    for (const [idx, r] of reports.slice(0, 5).entries()) addRow(r, idx, dashList);
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
    const res = await api(`/api/reports${memberQuery()}`);
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
    $("compare-title").textContent =
      `Comparing ${fmtSide(data.a)} (earlier) with ${fmtSide(data.b)} (later) — biggest movers first.`;
    drawCompare(data);
    resEl.classList.remove("hidden");
  } catch {
    resEl.classList.add("hidden");
    $("compare-empty").textContent = "Could not compare those reports.";
    $("compare-empty").classList.remove("hidden");
  }
}

function drawCompare(data) {
  // One glanceable chart: horizontal paired bars per biomarker, each pair
  // normalized to its own max (tests have different units). Biggest movers first.
  const canvas = $("compare-chart");
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const rows = data.rows.filter((r) =>
    r.a_value != null && r.b_value != null && isFinite(r.a_value) && isFinite(r.b_value));
  const pct = (r) => r.a_value === 0 ? (r.b_value === 0 ? 0 : 100)
    : ((r.b_value - r.a_value) / Math.abs(r.a_value)) * 100;
  rows.sort((x, y) => Math.abs(pct(y)) - Math.abs(pct(x)));
  const top = rows.slice(0, 12);
  const C_A = "#8b93c9", C_B = "#0089ff";
  // legend
  ctx.font = "12px system-ui";
  ctx.fillStyle = C_A; ctx.fillRect(8, 8, 14, 10);
  ctx.fillStyle = "#8fa3bd"; ctx.fillText("Earlier", 28, 17);
  ctx.fillStyle = C_B; ctx.fillRect(100, 8, 14, 10);
  ctx.fillStyle = "#8fa3bd"; ctx.fillText("Later", 120, 17);
  if (!top.length) {
    ctx.fillStyle = "#8fa3bd";
    ctx.fillText("No overlapping tests to compare.", 8, 44);
    return;
  }
  const labelW = 150, padR = 76, padT = 30;
  const rowH = Math.min(46, (H - padT - 12) / top.length);
  const maxW = W - labelW - padR;
  top.forEach((r, i) => {
    const y = padT + i * rowH;
    const mid = y + rowH / 2;
    const mx = Math.max(Math.abs(r.a_value), Math.abs(r.b_value), 1e-9);
    const wa = (Math.abs(r.a_value) / mx) * maxW;
    const wb = (Math.abs(r.b_value) / mx) * maxW;
    const name = r.standard_name.length > 24 ? r.standard_name.slice(0, 23) + "…" : r.standard_name;
    ctx.fillStyle = "#e9eff8";
    ctx.font = "12px system-ui";
    ctx.fillText(name, 6, mid + 4);
    const bh = 9, gapB = 4;
    ctx.fillStyle = C_A;
    ctx.fillRect(labelW, mid - bh - gapB / 2, Math.max(2, wa), bh);
    ctx.fillStyle = C_B;
    ctx.fillRect(labelW, mid + gapB / 2, Math.max(2, wb), bh);
    ctx.fillStyle = "#8fa3bd";
    ctx.font = "11px system-ui";
    ctx.fillText(`${r.a_value}`, labelW + wa + 6, mid - 3);
    ctx.fillText(`${r.b_value} ${r.unit || ""}`, labelW + wb + 6, mid + 12);
  });
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
    const res = await api(`/api/reports/trends/${id}${memberQuery()}`);
    if (!res.ok) throw new Error("no data");
    const trend = await res.json();
    result.classList.remove("hidden");
    empty.classList.add("hidden");
    const dir = $("trend-direction");
    const dirLabel = TREND_DIR_LABEL[trend.direction] || trend.direction;
    dir.textContent = `${trend.standard_name}: ${dirLabel} across ${trend.points.length} report${trend.points.length === 1 ? "" : "s"}`;
    dir.className = `trend-direction ${trend.direction}`;
    lastTrend = trend;
    const pts = trend.points;
    const first = pts[0], last = pts[pts.length - 1];
    const delta = pts.length > 1 ? (last.value - first.value) : 0;
    const dstr = pts.length > 1 ? `${delta > 0 ? "+" : ""}${delta.toFixed(1)} ${trend.unit || ""}` : "—";
    $("trend-stats").innerHTML = `
      <span class="tstat"><strong>${pts.length}</strong>reports</span>
      <span class="tstat"><strong>${last.value}</strong>latest${trend.unit ? ` (${trend.unit})` : ""}</span>
      <span class="tstat"><strong>${dstr}</strong>change</span>`;
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
let trendChartType = "bar";
let lastTrend = null;
document.querySelectorAll("[data-chart]").forEach((b) =>
  b.addEventListener("click", () => {
    trendChartType = b.dataset.chart;
    document.querySelectorAll("[data-chart]").forEach((x) =>
      x.classList.toggle("active", x === b));
    if (lastTrend) drawTrend(lastTrend);
  })
);

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

  const STATUS_FILL = { LOW: "#f5b301", NORMAL: "#22c55e", HIGH: "#d01a35" };
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
    ctx.fillStyle = "rgba(34, 197, 94, 0.12)";
    ctx.fillRect(padL, ys(bandHi), W - padL - padR, ys(bandLo) - ys(bandHi));
    ctx.strokeStyle = "rgba(34, 197, 94, 0.45)";
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(padL, ys(bandHi)); ctx.lineTo(W - padR, ys(bandHi)); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(padL, ys(bandLo)); ctx.lineTo(W - padR, ys(bandLo)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#22c55e";
    ctx.font = "10px system-ui";
    ctx.fillText(`ref on latest report: ${bandLo}–${bandHi}`, padL + 4, ys(bandHi) - 5);
  }

  // Gridlines + y labels.
  ctx.font = "11px system-ui";
  ctx.fillStyle = "#94a3b8";
  ctx.strokeStyle = "#1e3a5f";
  ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const v = min + ((max - min) * g) / 4;
    const y = ys(v);
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
    ctx.fillText(v.toFixed(1), 6, y + 4);
  }

  canvas._trendPts = pts.map((p, i) => ({ p, x: xs(i) - barW / 2, w: barW, yTop: ys(p.value), yBase: ys(Math.max(min, 0)) }));
  const drawLabels = () => {
    ctx.fillStyle = "#e9eff8";
    pts.forEach((p, i) => {
      ctx.fillStyle = "#e9eff8";
      ctx.fillText(String(p.value), xs(i) - 10, ys(p.value) - 10);
      ctx.fillStyle = "#94a3b8";
      const label = (p.report_date || "").slice(5) || "?";
      ctx.fillText(label, xs(i) - 14, H - 26);
      const rng = p.ref_low != null && p.ref_high != null ? `${p.ref_low}–${p.ref_high}`
        : p.ref_high != null ? `<${p.ref_high}` : p.ref_low != null ? `>${p.ref_low}` : "no range";
      ctx.fillText(rng, xs(i) - 20, H - 10);
    });
  };
  if (trendChartType === "line" && pts.length > 1) {
    ctx.strokeStyle = "#0089ff";
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    pts.forEach((p, i) => {
      const x = xs(i), y = ys(p.value);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    pts.forEach((p) => {
      ctx.fillStyle = STATUS_FILL[p.status] || "#64748b";
      ctx.beginPath(); ctx.arc(xs(pts.indexOf(p)), ys(p.value), 5, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#101651"; ctx.lineWidth = 2; ctx.stroke();
    });
    drawLabels();
  } else {
    pts.forEach((p, i) => {
      const x = xs(i) - barW / 2;
      const yTop = ys(p.value);
      const yBase = ys(Math.max(min, 0));
      ctx.fillStyle = STATUS_FILL[p.status] || "#64748b";
      ctx.fillRect(x, yTop, barW, Math.max(2, yBase - yTop));
    });
    drawLabels();
  }

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

const CHAT_MODE_DESC = {
  hybrid: "Answers use your reports plus curated knowledge — numbers come from your results.",
  baseline: "General answers from the AI alone, without your report data (for comparison).",
};

function chatMode() {
  const el = document.querySelector('.chat-mode [data-mode].active');
  return el ? el.dataset.mode : "hybrid";
}

function updateModeDesc() {
  $("chat-mode-desc").textContent = CHAT_MODE_DESC[chatMode()] || "";
}

document.querySelectorAll(".chat-mode [data-mode]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".chat-mode [data-mode]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    updateModeDesc();
  });
});
updateModeDesc();

function chatTimestamp() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/* Tiny safe markdown renderer: escape HTML, then bold, lists, line breaks. */
function renderMarkdown(text) {
  const esc = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const inline = (s) =>
    s
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|\W)\*([^*\n]+)\*/g, "$1<em>$2</em>");
  const lines = esc.split("\n");
  let html = "";
  let listOpen = null; // "ul" | "ol" | null
  const closeList = () => {
    if (listOpen) { html += `</${listOpen}>`; listOpen = null; }
  };
  for (const line of lines) {
    const t = line.trim();
    let m;
    if ((m = t.match(/^[-*]\s+(.*)/))) {
      if (listOpen !== "ul") { closeList(); html += "<ul>"; listOpen = "ul"; }
      html += `<li>${inline(m[1])}</li>`;
    } else if ((m = t.match(/^\d+[.)]\s+(.*)/))) {
      if (listOpen !== "ol") { closeList(); html += "<ol>"; listOpen = "ol"; }
      html += `<li>${inline(m[1])}</li>`;
    } else if ((m = t.match(/^#{1,3}\s+(.*)/))) {
      closeList();
      html += `<p class="md-head">${inline(m[1])}</p>`;
    } else if (t === "") {
      closeList();
    } else {
      closeList();
      html += `${inline(t)}<br />`;
    }
  }
  closeList();
  return html;
}

function hideWelcome() {
  const w = $("chat-welcome");
  if (w) w.hidden = true;
}

function addChatBubble(role, text, opts = {}) {
  hideWelcome();
  const log = $("chat-log");
  const msg = document.createElement("div");
  msg.className = `chat-msg ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "chat-avatar";
  if (role === "user") { avatar.textContent = "👤"; }
  else { avatar.innerHTML = '<img src="logo.png?v=20261029-labiq1" alt="LabIQ" />'; }
  msg.appendChild(avatar);

  const body = document.createElement("div");
  body.className = "chat-body";

  const div = document.createElement("div");
  div.className = `chat-bubble ${role}`;
  if (role === "assistant") {
    div.innerHTML = renderMarkdown(text);
  } else {
    div.textContent = text;
  }
  body.appendChild(div);

  const meta = document.createElement("div");
  meta.className = "chat-meta-row";
  const time = document.createElement("span");
  time.className = "chat-time";
  time.textContent = chatTimestamp();
  meta.appendChild(time);

  if (role === "assistant" && text) {
    const speak = document.createElement("button");
    speak.type = "button";
    speak.className = "speak-btn";
    speak.title = "Listen to this answer";
    speak.setAttribute("aria-label", "Listen to this answer");
    speak.textContent = "🔊";
    speak.addEventListener("click", () => toggleSpeak(text, speak));
    meta.appendChild(speak);
  }
  if (opts.sources && opts.sources.length) {
    const wrap = document.createElement("span");
    wrap.className = "chat-sources";
    for (const s of opts.sources.slice(0, 4)) {
      const chip = document.createElement("span");
      chip.className = "src-chip";
      chip.textContent = s;
      chip.title = s;
      wrap.appendChild(chip);
    }
    meta.appendChild(wrap);
  }
  if (opts.grounded === false) {
    const warn = document.createElement("span");
    warn.className = "chat-warn";
    warn.textContent = "⚠ some numbers not found in your reports";
    meta.appendChild(warn);
  }
  body.appendChild(meta);
  msg.appendChild(body);
  log.appendChild(msg);
  log.scrollTop = log.scrollHeight;
}

function addThinking() {
  hideWelcome();
  const log = $("chat-log");
  const msg = document.createElement("div");
  msg.className = "chat-msg assistant";
  const avatar = document.createElement("div");
  avatar.className = "chat-avatar";
  avatar.innerHTML = '<img src="logo.png?v=20261029-labiq1" alt="LabIQ" />';
  msg.appendChild(avatar);
  const body = document.createElement("div");
  body.className = "chat-body";
  const div = document.createElement("div");
  div.className = "chat-bubble assistant thinking";
  div.innerHTML = '<span class="tdot"></span><span class="tdot"></span><span class="tdot"></span>';
  body.appendChild(div);
  msg.appendChild(body);
  log.appendChild(msg);
  log.scrollTop = log.scrollHeight;
  return msg;
}

async function sendChatMessage(message) {
  message = (message || "").trim();
  if (!message) return;
  addChatBubble("user", message);
  chatHistory.push({ role: "user", content: message });

  const mode = chatMode();
  const thinking = addThinking();

  try {
    const url = mode === "baseline" ? `${API}/api/chat/baseline` : `${API}/api/chat`;
    const body = mode === "baseline"
      ? { message }
      : { message, report_id: lastReportId, history: chatHistory.slice(0, -1), member_id: selectedMemberId };
    const res = await api(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    thinking.remove();
    const sources = (data.sources || []).map((s) => s.title).filter(Boolean);
    addChatBubble("assistant", data.answer, { sources, grounded: data.numbers_grounded });
    chatHistory.push({ role: "assistant", content: data.answer });
    $("chat-meta").textContent =
      (data.model ? `model: ${data.model}` : "model: unavailable") +
      (mode === "hybrid" ? " · grounded in your reports" : " · AI only");
  } catch (err) {
    thinking.remove();
    addChatBubble("assistant", `Sorry — I couldn't get an answer (${err.message}). Please try again.`);
  }
}

function handleChat(e) {
  e.preventDefault();
  const input = $("chat-input");
  const message = input.value;
  input.value = "";
  autogrow(input);
  sendChatMessage(message);
  input.focus();
}

function clearChat() {
  chatHistory.length = 0;
  stopSpeaking();
  const log = $("chat-log");
  log.querySelectorAll(".chat-msg").forEach((m) => m.remove());
  const w = $("chat-welcome");
  if (w) w.hidden = false;
  $("chat-meta").textContent = "";
  log.scrollTop = 0;
}

$("chat-clear").addEventListener("click", clearChat);

document.querySelectorAll(".chat-suggest button").forEach((btn) => {
  btn.addEventListener("click", () => sendChatMessage(btn.textContent));
});

/* Textarea: autogrow + Enter to send, Shift+Enter for newline. */
function autogrow(input) {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}

(function initChatInput() {
  const input = $("chat-input");
  input.addEventListener("input", () => autogrow(input));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleChat(e);
    }
  });
})();

/* ---- Voice input/output (zero-cost Web Speech API) ---- */

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const TTS = "speechSynthesis" in window ? window.speechSynthesis : null;
let recognizer = null;
let listening = false;
let speakingBtn = null;

function voiceSupported() {
  return !!(SR || TTS);
}

function showVoiceNote() {
  const note = $("voice-note");
  if (SR && TTS) return; // fully supported
  note.hidden = false;
  if (!SR && !TTS) {
    note.textContent = "Voice input/output isn't supported in this browser — type your question instead.";
  } else if (!SR) {
    note.textContent = "Voice input isn't supported in this browser — you can still listen to answers.";
  } else {
    note.textContent = "Listening to answers isn't supported in this browser — voice input still works.";
  }
}

function stopListening() {
  if (recognizer && listening) {
    recognizer.stop();
  }
}

function stopSpeaking() {
  if (TTS) TTS.cancel();
  if (speakingBtn) {
    speakingBtn.textContent = "🔊";
    speakingBtn.title = "Listen to this answer";
    speakingBtn = null;
  }
}

function toggleMic() {
  if (!SR) return;
  if (listening) {
    stopListening();
    return;
  }
  recognizer = new SR();
  recognizer.lang = "en-US";
  recognizer.interimResults = false;
  recognizer.maxAlternatives = 1;
  const mic = $("chat-mic");
  recognizer.onresult = (e) => {
    const transcript = e.results[0][0].transcript;
    const input = $("chat-input");
    input.value = (input.value ? input.value + " " : "") + transcript;
    input.focus();
  };
  recognizer.onerror = () => setMicState(false);
  recognizer.onend = () => setMicState(false);
  recognizer.start();
  setMicState(true);
}

function setMicState(on) {
  listening = on;
  const mic = $("chat-mic");
  mic.classList.toggle("listening", on);
  mic.title = on ? "Stop listening" : "Ask with your voice";
}

function toggleSpeak(text, btn) {
  if (!TTS) return;
  if (speakingBtn === btn) {
    stopSpeaking();
    return;
  }
  stopSpeaking();
  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = 1;
  utter.onend = utter.onerror = () => {
    if (speakingBtn === btn) {
      btn.textContent = "🔊";
      btn.title = "Listen to this answer";
      speakingBtn = null;
    }
  };
  speakingBtn = btn;
  btn.textContent = "⏹";
  btn.title = "Stop";
  TTS.speak(utter); // user-gesture initiated only; no autoplay
}

$("chat-mic").addEventListener("click", toggleMic);
if (!SR) {
  const mic = $("chat-mic");
  mic.disabled = true;
  mic.title = "Voice input not supported in this browser";
}
showVoiceNote();

$("chat-form").addEventListener("submit", handleChat);

/* ---- Tabs, profile, navigation wiring ---- */

let dashboardHasData = false;
let activeView = "dashboard";

function switchTab(name) {
  activeView = name;
  document.querySelectorAll("#tabs .side-link").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === activeView)
  );
  document.querySelectorAll(".tab-panel").forEach((p) => {
    let show = p.dataset.panel === activeView;
    if (show && p.dataset.requires === "data" && !dashboardHasData) show = false;
    if (show && p.dataset.requires === "empty" && dashboardHasData) show = false;
    p.classList.toggle("hidden", !show);
  });
  $("app-main").scrollIntoView({ behavior: "smooth", block: "start" });
}

function loadProfile() {
  const user = currentUser;
  if (!user) return;
  $("profile-name").textContent = user.name || "";
  $("profile-email").textContent = user.email || "";
}

$("upload-form").addEventListener("submit", handleUpload);
const dz = $("dropzone"), fi = $("file-input");
fi.addEventListener("change", () => {
  $("file-name").textContent = fi.files[0] ? fi.files[0].name : "";
});
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.add("drag");
}));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.remove("drag");
}));
dz.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) {
    fi.files = e.dataTransfer.files;
    $("file-name").textContent = fi.files[0].name;
  }
});
document.querySelectorAll("#tabs .side-link").forEach((t) =>
  t.addEventListener("click", () => switchTab(t.dataset.tab))
);
document.querySelectorAll(".sidebar .side-nav:not(#tabs) .side-link").forEach((t) =>
  t.addEventListener("click", () => switchTab(t.dataset.tab))
);
$("empty-add-btn").addEventListener("click", () =>
  switchTab("upload"));
$("dash-add-btn").addEventListener("click", () =>
  switchTab("upload"));
$("worth-all-btn").addEventListener("click", () =>
  switchTab("results"));
$("view-all-reports-btn").addEventListener("click", () =>
  switchTab("reports"));
$("forgot-btn").addEventListener("click", () => {
  const err = $("auth-error");
  err.textContent = "Password reset isn't available yet — please ask support for help.";
  err.classList.remove("hidden");
});
$("prev-report-btn").addEventListener("click", () => stepReport(1));
$("next-report-btn").addEventListener("click", () => stepReport(-1));
$("profile-logout-btn").addEventListener("click", logout);
$("explain-btn").addEventListener("click", handleExplain);
$("trend-form").addEventListener("submit", (e) => { e.preventDefault(); loadTrend(); });
$("trend-select").addEventListener("change", loadTrend);
$("compare-form").addEventListener("submit", runCompare);
checkHealth();
loadBiomarkers();
initAuth();


/* ---------------- Family profiles ---------------- */
const MEMBER_KEY = "labiq_member";
let familyMembers = [];
let selectedMemberId = null; // null = the account owner ("Me")
let editingMemberId = null;

function memberQuery() {
  return selectedMemberId == null ? "" : `?member_id=${encodeURIComponent(selectedMemberId)}`;
}

function profileName() {
  if (selectedMemberId != null) {
    const m = familyMembers.find((x) => x.id === selectedMemberId);
    if (m) return m.name;
  }
  return currentUser && currentUser.name ? currentUser.name.split(" ")[0] : "";
}

async function loadFamily() {
  try {
    const res = await api("/api/family");
    familyMembers = res.ok ? await res.json() : [];
  } catch {
    familyMembers = [];
  }
  if (selectedMemberId != null && !familyMembers.some((m) => m.id === selectedMemberId)) {
    selectedMemberId = null;
    localStorage.removeItem(MEMBER_KEY);
  }
  renderMemberChips();
  renderFamilyList();
  renderUploadMemberSelect();
}

function renderMemberChips() {
  const wrap = $("member-chips");
  wrap.innerHTML = "";
  const mk = (label, id, title) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (selectedMemberId === id ? " active" : "");
    b.textContent = label;
    if (title) b.title = title;
    b.addEventListener("click", () => selectMember(id));
    return b;
  };
  const meLabel = currentUser && currentUser.name ? currentUser.name.split(" ")[0] : "Me";
  wrap.appendChild(mk(meLabel, null, "Your own reports"));
  for (const m of familyMembers) {
    wrap.appendChild(mk(m.name, m.id, `${m.relationship} · ${m.report_count} report(s)`));
  }
  const add = document.createElement("button");
  add.type = "button";
  add.className = "chip chip-add";
  add.textContent = "+ Add";
  add.title = "Add a family member";
  add.addEventListener("click", () => openMemberModal(null));
  wrap.appendChild(add);
}

const REL_LABELS = { father: "Father", mother: "Mother", spouse: "Spouse", son: "Son", daughter: "Daughter", other: "Other" };

function renderFamilyList() {
  const ul = $("family-list");
  ul.innerHTML = "";
  if (!familyMembers.length) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No family profiles yet.";
    ul.appendChild(li);
    return;
  }
  for (const m of familyMembers) {
    const li = document.createElement("li");
    const left = document.createElement("div");
    const nm = document.createElement("div");
    nm.className = "fam-name";
    nm.textContent = m.name;
    const sub = document.createElement("div");
    sub.className = "fam-sub";
    const bits = [REL_LABELS[m.relationship] || m.relationship];
    if (m.sex) bits.push(m.sex);
    bits.push(`${m.report_count} report${m.report_count === 1 ? "" : "s"}`);
    sub.textContent = bits.join(" · ");
    left.append(nm, sub);
    const acts = document.createElement("div");
    acts.className = "fam-actions";
    const view = document.createElement("button");
    view.type = "button"; view.className = "secondary small-btn"; view.textContent = "View";
    view.addEventListener("click", () => selectMember(m.id));
    const edit = document.createElement("button");
    edit.type = "button"; edit.className = "secondary small-btn"; edit.textContent = "Edit";
    edit.addEventListener("click", () => openMemberModal(m.id));
    const del = document.createElement("button");
    del.type = "button"; del.className = "secondary small-btn"; del.textContent = "Remove";
    del.addEventListener("click", () => deleteMember(m.id));
    acts.append(view, edit, del);
    li.append(left, acts);
    ul.appendChild(li);
  }
}

function renderUploadMemberSelect() {
  const sel = $("upload-member");
  sel.innerHTML = "";
  const meLabel = currentUser && currentUser.name ? `Me (${currentUser.name.split(" ")[0]})` : "Me";
  sel.appendChild(new Option(meLabel, ""));
  for (const m of familyMembers) {
    sel.appendChild(new Option(`${m.name} (${REL_LABELS[m.relationship] || m.relationship})`, String(m.id)));
  }
  sel.value = selectedMemberId == null ? "" : String(selectedMemberId);
}

async function selectMember(id) {
  selectedMemberId = id == null ? null : Number(id);
  if (selectedMemberId == null) localStorage.removeItem(MEMBER_KEY);
  else localStorage.setItem(MEMBER_KEY, String(selectedMemberId));
  renderMemberChips();
  renderUploadMemberSelect();
  switchTab("dashboard");
  await refreshProfileData();
}

async function refreshProfileData() {
  lastReportId = null;
  lastResults = null;
  lastAiExplanation = null;
  dashboardHasData = false;
  clearChat();
  $("results-groups").innerHTML = "";
  $("ai-panel").classList.add("hidden");
  await loadHistory();
  await loadTrend();
  await loadCompareReports();
  if (reportIds.length) {
    try { await loadReport(reportIds[0]); } catch { /* dashboard stays empty */ }
  } else {
    refreshDashboardPanels();
  }
}

function openMemberModal(editId) {
  editingMemberId = editId || null;
  const m = editId ? familyMembers.find((x) => x.id === editId) : null;
  $("member-modal-title").textContent = m ? `Edit ${m.name}` : "Add family member";
  $("mm-name").value = m ? m.name : "";
  $("mm-rel").value = m ? m.relationship : "other";
  $("mm-sex").value = m && m.sex ? m.sex : "";
  $("mm-dob").value = m && m.date_of_birth ? m.date_of_birth : "";
  $("member-modal").classList.remove("hidden");
  $("mm-name").focus();
}

function closeMemberModal() {
  $("member-modal").classList.add("hidden");
  editingMemberId = null;
}

async function saveMember() {
  const name = $("mm-name").value.trim();
  if (!name) { alert("Please enter a name."); return; }
  const body = {
    name,
    relationship: $("mm-rel").value,
    sex: $("mm-sex").value || null,
    date_of_birth: $("mm-dob").value || null,
  };
  try {
    const url = editingMemberId ? `/api/family/${editingMemberId}` : "/api/family";
    const res = await api(url, {
      method: editingMemberId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    closeMemberModal();
    await loadFamily();
  } catch (err) {
    alert(`Could not save: ${err.message}`);
  }
}

async function deleteMember(id) {
  const m = familyMembers.find((x) => x.id === id);
  const n = m ? m.report_count : 0;
  if (!confirm(`Remove ${m ? m.name : "this member"}${n ? ` and their ${n} report${n === 1 ? "" : "s"}` : ""}? This cannot be undone.`)) return;
  const res = await api(`/api/family/${id}`, { method: "DELETE" });
  if (!res.ok) { alert("Could not remove this member."); return; }
  if (selectedMemberId === id) await selectMember(null);
  else await loadFamily();
}

$("family-add-btn").addEventListener("click", () => openMemberModal(null));
$("mm-save").addEventListener("click", saveMember);
$("mm-cancel").addEventListener("click", closeMemberModal);
$("member-modal").addEventListener("click", (e) => {
  if (e.target === $("member-modal")) closeMemberModal();
});
