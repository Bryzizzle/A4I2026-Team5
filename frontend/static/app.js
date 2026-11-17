// Clinic Plan Console. Reads the SSE stream from /api/run or /api/replay and renders:
//   left  = the architecture live (pipeline, event log, session.state with writer -> readers)
//   right = the Clinic Plan (map + calendar, disagreement, coverage, audit, flyers, report)
"use strict";

// ------------------------------------------------------------------ architecture metadata
const STAGE = { need_scout: 0, coverage_scout: 0, respiratory_scout: 0,
                planner: 1, reviewer: 1, approval_gate: 1,
                auditor: 2, explainer: 3, reporter: 4 };
const OUTPUT_KEY = { need_scout: "evidence_need", coverage_scout: "evidence_coverage",
                     respiratory_scout: "evidence_respiratory", planner: "plan", reviewer: "review",
                     auditor: "audit", explainer: "flyer", reporter: "clinic_plan" };
// Which agent (or tool) writes each key, and who reads it. Order = display order.
const KEY_FLOW = [
  ["evidence_need",        "need_scout",        "planner"],
  ["evidence_coverage",    "coverage_scout",    "planner, reporter"],
  ["evidence_respiratory", "respiratory_scout", "reporter"],
  ["plan_round",           "plan_saturdays()",  "reporter"],
  ["plan_data",            "plan_saturdays()",  "check_plan_rules()"],
  ["plan_history",         "plan_saturdays()",  "this console"],
  ["picked_tract_ids",     "plan_saturdays()",  "auditor"],
  ["plan",                 "planner",           "reviewer, explainer, reporter"],
  ["review_findings",      "check_plan_rules()", "reviewer"],
  ["excluded_geo_ids",     "check_plan_rules()", "plan_saturdays() next round"],
  ["rejection_log",        "check_plan_rules()", "reporter"],
  ["plan_approved",        "check_plan_rules()", "approval_gate, auditor"],
  ["review",               "reviewer",          "planner (next round), reporter"],
  ["audit",                "auditor",           "reporter"],
  ["flyer",                "explainer",         "reporter"],
  ["clinic_plan",          "reporter",          "the outreach lead"],
];
const AUDIT_KEYS = new Set(["audit"]);

// ------------------------------------------------------------------ run state
let S = freshRun();
function freshRun() {
  return { state: {}, events: 0, startedAt: null, timer: null, running: false, error: false,
           openKeys: new Set(), lastHistoryJson: "", seenAgents: new Set() };
}

const $ = (id) => document.getElementById(id);
const md = (text) => DOMPurify.sanitize(marked.parse(String(text || "")));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtInt = (n) => (n == null || isNaN(n) ? "–" : Math.round(Number(n)).toLocaleString());
const fmtPct = (n) => (n == null || isNaN(n) ? "–" : `${Math.round(Number(n))}%`);

// ------------------------------------------------------------------ SSE
async function stream(url, opts) {
  resetUI();
  setRunning(true, url.includes("replay") ? "Replaying" : "Running live");
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    return fail(`Network error: ${e.message}`);
  }
  if (!res.ok) {
    const text = await res.text();
    let msg = text;
    try { msg = JSON.parse(text).detail || text; } catch (_) { /* plain text */ }
    return fail(`${res.status}: ${msg}`);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (!chunk || chunk.startsWith(":")) continue;
      const ev = /^event: (.*)$/m.exec(chunk), da = /^data: (.*)$/m.exec(chunk);
      if (ev && da) handle(ev[1], JSON.parse(da[1]));
    }
  }
  if (S.running) finish();
}

function handle(name, d) {
  if (name === "session") {
    setRunning(true, d.mode === "replay" ? "Replaying" : "Running live");
  } else if (name === "agent") {
    onAgentEvent(d);
  } else if (name === "final") {
    Object.assign(S.state, d.state || {});
    renderState(Object.keys(d.state || {}));
    renderResults();
    markAllDone();
  } else if (name === "error") {
    addLog({ t: "", author: "console", kind: "error", text: d.message + (d.where ? ` (${d.where})` : "") });
    fail(d.message);
  } else if (name === "done") {
    finish();
  }
}

// ------------------------------------------------------------------ agent events
function onAgentEvent(d) {
  S.events += 1;
  $("event-count").textContent = `${S.events} events`;
  setActive(d.author);
  addLog(d);

  if (d.kind === "tool_result" && d.tool === "check_plan_rules" && typeof d.approved === "boolean") {
    const round = S.state.plan_round || "?";
    const loop = $("loop"), verdict = $("loop-verdict"), reviewer = node("reviewer");
    if (d.approved) {
      loop.classList.remove("rejecting");
      reviewer && reviewer.classList.remove("rejected");
      verdict.innerHTML = `<span class="badge ok">approved in round ${esc(round)}</span>`;
    } else {
      loop.classList.add("rejecting");
      reviewer && reviewer.classList.add("rejected");
      verdict.innerHTML = `<span class="badge bad">round ${esc(round)} rejected</span>`;
    }
  }
  if (d.kind === "state") {
    const delta = d.state_delta || {};
    Object.assign(S.state, delta);
    if ("plan_round" in delta) $("round").textContent = delta.plan_round || "–";
    const out = OUTPUT_KEY[d.author];
    if (out && out in delta) markDone(d.author);
    renderState(Object.keys(delta));
    renderResults();
  }
}

// ------------------------------------------------------------------ pipeline
function node(agent) { return document.querySelector(`.node[data-agent="${agent}"]`); }

function setActive(agent) {
  const n = node(agent);
  if (!n) return;
  S.seenAgents.add(agent);
  const stage = STAGE[agent];
  document.querySelectorAll(".node").forEach((m) => {
    const a = m.dataset.agent, s = STAGE[a];
    if (s < stage && S.seenAgents.has(a)) { m.classList.remove("active"); m.classList.add("done"); }
    if (stage === 1 && s === 1 && a !== agent) m.classList.remove("active");   // loop: one at a time
  });
  n.classList.remove("done");
  n.classList.add("active");
}
function markDone(agent) {
  const n = node(agent);
  if (n) { n.classList.remove("active"); n.classList.add("done"); }
}
function markAllDone() {
  S.seenAgents.forEach(markDone);
}

// ------------------------------------------------------------------ event log
function addLog(d) {
  const log = $("log");
  if (S.events <= 1 && log.querySelector(".muted")) log.textContent = "";
  let what = "", cls = "";
  if (d.kind === "tool_call") {
    const args = Object.entries(d.args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
    what = `→ ${d.tool}(${args.length > 60 ? args.slice(0, 60) + "…" : args})`;
  } else if (d.kind === "tool_result") {
    what = `← ${d.tool}`;
    if (d.tool === "check_plan_rules" && d.approved === false) { what = "✗ REJECTED the plan"; cls = "reject"; }
    if (d.tool === "check_plan_rules" && d.approved === true) { what = "✓ approved the plan"; cls = "approve"; }
  } else if (d.kind === "text") {
    const t = String(d.text).replace(/\s+/g, " ").trim();
    what = `“${t.length > 90 ? t.slice(0, 90) + "…" : t}”`;
  } else if (d.kind === "state") {
    what = `writes ${Object.keys(d.state_delta || {}).join(", ")}`;
  } else if (d.kind === "escalate") {
    what = "ends the plan/review loop"; cls = "approve";
  } else if (d.kind === "error") {
    what = d.text; cls = "error";
  }
  const row = document.createElement("div");
  row.className = `row ${cls}`;
  row.innerHTML = `<span class="t">${d.t === "" ? "" : esc(Number(d.t).toFixed(1)) + "s"}</span>` +
                  `<span class="who">${esc(d.author)}</span><span class="what"></span>`;
  row.querySelector(".what").textContent = what;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

// ------------------------------------------------------------------ state panel
function shortValue(v) {
  if (v == null) return "null";
  if (typeof v === "string") return v.length > 40 ? `${v.length.toLocaleString()} chars` : v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (Array.isArray(v)) return `[${v.length}]`;
  return "{…}";
}
function renderState(changed = []) {
  const box = $("state");
  box.querySelectorAll("details[open]").forEach((d) => S.openKeys.add(d.dataset.key));
  box.querySelectorAll("details:not([open])").forEach((d) => S.openKeys.delete(d.dataset.key));
  const keys = KEY_FLOW.filter(([k]) => k in S.state);
  if (!keys.length) return;
  box.textContent = "";
  for (const [k, writer, readers] of keys) {
    const v = S.state[k];
    const det = document.createElement("details");
    det.dataset.key = k;
    if (AUDIT_KEYS.has(k)) det.classList.add("audit-key");
    if (S.openKeys.has(k)) det.open = true;
    if (changed.includes(k)) det.classList.add("flash");
    det.innerHTML = `<summary><span class="k">${esc(k)}</span><span class="v">${esc(shortValue(v))}</span>` +
      `<span class="flow"><span class="w">${esc(writer)}</span> → ${esc(readers)}</span></summary><pre></pre>`;
    det.querySelector("pre").textContent = typeof v === "string" ? v : JSON.stringify(v, null, 2);
    box.appendChild(det);
  }
}

// ------------------------------------------------------------------ results (right column)
function renderResults() {
  renderWhere();
  renderDisagreement();
  show("cant", S.state.evidence_coverage || S.state.evidence_respiratory, () => {
    $("cant-coverage").innerHTML = md(S.state.evidence_coverage || "_Waiting for the coverage scout…_");
    $("cant-resp").innerHTML = md(S.state.evidence_respiratory || "_Waiting for the respiratory scout…_");
  });
  show("audit", S.state.audit, () => { $("audit-content").innerHTML = md(S.state.audit); });
  renderFlyers();
  show("report", S.state.clinic_plan, () => { $("report-content").innerHTML = md(S.state.clinic_plan); });
}
function show(tab, hasData, fill) {
  const empty = $(`${tab}-empty`), content = $(`${tab}-content`);
  if (!hasData) return;
  empty.hidden = true;
  content.hidden = false;
  fill();
}

// --- Where: map + calendar
let map = null, mapLayer = null;
function nextMonthSaturdays(n = 4) {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  while (d.getDay() !== 6) d.setDate(d.getDate() + 1);
  return Array.from({ length: n }, (_, i) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + 7 * i));
}
function history() { return Array.isArray(S.state.plan_history) ? S.state.plan_history : []; }

function renderWhere() {
  const hist = history();
  if (!hist.length) return;
  const json = JSON.stringify(hist);
  if (json === S.lastHistoryJson) return;
  S.lastHistoryJson = json;
  $("where-empty").hidden = true;
  $("where-content").hidden = false;

  const final = hist[hist.length - 1].picked || [];
  const finalIds = new Set(final.map((p) => p.geo_id));
  const rejected = [];
  const seen = new Set();
  hist.slice(0, -1).forEach((h) => (h.picked || []).forEach((p) => {
    if (!finalIds.has(p.geo_id) && !seen.has(p.geo_id)) { seen.add(p.geo_id); rejected.push({ ...p, round: h.round }); }
  }));

  ensureMap();
  mapLayer.clearLayers();
  const pts = [];
  const radius = (pop) => 6 + Math.sqrt(Number(pop) || 0) / 8;
  rejected.forEach((p) => {
    if (p.latitude == null) return;
    L.circleMarker([p.latitude, p.longitude], { radius: radius(p.total_pop), color: cssVar("--bad"),
      weight: 2, dashArray: "4 3", fillOpacity: 0.08 })
      .bindTooltip(`Rejected in round ${p.round}: tract ${esc(p.geo_id)}`).addTo(mapLayer);
    pts.push([p.latitude, p.longitude]);
  });
  final.forEach((p, i) => {
    if (p.latitude == null) return;
    L.circleMarker([p.latitude, p.longitude], { radius: radius(p.total_pop), color: cssVar("--accent"),
      weight: 2, fillOpacity: 0.35 })
      .bindTooltip(`Saturday ${i + 1}: tract ${esc(p.geo_id)}, ${fmtInt(p.total_pop)} people`, { permanent: false })
      .addTo(mapLayer);
    L.marker([p.latitude, p.longitude], { icon: L.divIcon({ className: "", html:
      `<div style="font:700 12px system-ui;color:#fff;background:${cssVar("--accent")};border-radius:50%;width:20px;height:20px;line-height:20px;text-align:center;transform:translate(-4px,-4px)">${i + 1}</div>` }) })
      .addTo(mapLayer);
    pts.push([p.latitude, p.longitude]);
  });
  if (pts.length) map.fitBounds(pts, { padding: [40, 40], maxZoom: 12 });

  const dates = nextMonthSaturdays(final.length);
  $("cal").innerHTML = final.map((p, i) => `
    <article class="stop">
      <div class="date">${dates[i].toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</div>
      <h3>Census tract ${esc(p.geo_id)}</h3>
      <div class="muted" style="font-size:12px">need score ${esc(p.need_score)} · rank ${esc(p.need_rank ?? "–")}</div>
      <div class="facts">
        <div><b>${fmtInt(p.total_pop)}</b>people</div>
        <div><b>${p.km_to_safety_net == null ? "–" : Number(p.km_to_safety_net).toFixed(1) + " km"}</b>to safety-net site <span class="scale">straight line, upper bound</span></div>
        <div><b>${fmtPct(p.pct_uninsured)}</b>adults 18–64 uninsured <span class="scale">modeled</span></div>
        <div><b>${fmtPct(p.pct_no_vehicle)}</b>households, no vehicle <span class="scale">survey</span></div>
      </div>
      ${p.components_missing ? `<div class="flag">Scored with ${esc(p.components_missing)} input(s) missing</div>` : ""}
    </article>`).join("");
}
function ensureMap() {
  if (map) { setTimeout(() => map.invalidateSize(), 0); return; }
  map = L.map("map", { scrollWheelZoom: false }).setView([33.79, -84.47], 10);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
  mapLayer = L.layerGroup().addTo(map);
}
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

// --- Disagreement
function renderDisagreement() {
  const hist = history();
  const log = Array.isArray(S.state.rejection_log) ? S.state.rejection_log : [];
  const badge = $("disagree-count");
  badge.hidden = !log.length;
  badge.textContent = log.length;
  badge.className = `count badge${log.length ? " bad" : ""}`;
  if (!hist.length) return;
  $("disagree-empty").hidden = true;
  const box = $("disagree-content");
  box.hidden = false;

  const first = hist[0], last = hist[hist.length - 1];
  const firstIds = new Set((first.picked || []).map((p) => p.geo_id));
  const lastIds = new Set((last.picked || []).map((p) => p.geo_id));
  const col = (h, title, other, cls) => `
    <div class="round-col"><h3><span>${title}</span><span class="muted">round ${esc(h.round)}</span></h3>
      <ol>${(h.picked || []).map((p) => `<li class="${other.has(p.geo_id) ? "" : cls}">
        <span class="mono">${esc(p.geo_id)}</span> · ${fmtInt(p.total_pop)} people · score ${esc(p.need_score)}</li>`).join("")}</ol>
    </div>`;
  let html = "";
  if (hist.length > 1) {
    html += `<div class="rounds">${col(first, "First plan", lastIds, "gone")}${col(last, "Final plan", firstIds, "new")}</div>`;
  } else {
    html += `<div class="rounds">${col(last, "Plan", lastIds, "")}</div>`;
  }
  if (log.length) {
    html += log.map((r) => `
      <div class="rejection">
        <div class="head">Reviewer, round ${esc(r.round)}: ${esc(String(r.rule || "").replace(/_/g, " "))}</div>
        <div class="swap">✗ ${esc(r.reject)} → ✓ ${esc(r.prefer)}</div>
        <div>${esc(r.detail)}</div>
      </div>`).join("");
  } else if (S.state.plan_approved) {
    html += `<p class="muted" style="margin-top:12px">The reviewer approved the first plan: no rule was broken.</p>`;
  }
  if (S.state.review) {
    html += `<details style="margin-top:12px"><summary class="muted">Reviewer's final verdict (full text)</summary><div class="md">${md(S.state.review)}</div></details>`;
  }
  box.innerHTML = html;
}

// --- Flyers
let lang = "en";
function parseFlyers(text) {
  const sections = String(text || "").split(/^##\s+/m).slice(1);
  return sections.map((sec) => {
    const [titleLine, ...rest] = sec.split("\n");
    const body = rest.join("\n");
    const parts = body.split(/^###\s+/m).slice(1);
    const out = { title: titleLine.trim(), en: "", es: "" };
    parts.forEach((p) => {
      const [h, ...b] = p.split("\n");
      const head = h.trim().toLowerCase();
      if (head.startsWith("eng")) out.en = b.join("\n");
      else if (head.startsWith("esp") || head.startsWith("spa")) out.es = b.join("\n");
    });
    if (!out.en && !out.es) out.en = out.es = body;
    return out;
  });
}
function renderFlyers() {
  if (!S.state.flyer) return;
  $("flyer-empty").hidden = true;
  const flyers = parseFlyers(S.state.flyer);
  $("flyers").innerHTML = flyers.length
    ? flyers.map((f) => `<article class="flyer"><h3>${esc(f.title)}</h3><div class="md">${md(f[lang])}</div></article>`).join("")
    : `<article class="flyer"><div class="md">${md(S.state.flyer)}</div></article>`;
}

// ------------------------------------------------------------------ chrome
function setRunning(on, label) {
  S.running = on;
  $("btn-live").disabled = on;
  $("btn-replay").disabled = on;
  const pill = $("status");
  pill.className = `pill ${on ? "running" : ""}`;
  $("status-text").textContent = label;
  if (on && !S.timer) {
    S.startedAt = Date.now();
    S.timer = setInterval(() => { $("elapsed").textContent = `${Math.round((Date.now() - S.startedAt) / 1000)}s`; }, 500);
  }
}
function stopTimer() { clearInterval(S.timer); S.timer = null; }
function finish() {
  stopTimer();
  setRunning(false, S.error ? "Error" : "Done");
  $("status").className = `pill ${S.error ? "error" : "done"}`;
  markAllDone();
}
function fail(msg) {
  S.error = true;
  stopTimer();
  setRunning(false, "Error");
  $("status").className = "pill error";
  $("status-text").textContent = msg.length > 80 ? msg.slice(0, 80) + "…" : msg;
  $("status").title = msg;
}
function resetUI() {
  stopTimer();
  S = freshRun();
  $("elapsed").textContent = "";
  $("event-count").textContent = "";
  $("round").textContent = "–";
  $("loop-verdict").textContent = "";
  $("loop").classList.remove("rejecting");
  document.querySelectorAll(".node").forEach((n) => n.classList.remove("active", "done", "rejected"));
  $("log").innerHTML = '<div class="muted">Events appear here as each agent works.</div>';
  $("state").innerHTML = '<div class="muted">State keys appear as agents write them.</div>';
  for (const t of ["where", "disagree", "cant", "audit", "report"]) {
    $(`${t}-empty`).hidden = false;
    $(`${t}-content`).hidden = true;
  }
  $("flyer-empty").hidden = false;
  $("flyers").innerHTML = "";
  $("disagree-count").hidden = true;
  if (mapLayer) mapLayer.clearLayers();
}

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
  document.querySelectorAll(".panel").forEach((p) => { p.hidden = p.id !== `panel-${tab.dataset.tab}`; });
  if (tab.dataset.tab === "where" && map) setTimeout(() => map.invalidateSize(), 0);
}));
document.querySelectorAll(".lang button").forEach((b) => b.addEventListener("click", () => {
  lang = b.dataset.lang;
  document.querySelectorAll(".lang button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  renderFlyers();
}));
$("btn-print").addEventListener("click", () => window.print());
$("btn-live").addEventListener("click", () => stream("/api/run", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }));
$("btn-replay").addEventListener("click", () => stream(`/api/replay?speed=${$("speed").value}`));
