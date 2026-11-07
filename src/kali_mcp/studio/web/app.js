/* Playbook Studio SPA — routed, data-driven pages wired to /api/*.
 * No hardcoded content: every page renders live backend data.
 * Auth: 401 -> token prompt (localStorage 'kmcp_token', Bearer header).
 */
const API = window.API || "/api";
const TOKEN_KEY = "kmcp_token";

function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return [...root.querySelectorAll(sel)]; }
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ── API client ─────────────────────────────────────────────────────── */

function token() { return localStorage.getItem(TOKEN_KEY) || ""; }

function toast(msg, bad = false) {
  const el = $("#toast");
  if (!el) return;
  el.textContent = msg;
  el.style.borderColor = bad ? "#6b4343" : "";
  el.style.background = bad ? "#2e1d20" : "";
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => {
    el.classList.remove("show");
    el.style.borderColor = "";
    el.style.background = "";
  }, 2600);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (token()) headers.Authorization = `Bearer ${token()}`;
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401) {
    promptForToken();
    throw new Error("401 Unauthorized — API token required");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.error?.message || body?.error || `${res.status} ${res.statusText}`);
  return body?.data ?? body;
}

let pendingRetry = [];
function promptForToken() {
  $("#tokenModal").classList.add("open");
  $("#tokenInput").focus();
  return new Promise((resolve) => pendingRetry.push(resolve));
}

async function saveTokenAndRetry() {
  const value = $("#tokenInput").value.trim();
  if (!value) return;
  localStorage.setItem(TOKEN_KEY, value);
  $("#tokenModal").classList.remove("open");
  $("#tokenInput").value = "";
  refreshAuthBadge();
  toast("Token saved — reloading");
  pendingRetry.forEach((r) => r(true));
  pendingRetry = [];
  route();
}

/* ── shell helpers ─────────────────────────────────────────────────── */

function setPageMeta({ eyebrow, title, subtitle, actions = [], crumb } = {}) {
  const actionsEl = $("#topActions");
  if (actionsEl) actionsEl.innerHTML = actions
    .map((a, i) => `<button class="btn ${a.cls || "ghost"}" data-act="top${i}">${esc(a.label)}</button>`)
    .join("");
  if (actionsEl) {
    $$("#topActions [data-act]").forEach((btn, i) => {
      btn.addEventListener("click", () => { const f = actions[i]?.fn; if (f) f(); });
    });
  }
  const tail = $("#crumbPage");
  if (tail) tail.textContent = crumb || title || "";
  const titleEl = $("#crumbTitle");
  if (titleEl) titleEl.textContent = subtitle || "";
}

async function render() {
  const container = $("#content");
  container.innerHTML = `<section class="pagehead">
    <div class="page-top"><div id="pageHeadInfo"></div><div class="head-right" id="pageHeadActions"></div></div>
  </section><section class="pagebody" id="pageBody"></section>`;
  return container;
}

function headActionsHtml(buttons) {
  return buttons.map((b) => `<button class="btn ${b.cls || "ghost"}" id="${b.id}">${esc(b.label)}</button>`).join("");
}

/* ── shared widgets ────────────────────────────────────────────────── */

function kpis(items) {
  return `<div class="kpi-grid">${items.map((k) => `
    <div class="kpi"><div class="kpi-label">${esc(k.label)}</div>
      <div class="kpi-value">${esc(k.value)}</div>
      <div class="kpi-sub">${esc(k.sub || "")}</div></div>`).join("")}</div>`;
}

function table(headers, rows, emptyText = "Nothing here yet.") {
  if (!rows.length) return `<div class="panel table-panel"><p class="empty">${esc(emptyText)}</p></div>`;
  const cols = headers.length;
  return `<div class="panel table-panel" style="overflow:auto">
    <div class="table-head" style="grid-template-columns:repeat(${cols},minmax(0,1fr)) auto">
      ${headers.map((h) => `<span>${esc(h)}</span>`).join("")}<span></span>
    </div>
    ${rows.map((r) => `<div class="table-row" style="grid-template-columns:repeat(${cols},minmax(0,1fr)) auto">
      ${r.cells.map((c) => `<span>${c}</span>`).join("")}<span>${r.menu || ""}</span>
    </div>`).join("")}
  </div>`;
}

const BADGE = (s) => {
  const map = {
    completed: "run-state", running: "run-state run-run", pending: "run-state",
    failed: "run-state failed", cancelled: "run-state failed",
    draft: "run-state", published: "run-state ok", healthy: "run-state ok",
    unreachable: "run-state failed", critical: "run-state failed",
    high: "run-state failed", medium: "run-state warn", low: "run-state",
    info: "run-state",
  };
  return `<span class="${map[s] || "run-state"}">${esc(s || "—")}</span>`;
};

/* ── route: overview ───────────────────────────────────────────────── */

async function pageOverview() {
  setPageMeta({ crumb: "Overview", title: "Workspace overview", subtitle: "Live backend summary" });
  const o = await api("/overview");
  const execState = o.executions?.by_status || {};
  const fnd = o.findings?.by_severity || {};
  const runState = ["running", "completed", "failed", "cancelled"]
    .filter((s) => execState[s]).map((s) => `${s}: ${execState[s]}`).join(" · ") || "no runs yet";
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">OVERVIEW</div><h1>Overview</h1>
    <div class="subtitle">Everything below is read live from the database.</div>`;
  $("#pageBody").innerHTML = `
    ${kpis([
      { label: "Playbooks", value: o.playbooks?.total ?? 0, sub: Object.entries(o.playbooks?.by_status || {}).map(([k, v]) => `${k}: ${v}`).join(" · ") },
      { label: "Executions", value: o.executions?.total ?? 0, sub: runState },
      { label: "Tools", value: o.tools?.total ?? 0, sub: Object.entries(o.tools?.by_visibility || {}).map(([k, v]) => `${k}: ${v}`).join(" · ") },
      { label: "Findings", value: o.findings?.total ?? 0, sub: Object.entries(fnd).map(([k, v]) => `${k}: ${v}`).join(" · ") },
      { label: "MCP connections", value: o.connections?.total ?? 0, sub: `healthy: ${o.connections?.healthy ?? 0}` },
      { label: "Agent profiles", value: o.agents?.total ?? 0, sub: "" },
    ])}
    <div class="two-col">
      <div class="panel" style="min-height:220px">
        <div class="panel-head"><span>Recent executions</span></div>
        <div style="padding:8px">${table(["Execution", "Playbook", "Status", "Started"],
          (o.recent_executions || []).map((e) => ({
            cells: [esc(e.execution_id), esc(e.playbook_id || "—"), BADGE(e.status), esc((e.started_at || "").slice(0, 19))],
            menu: `<a href="#/executions/${esc(e.execution_id)}">view</a>`,
          })), "No executions yet.")}
        </div>
      </div>
      <div class="panel" style="min-height:220px">
        <div class="panel-head"><span>Latest findings</span></div>
        <div style="padding:8px">${table(["Target hint", "Tool", "Severity", "Test"],
          (o.recent_findings || []).map((f) => ({
            cells: [esc(f.port_state || f.status || "—"), esc(f.tool), BADGE(f.severity), esc(f.test_name || f.checkname || f.validation_status || "—")],
            menu: `<a href="#/findings">findings</a>`,
          })), "No findings yet.")}
        </div>
      </div>
    </div>`;
}

/* ── route: playbook studio ────────────────────────────────────────── */

let selectedId = null;
let playbooksCache = [];

async function refreshPlaybooks() {
  const d = await api("/playbooks?limit=200");
  playbooksCache = d.playbooks || [];
  renderPlaybookList();
  if (!selectedId && playbooksCache.length) await selectPlaybook(playbooksCache[0].playbook_id);
  if (!playbooksCache.length) {
    $("#dslCode") && ($("#dslCode").value = "");
    $("#editorTitle") && ($("#editorTitle").textContent = "No playbooks yet");
  }
}

function renderPlaybookList() {
  const el = $("#playbookList");
  if (!el) return;
  el.innerHTML = playbooksCache.length
    ? playbooksCache.map((p) => `
      <button class="playbook-item ${p.playbook_id === selectedId ? "active" : ""}" data-pb="${esc(p.playbook_id)}">
        <strong>${esc(p.name)}</strong><br/>
        <small>${esc(p.playbook_id)}</small> ${BADGE(p.status)}
      </button>`).join("")
    : `<p class="empty">No playbooks yet.</p>`;
  $$("#playbookList .playbook-item").forEach((btn) =>
    btn.addEventListener("click", () => selectPlaybook(btn.dataset.pb)));
}

async function selectPlaybook(id) {
  selectedId = id;
  renderPlaybookList();
  try {
    const [d, defn] = await Promise.all([
      api(`/playbooks/${encodeURIComponent(id)}`),
      api(`/playbooks/${encodeURIComponent(id)}/definition`).catch(() => ({ definition: null })),
    ]);
    const def = defn.definition;
    $("#dslCode").value = def ? JSON.stringify(def, null, 2) : "";
    $("#editorTitle").textContent = `${d.name} — ${id}`;
    $("#editorStatus").innerHTML = `${BADGE(d.status)} <span class="version">${esc(d.current_version_id || "no version")}</span>`;
    if (builderView === "graph") {
      if (loadGraphFromDSL()) renderBuilder();
    }
  } catch (err) {
    toast(err.message, true);
  }
}

async function saveDraft() {
  if (!selectedId) return toast("Select a playbook first", true);
  try {
    const body = { definition: JSON.parse($("#dslCode").value) };
    await api(`/playbooks/${encodeURIComponent(selectedId)}/definition`, {
      method: "PUT", body: JSON.stringify(body),
    });
    toast("Draft saved");
  } catch (err) {
    toast(err.message, true);
  }
}

async function publish() {
  if (!selectedId) return toast("Select a playbook first", true);
  await saveDraft();
  try {
    const def = JSON.parse($("#dslCode").value);
    const version = def.version || "1.0.0";
    await api(`/playbooks/${encodeURIComponent(selectedId)}/publish`, {
      method: "POST", body: JSON.stringify({ definition: def, version }),
    });
    toast(`Published ${version}`);
    await refreshPlaybooks();
  } catch (err) {
    if (/approval/i.test(err.message || "")) {
      if (confirm(`Publishing requires an approval request first.\nCreate the pending approval for ${selectedId} and retry?`)) {
        try {
          await api(`/playbooks/${encodeURIComponent(selectedId)}/approval-request`, { method: "POST" });
          toast("Approval request recorded — retrying publish");
          await publish();
        } catch (e2) { toast(e2.message, true); }
      }
      return;
    }
    toast(err.message, true);
  }
}

async function newPlaybook() {
  const name = prompt("Playbook name:");
  if (!name) return;
  try {
    await api("/playbooks", { method: "POST", body: JSON.stringify({ name, category: "custom" }) });
  } catch (err) { return toast(err.message, true); }
  await refreshPlaybooks();
  toast("Playbook created");
}

async function deletePlaybook() {
  if (!selectedId) return toast("Select a playbook first", true);
  if (!confirm(`Delete playbook ${selectedId}? This cannot be undone.`)) return;
  try {
    await api(`/playbooks/${encodeURIComponent(selectedId)}`, { method: "DELETE" });
    selectedId = null;
    await refreshPlaybooks();
    toast("Playbook deleted");
  } catch (err) { toast(err.message, true); }
}

async function showVersions() {
  if (!selectedId) return toast("Select a playbook first", true);
  try {
    const d = await api(`/playbooks/${encodeURIComponent(selectedId)}/versions`);
    const list = d.versions || [];
    if (!list.length) return toast("No versions published yet");
    const pick = list
      .map((v) => `${v.version_id}. ${v.version}`)
      .join("\n");
    const choice = prompt(`Versions:\n${pick}\n\nEnter version_id to roll back:`, "");
    if (!choice) return;
    await api(`/playbooks/${encodeURIComponent(selectedId)}/rollback`, {
      method: "POST", body: JSON.stringify({ version_id: choice }),
    });
    toast("Rolled back");
    await selectPlaybook(selectedId);
  } catch (err) { toast(err.message, true); }
}

async function exportPlaybook() {
  if (!selectedId) return toast("Select a playbook first", true);
  try {
    const pkg = await api(`/playbooks/${encodeURIComponent(selectedId)}/export`);
    const blob = new Blob([JSON.stringify(pkg, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${selectedId}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast("Export downloaded");
  } catch (err) { toast(err.message, true); }
}

async function importPlaybook() {
  const file = document.createElement("input");
  file.type = "file";
  file.accept = ".json";
  file.onchange = async () => {
    try {
      const pkg = JSON.parse(await file.files[0].text());
      await api("/playbooks/import", { method: "POST", body: JSON.stringify({ package: pkg }) });
      toast("Imported");
      await refreshPlaybooks();
    } catch (err) { toast(err.message, true); }
  };
  file.click();
}

async function pagePlaybooks() {
  builderView = "dsl"; graphDef = null; graphSel = null; graphPos = {}; graphZoom = 1;
  setPageMeta({
    crumb: "Playbook Studio", subtitle: "Plan & edit playbooks",
    actions: [{ label: "New", fn: newPlaybook }, { label: "Refresh", fn: refreshPlaybooks }],
  });
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">PLAYBOOK STUDIO</div><h1>Playbooks</h1>
    <div class="subtitle">Select a playbook and edit it in the DSL editor or visually in the graph builder. Save drafts, publish versions, roll back or export.</div>`;
  $("#pageHeadActions").innerHTML = headActionsHtml([
    { id: "refreshBtn", label: "↻ Refresh" },
    { id: "newPlaybookBtn", label: "＋ New", cls: "primary" },
  ]);
  $("#pageBody").innerHTML = `
  <section class="studio-grid">
    <aside class="playbook-list" id="playbookList">Loading…</aside>
    <section class="editor">
      <div class="panel-head">
        <span id="editorTitle">Select a playbook</span>
        <div class="mode-switch" id="builderSwitch">
          <button data-view="dsl" class="active">DSL editor</button>
          <button data-view="graph">Graph builder</button>
        </div>
        <span id="editorStatus"></span>
      </div>
      <div id="dslView">
        <textarea class="code-area" id="dslCode" spellcheck="false" placeholder="Playbook definition (JSON as returned by /definition)…"></textarea>
        <div class="editor-actions">
          <button class="btn" id="validateBtn">✓ Validate</button>
          <button class="btn" id="saveDraftBtn">Save draft</button>
          <button class="btn primary" id="publishBtn">Publish</button>
          <button class="btn" id="runBtn">▶ Run</button>
          <span style="flex:1"></span>
          <button class="btn ghost" id="versionsBtn">Versions / rollback</button>
          <button class="btn ghost" id="exportBtn">↗ Export</button>
          <button class="btn ghost" id="importBtn">↙ Import</button>
          <button class="btn danger" id="deleteBtn">Delete</button>
        </div>
      </div>
      <div id="graphView" class="builder" hidden>
        <div class="workarea">
          <div class="canvas-toolbar">
            <div class="mode-switch" id="graphCount">graph builder</div>
            <div class="canvas-tools">
              <button class="btn" id="addStepBtn">＋ Step</button>
              <button class="btn" id="resetLayoutBtn">Reset layout</button>
              <button class="btn" id="graphSaveBtn">Save draft</button>
              <button class="btn" id="graphValidateBtn">✓ Validate</button>
              <button class="btn" id="graphRunBtn">▶ Run</button>
            </div>
          </div>
          <div class="canvas-area" id="canvasArea">
            <div class="canvas-inner" id="canvasInner">
              <span class="canvas-label">EXECUTION GRAPH</span>
              <span class="canvas-hint">click a step to edit · drag to rearrange · drag <b>●</b> from a port onto another step to connect</span>
              <svg class="edges" id="edgeLayer"></svg>
              <div class="canvas-legend">
                <span><i class="legend-dot" style="background:#edc57c"></i>tool</span>
                <span><i class="legend-dot" style="background:#92dbad"></i>scope / report</span>
                <span><i class="legend-dot" style="background:#aabaff"></i>correlation</span>
              </div>
              <div class="add-node" id="addNodeTile" title="Add a step">＋ Add step</div>
              <div class="zoom" id="zoomCtl" title="Zoom">
                <button id="zoomOut" title="Zoom out">−</button>
                <button id="zoomReset" title="Reset zoom">⌂</button>
                <button id="zoomIn" title="Zoom in">＋</button>
              </div>
            </div>
          </div>
        </div>
        <aside class="inspector" id="inspector"></aside>
      </div>
      <pre class="result" id="editorResult" hidden></pre>
    </section>
  </section>`;
  $("#refreshBtn").addEventListener("click", () => refreshPlaybooks());
  $("#newPlaybookBtn").addEventListener("click", newPlaybook);

  $$("#builderSwitch button").forEach((btn) =>
    btn.addEventListener("click", () => switchBuilderView(btn.dataset.view)));

  $("#validateBtn").addEventListener("click", async () => {
    const out = $("#editorResult");
    if (!selectedId) return toast("Select a playbook first", true);
    try {
      const r = await api(`/playbooks/${encodeURIComponent(selectedId)}/validate-definition`, {
        method: "POST", body: JSON.stringify({ definition: JSON.parse($("#dslCode").value) }),
      });
      out.hidden = false;
      out.textContent = JSON.stringify(r, null, 2);
      toast(r.valid ? "Definition valid" : "Validation failed", !r.valid);
    } catch (err) {
      out.hidden = false;
      out.textContent = String(err);
      toast(err.message, true);
    }
  });
  $("#saveDraftBtn").addEventListener("click", saveDraft);
  $("#publishBtn").addEventListener("click", publish);
  $("#runBtn").addEventListener("click", () => runPlaybook(selectedId));
  $("#versionsBtn").addEventListener("click", showVersions);
  $("#exportBtn").addEventListener("click", exportPlaybook);
  $("#importBtn").addEventListener("click", importPlaybook);
  $("#deleteBtn").addEventListener("click", deletePlaybook);

  $("#addStepBtn").addEventListener("click", addGraphStep);
  $("#resetLayoutBtn").addEventListener("click", resetGraphLayout);  $("#graphSaveBtn").addEventListener("click", () => { captureGraphToDSL(); saveDraft(); });
  $("#graphValidateBtn").addEventListener("click", async () => {
    captureGraphToDSL();
    const out = $("#editorResult");
    if (!selectedId) return toast("Select a playbook first", true);
    try {
      const r = await api(`/playbooks/${encodeURIComponent(selectedId)}/validate-definition`, {
        method: "POST", body: JSON.stringify({ definition: JSON.parse($("#dslCode").value) }),
      });
      out.hidden = false;
      out.textContent = JSON.stringify(r, null, 2);
      toast(r.valid ? "Definition valid" : r.findings?.length + " validation finding(s)", !r.valid);
    } catch (err) { toast(err.message, true); }
  });
  $("#graphRunBtn").addEventListener("click", () => runPlaybook(selectedId));

  /* static canvas chrome: on-canvas ＋ tile + zoom controls (visual builder) */
  const addTile = $("#addNodeTile");
  if (addTile) addTile.addEventListener("click", (e) => { e.stopPropagation(); addGraphStep(); });
  const zi = $("#zoomIn"), zo = $("#zoomOut"), zr = $("#zoomReset");
  if (zi) zi.addEventListener("click", () => nudgeZoom(+0.25));
  if (zo) zo.addEventListener("click", () => nudgeZoom(-0.25));
  if (zr) zr.addEventListener("click", () => { graphZoom = 1; applyZoom(); });

  await refreshPlaybooks();
}

/* ── graph (visual) builder ────────────────────────────────────────── */

const NODE_W = 190, NODE_H = 111, X_GAP = 260, Y_GAP = 150;
let builderView = "dsl";
let graphDef = null;          // definition object while in graph view
let graphSel = null;          // selected step id
let graphPos = {};            // {stepId:{x,y}} drag overrides
let graphZoom = 1;

const TYPE_ICONS = {
  tool: { cls: "scan", glyph: "◎" },
  scope_check: { cls: "dns", glyph: "✓" },
  finding_correlation: { cls: "web", glyph: "⇄" },
  assessment_report: { cls: "out", glyph: "▤" },
};
const iconFor = (s) => TYPE_ICONS[s?.type] || { cls: "scan", glyph: "◈" };

function getGraphSteps() { return Array.isArray(graphDef?.steps) ? graphDef.steps : []; }

function loadGraphFromDSL() {
  const raw = $("#dslCode")?.value?.trim();
  if (raw) {
    try {
      graphDef = JSON.parse(raw);
    } catch (err) {
      toast("DSL is not valid JSON — fix the DSL before opening the graph: " + err.message, true);
      return false;
    }
  } else {
    graphDef = { name: selectedId || "empty", steps: [] };
  }
  if (!Array.isArray(graphDef.steps)) graphDef.steps = [];
  graphSel = null;
  graphPos = {};
  return true;
}

function captureGraphToDSL() {
  if (builderView !== "graph" || !graphDef) return;
  const t = $("#dslCode");
  if (t) t.value = JSON.stringify(graphDef, null, 2);
}

function switchBuilderView(view) {
  if (view === builderView && view === "graph") { renderBuilder(); return; }
  if (view === "graph") {
    if (!loadGraphFromDSL()) return;
  } else {
    captureGraphToDSL();
  }
  builderView = view;
  const dv = $("#dslView"), gv = $("#graphView");
  if (dv) dv.hidden = view !== "dsl";
  if (gv) gv.hidden = view !== "graph";
  $$("#builderSwitch button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (view === "graph") { renderBuilder(); } else { const inj = $("#inspector"); if (inj) inj.innerHTML = ""; }
}

function stepById(id) { return getGraphSteps().find((s) => s.id === id); }

/* cycle-safe longest-path layering (iterative relaxation) */
function graphLayout(depths) {
  const steps = getGraphSteps();
  const ids = new Set(steps.map((s) => s.id));
  steps.forEach((s) => { depths[s.id] = 0; });
  for (let iter = 0; iter < steps.length + 1; iter++) {
    let changed = false;
    for (const s of steps) {
      const deps = (s.depends_on || []).filter((d) => ids.has(d) && d !== s.id);
      const d = deps.length ? Math.max(...deps.map((x) => (depths[x] ?? 0) + 1)) : 0;
      if (d > depths[s.id]) { depths[s.id] = d; changed = true; }
    }
    if (!changed) break;
  }
}

function nodePos(id, depths) {
  if (graphPos[id]) return graphPos[id];
  const depth = depths[id] ?? 0;
  const sameLane = getGraphSteps().filter((s) => (depths[s.id] ?? 0) === depth);
  const yIdx = sameLane.findIndex((s) => s.id === id);
  return { x: 40 + depth * X_GAP, y: 193 + yIdx * Y_GAP };
}

function renderBuilder() {
  const inner = $("#canvasInner");
  if (!inner) return;
  const steps = getGraphSteps();
  const countEl = $("#graphCount");
  if (countEl) countEl.innerHTML = `<span>${steps.length} step${steps.length === 1 ? "" : "s"}</span>`;
  const depths = {};
  graphLayout(depths);

  // remove previous nodes, keep static chrome
  $$(".node", inner).forEach((n) => n.remove());
  inner.style.transform = `scale(${graphZoom})`;

  for (const s of steps) {
    const p = nodePos(s.id, depths);
    const ic = iconFor(s);
    const isTool = s.type === "tool";
    const argSummary = isTool
      ? `tool: ${s.tool || "?"} · ${Object.keys(s.args || {}).length} arg(s)`
      : Object.keys(s.args || {}).length ? `${Object.keys(s.args || {}).length} arg(s)` : "internal stage";
    const el = document.createElement("div");
    el.className = `node ${graphSel === s.id ? "selected" : ""}`;
    el.style.left = `${p.x}px`; el.style.top = `${p.y}px`;
    el.dataset.step = s.id;
    el.innerHTML = `
      <div class="node-top"><div class="node-icon ${ic.cls}">${ic.glyph}</div>
        <div><div class="node-title">${esc(s.id)}</div><div class="node-kind">${esc(s.type || "step")}</div></div>
        <span class="node-status ${(s.done || s.checkpoint) ? "done" : ""}"></span></div>
      <div class="node-body">${esc(argSummary)}${s.when ? `<br/>when: ${esc(s.when)}` : ""}</div>
      <div class="node-foot"><span class="chip">${esc((s.depends_on || []).length + " dep(s)")}</span>${s.checkpoint ? '<span class="chip">checkpoint</span>' : ""}</div>
      <span class="port left"></span><span class="port right"></span>`;
    el.addEventListener("mousedown", (e) => startNodeDrag(e, s.id, p));
    const rightPort = el.querySelector(".port.right");
    if (rightPort) {
      rightPort.addEventListener("mousedown", (e) => startPortConnect(e, s.id));
    }
    inner.appendChild(el);
  }

  // edges
  const svg = $("#edgeLayer");
  let edges = "";
  for (const s of steps) {
    for (const dep of s.depends_on || []) {
      if (!depths.hasOwnProperty(dep) || dep === s.id) continue;
      const a = nodePos(dep, depths), b = nodePos(s.id, depths);
      const x1 = a.x + NODE_W, y1 = a.y + 51, x2 = b.x, y2 = b.y + 51;
      const mx = (x1 + x2) / 2;
      edges += `<path class="edge" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
    }
  }
  svg.innerHTML = edges;
  renderInspector();
}

function renderInspector() {
  const inj = $("#inspector");
  const s = graphSel ? stepById(graphSel) : null;
  if (!s) {
    inj.innerHTML = `<div style="padding:14px"><div class="eyebrow">INSPECTOR</div>
      <p class="empty" style="padding:8px 0">Select a step on the canvas to edit id, type, tool, dependencies and args. Use ＋ Step to add one.</p></div>`;
    return;
  }
  inj.innerHTML = `<div style="padding:14px;display:flex;flex-direction:column;gap:10px;overflow:auto">
    <div class="eyebrow">INSPECTOR</div>
    <label class="dim" style="font-size:10px">Step id<input class="select" id="insId" value="${esc(s.id)}"></label>
    <label class="dim" style="font-size:10px">Type
      <select class="select" id="insType">
        ${["tool", "scope_check", "finding_correlation", "assessment_report", "custom"]
          .map((v) => `<option value="${v}" ${v === (s.type || "tool") ? "selected" : ""}>${v}</option>`).join("")}
      </select></label>
    <label class="dim" style="font-size:10px">Tool (type=tool)<input class="select" id="insTool" value="${esc(s.tool || "")}" placeholder="e.g. nuclei"></label>
    <label class="dim" style="font-size:10px">depends_on (comma separated)<input class="select" id="insDeps" value="${esc((s.depends_on || []).join(", "))}"></label>
    <label class="dim" style="font-size:10px">when (optional condition)<input class="select" id="insWhen" value="${esc(s.when || "")}"></label>
    <label class="dim" style="font-size:10px" style="display:flex;gap:6px;align-items:center">checkpoint
      <input type="checkbox" id="insCheckpoint" ${s.checkpoint ? "checked" : ""}></label>
    <label class="dim" style="font-size:10px">args (JSON)<textarea class="select" id="insArgs" style="min-height:110px;font-family:ui-monospace,Menlo,monospace;font-size:11px" spellcheck="false">${esc(JSON.stringify(s.args || {}, null, 2))}</textarea></label>
    <div style="display:flex;gap:8px">
      <button class="btn primary" id="insApply">Apply</button>
      <button class="btn danger" id="insDel">Delete step</button>
    </div>
  </div>`;
  $("#insApply").addEventListener("click", applyInspector);
  $("#insDel").addEventListener("click", () => deleteGraphStep(graphSel));
}

function applyInspector() {
  const s = stepById(graphSel);
  if (!s) return;
  const oldId = s.id;
  const newId = ($("#insId").value || "").trim();
  const ids = new Set(getGraphSteps().map((x) => x.id).filter((x) => x !== oldId));
  if (!newId) return toast("Step id required", true);
  if (newId !== oldId && ids.has(newId)) return toast(`Step id "${newId}" already used`, true);
  if (newId !== oldId) {
    getGraphSteps().forEach((x) => {
      if (Array.isArray(x.depends_on)) x.depends_on = x.depends_on.map((d) => (d === oldId ? newId : d));
    });
    delete graphPos[oldId];
  }
  s.id = newId;
  s.type = $("#insType").value;
  const tool = $("#insTool").value.trim();
  if (s.type === "tool") { if (tool) s.tool = tool; else delete s.tool; }
  else delete s.tool;
  s.depends_on = $("#insDeps").value.split(",").map((d) => d.trim()).filter(Boolean);
  if (!Array.isArray(s.depends_on)) s.depends_on = [];
  const when = $("#insWhen").value.trim();
  if (when) s.when = when; else delete s.when;
  if ($("#insCheckpoint").checked) s.checkpoint = true; else delete s.checkpoint;
  try {
    const parsed = JSON.parse($("#insArgs").value || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      if (Object.keys(parsed).length) s.args = parsed; else delete s.args;
    } else { toast("args must be a JSON object — kept previous value", true); }
  } catch { return toast("args is not valid JSON — nothing applied for args", true); }

  graphSel = s.id;
  renderBuilder();
  captureGraphToDSL();
  toast(`Step ${s.id} updated`);
}

function deleteGraphStep(id) {
  graphDef.steps = getGraphSteps().filter((s) => s.id !== id);
  getGraphSteps().forEach((s) => {
    if (Array.isArray(s.depends_on)) s.depends_on = s.depends_on.filter((d) => d !== id);
  });
  graphSel = null;
  captureGraphToDSL();
  renderBuilder();
  toast(`Step ${id} deleted`);
}

function addGraphStep() {
  if (builderView !== "graph") {
    if (!loadGraphFromDSL()) return;
  }
  let n = 1, id;
  do { id = `step_${n++}`; } while (stepById(id));
  getGraphSteps().push({ id, type: "tool", depends_on: [] });
  graphSel = id;
  renderBuilder();
  captureGraphToDSL();
  toast(`Added ${id}`);
}

function resetGraphLayout() { graphPos = {}; graphZoom = 1; renderBuilder(); toast("Layout reset"); }

/* node dragging: pointer capture on .node */
let dragCtx = null;
function startNodeDrag(e, id, origin) {
  e.preventDefault();
  const startX = e.clientX, startY = e.clientY;
  const ox = origin.x, oy = origin.y;
  let moved = false;
  const move = (ev) => {
    const dx = ev.clientX - startX, dy = ev.clientY - startY;
    if (!moved && Math.hypot(dx, dy) < 4) return;
    moved = true;
    const x = Math.max(0, Math.round(ox + dx / graphZoom)), y = Math.max(0, Math.round(oy + dy / graphZoom));
    graphPos[id] = { x, y };
    const el = $(`.node[data-step="${CSS.escape(id)}"]`);
    if (el) { el.style.left = `${x}px`; el.style.top = `${y}px`; }
    redrawEdges();
  };
  const up = () => {
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", up);
    if (!moved) { graphSel = id; renderBuilder(); }
  };
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
}

/* edge creation: drag from a node's right port onto another node
   (adds srcId to the target step's depends_on, cycle-checked) */
let connectCtx = null;

function wouldCreateCycle(srcId, tgtId) {
  // Adding src as a dependency of tgt closes a loop only if src already
  // depends (transitively) on tgt.
  if (srcId === tgtId) return true;
  const seen = new Set();
  const stack = [srcId];
  while (stack.length) {
    const cur = stack.pop();
    if (cur === tgtId) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    const s = stepById(cur);
    (s?.depends_on || []).forEach((d) => stack.push(d));
  }
  return false;
}

function clearConnectPreview() {
  const p = $("#connectPreview");
  if (p) p.remove();
}

function startPortConnect(e, srcId) {
  e.preventDefault();
  e.stopPropagation();
  const depths = {};
  graphLayout(depths);
  const a = nodePos(srcId, depths);
  const x1 = a.x + NODE_W, y1 = a.y + 51;
  connectCtx = { srcId, depths };
  const inner = $("#canvasInner");
  const toCanvas = (ev) => {
    const r = inner.getBoundingClientRect();
    return { x: (ev.clientX - r.left) / graphZoom, y: (ev.clientY - r.top) / graphZoom };
  };
  const move = (ev) => {
    const m = toCanvas(ev);
    const mx = (x1 + m.x) / 2;
    clearConnectPreview();
    const svg = $("#edgeLayer");
    if (!svg) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.id = "connectPreview";
    path.setAttribute("class", "edge");
    path.setAttribute("d", `M${x1},${y1} C${mx},${y1} ${mx},${m.y} ${m.x},${m.y}`);
    svg.appendChild(path);
  };
  const up = (ev) => {
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", up);
    clearConnectPreview();
    connectCtx = null;
    const hit = document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".node");
    if (!hit) return;
    const tgtId = hit.dataset.step;
    if (!tgtId) return;
    const s = stepById(tgtId);
    if (!s) return;
    if (tgtId === srcId) return toast("A step cannot depend on itself", true);
    if (wouldCreateCycle(srcId, tgtId)) return toast(`Wire ${srcId} → ${tgtId} would create a cycle`, true);
    s.depends_on = Array.isArray(s.depends_on) ? s.depends_on : [];
    if (s.depends_on.includes(srcId)) return toast(`${tgtId} already depends on ${srcId}`);
    s.depends_on.push(srcId);
    renderBuilder();
    captureGraphToDSL();
    toast(`Connected ${srcId} → ${tgtId}`);
  };
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
}

/* zoom: 0.25x – 2x on the canvas inner */
function applyZoom() {
  const inner = $("#canvasInner");
  if (inner) inner.style.transform = `scale(${graphZoom})`;
}

function nudgeZoom(delta) {
  graphZoom = Math.min(2, Math.max(0.25, Math.round((graphZoom + delta) * 100) / 100));
  applyZoom();
}

function redrawEdges() {
  const inner = $("#canvasInner");
  const depths = {};
  graphLayout(depths);
  const svg = $("#edgeLayer");
  let edges = "";
  for (const s of getGraphSteps()) {
    for (const dep of s.depends_on || []) {
      if (!depths.hasOwnProperty(dep) || dep === s.id) continue;
      const a = nodePos(dep, depths), b = nodePos(s.id, depths);
      const x1 = a.x + NODE_W, y1 = a.y + 51, x2 = b.x, y2 = b.y + 51;
      const mx = (x1 + x2) / 2;
      edges += `<path class="edge" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`;
    }
  }
  svg.innerHTML = edges;
}

/* ── route: executions ─────────────────────────────────────────────── */

let execTimer = null;

async function refreshExecutions(status) {
  const q = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "?limit=100";
  const d = await api(`/executions${q}`);
  const list = d.executions || [];
  const el = $("#execTable");
  if (!el) return;
  el.innerHTML = table(["Execution", "Playbook", "Status", "Started", "Completed"],
    list.map((e) => ({
      cells: [
        `<a href="#/executions/${esc(e.execution_id)}">${esc(e.execution_id)}</a>`,
        esc(e.playbook_id || "—"), BADGE(e.status),
        esc((e.started_at || "").slice(0, 19)),
        esc((e.completed_at || "").slice(0, 19) || "—"),
      ],
      menu: `<a href="#/executions/${esc(e.execution_id)}">detail</a>`,
    })), "No executions match this filter.");
}

async function runPlaybook(pid) {
  const id = pid || selectedId;
  if (!id) return toast("Select a playbook first", true);
  let inputs = {};
  const raw = prompt(`Run "${id}" now (runs the published version).\nInputs JSON (optional, e.g. {"target":"127.0.0.1"}):`, "{}");
  if (raw === null) return;
  if (raw.trim()) {
    try { inputs = JSON.parse(raw); } catch { return toast("Inputs must be valid JSON", true); }
  }
  toast(`Starting ${id}…`);
  try {
    const r = await api("/executions", { method: "POST", body: JSON.stringify({ playbook_id: id, inputs }) });
    const execId = r?.execution?.execution_id || r?.execution_id || "";
    toast(`Run started${execId ? `: ${execId}` : ""}`);
    if (execId) location.hash = `#/executions/${encodeURIComponent(execId)}`;
    else { location.hash = "#/executions"; }
  } catch (err) { toast(err.message, true); }
}

async function pageExecutions() {
  setPageMeta({
    crumb: "Executions", title: "Executions", subtitle: "Live workflow runs",
    actions: [{ label: "▶ Run…", fn: () => runPlaybook(prompt("Playbook id to run:", "")) }, { label: "Refresh", fn: () => refreshExecutions($("#execFilter")?.value || "all") }],
  });
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">EXECUTIONS</div><h1>Executions</h1>
    <div class="subtitle">Workflow runs from the DAG engine, newest first. Click an execution for step detail.</div>`;
  $("#pageBody").innerHTML = `
    <div class="filterbar">
      <select id="execFilter" class="select">
        <option value="all">All statuses</option>
        <option value="running">running</option>
        <option value="pending">pending</option>
        <option value="completed">completed</option>
        <option value="failed">failed</option>
        <option value="cancelled">cancelled</option>
      </select>
      <label class="checkline"><input type="checkbox" id="execAuto" /> auto-refresh every 5s</label>
    </div>
    <div id="execTable">Loading…</div>`;
  $("#execFilter").addEventListener("change", () => refreshExecutions($("#execFilter").value));
  $("#execAuto").addEventListener("change", () => {
    if ($("#execAuto").checked) execTimer = setInterval(() => refreshExecutions($("#execFilter").value), 5000);
    else if (execTimer) { clearInterval(execTimer); execTimer = null; }
  });
  await refreshExecutions("all");
}

async function pageExecutionDetail(id) {
  setPageMeta({ crumb: "Executions", title: id, subtitle: "Execution detail" });
  const d = await api(`/executions/${encodeURIComponent(id)}`);
  const e = d.execution;
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">EXECUTIONS</div><h1>${esc(id)}</h1>
    <div class="subtitle">${esc(e.playbook_id || "")} <span style="margin-left:8px">${BADGE(e.status)}</span></div>`;
  $("#pageBody").innerHTML = `
    <div class="detail-actions">
      <button class="btn" id="cancelExecBtn">Cancel</button>
      <button class="btn" id="resumeExecBtn">Resume from checkpoint</button>
      <a class="btn ghost" href="#/executions">← back</a>
    </div>
    ${kpis([
      { label: "Steps", value: (d.steps || []).length },
      { label: "Artifacts", value: (d.artifacts || []).length },
      { label: "Started", value: (e.started_at || "").slice(0, 19) },
      { label: "Completed", value: (e.completed_at || "").slice(0, 19) || "—" },
    ])}
    <div class="panel" style="margin-top:14px;padding:14px"><pre class="result">${esc(JSON.stringify(e, null, 2))}</pre></div>
    <div class="panel" style="min-height:120px">
      <div class="panel-head"><span>Steps</span></div>
      <div style="padding:8px">${table(["Step", "Type", "Tool", "Status"], (d.steps || []).map((s) => ({
        cells: [esc(s.step_id), esc(s.step_type || "—"), esc(s.tool_id || "—"), BADGE(s.status)],
      })), "No steps recorded.")}</div>
    </div>
    <div class="panel" style="min-height:120px;margin-top:14px">
      <div class="panel-head"><span>Artifacts</span></div>
      <div style="padding:8px">${table(["Artifact", "Category"], (d.artifacts || []).map((a) => ({
        cells: [esc(a.name || a.artifact_id || a.evidence_id || "—"), esc(a.category || "—")],
      })), "No artifacts recorded.")}</div>
    </div>`;
  $("#cancelExecBtn").addEventListener("click", async () => {
    if (!confirm(`Cancel ${id}?`)) return;
    try { await api(`/executions/${encodeURIComponent(id)}/cancel`, { method: "POST" }); toast("Cancelled"); pageExecutionDetail(id); }
    catch (err) { toast(err.message, true); }
  });
  $("#resumeExecBtn").addEventListener("click", async () => {
    try { await api(`/executions/${encodeURIComponent(id)}/resume`, { method: "POST" }); toast("Resume requested"); pageExecutionDetail(id); }
    catch (err) { toast(err.message, true); }
  });
}

/* ── route: tool registry ──────────────────────────────────────────── */

let toolsCache = [];

async function refreshTools() {
  const el = $("#toolTable");
  if (el) el.innerHTML = `<div class="panel table-panel"><p class="empty">Loading tools…</p></div>`;
  const hint = $("#toolHint");
  try {
    const d = await api("/tools?limit=500");
    toolsCache = d.tools || [];
    renderTools();
    if (hint) {
      if (toolsCache.length) {
        hint.textContent = "";
      } else {
        const srv = await toolRegistryHint().catch(() => "");
        hint.innerHTML = `<div class="panel" style="padding:12px"><p class="empty">No tools registered — import MCP connections to populate the registry.</p>
          <p class="dim" style="font-size:11px">This list is read straight from the running server's database. ${esc(srv)}<br/>
          If you expected tools here: hard-refresh this page (Cmd/Ctrl+Shift+R) to drop a cached script, and check that you are connected to the intended server/port.</p></div>`;
      }
    }
  } catch (err) {
    if (el) el.innerHTML = `<div class="panel table-panel"><p class="empty">Failed to load tools: ${esc(err.message)}</p></div>`;
    if (hint) hint.textContent = "";
  }
}

async function toolRegistryHint() {
  try {
    const s = await api("/server");
    const parts = [`db: ${s.db_path || "unknown"} (${s.db_exists ? "file exists" : "file missing"})`];
    return parts.join(" · ");
  } catch { return ""; }
}

function renderTools() {
  const el = $("#toolTable");
  if (!el) return;
  const q = ($("#toolSearch").value || "").toLowerCase();
  const rows = toolsCache.filter((t) =>
    !q || String(t.tool_id).toLowerCase().includes(q) || String(t.name || "").toLowerCase().includes(q));
  el.innerHTML = table(["Tool", "Provider", "Visibility", "Enabled", "Timeout"],
    rows.map((t) => {
      const isBuiltin = t.provider === "native" || t.provider === "builtin";
      const opts = ["agent_callable", "playbook_selectable", "internal", "hidden"]
        .map((v) => `<option value="${v}" ${v === t.visibility ? "selected" : ""}>${v}</option>`).join("");
      return {
        cells: [esc(t.tool_id), esc(t.provider || "—"),
          `<select class="select sel-vis" data-tool="${esc(t.tool_id)}">${opts}</select>`,
          t.enabled ? "yes" : "no", esc(t.default_timeout ?? "—")],
        menu: isBuiltin ? `<span class="dim">builtin</span>` : "",
      };
    }), "No tools registered — import MCP connections to populate the registry.");
  $$(".sel-vis", el).forEach((sel) => sel.addEventListener("change", async () => {
    try {
      const id = sel.dataset.tool;
      if (sel.value === "agent_callable") {
        await api(`/tools/${encodeURIComponent(id)}/visibility`, { method: "PUT", body: JSON.stringify({ visibility: sel.value }) });
      } else {
        await api(`/tools/${encodeURIComponent(id)}/visibility`, { method: "PUT", body: JSON.stringify({ visibility: sel.value }) });
      }
      toast(`${id} → ${sel.value}`);
    } catch (err) { toast(err.message, true); }
  }));
}

async function pageTools() {
  setPageMeta({
    crumb: "Tool Registry", title: "Tool Registry", subtitle: "Live catalog from the database",
    actions: [{ label: "Refresh", fn: refreshTools }],
  });
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">TOOL REGISTRY</div><h1>Tool Registry</h1>
    <div class="subtitle">Every tool known to the backend. Changing visibility writes straight to the DB (promoting to agent_callable may require an approval).</div>`;
  $("#pageBody").innerHTML = `
    <div id="toolHint"></div>
    <div class="filterbar"><input class="select" id="toolSearch" placeholder="Search tool id or name…" /></div>
    <div id="toolTable">Loading…</div>`;
  $("#toolSearch").addEventListener("input", renderTools);
  await refreshTools();
}

/* ── route: connections ────────────────────────────────────────────── */

let connectionsCache = [];

async function refreshConnections() {
  const d = await api("/connections");
  connectionsCache = d.connections || [];
  renderConnections();
}

function renderConnections() {
  const el = $("#connTable");
  if (!el) return;
  el.innerHTML = table(["Connection", "Transport", "Endpoint", "Health", "Exported tools"],
    connectionsCache.map((c) => ({
      cells: [
        `<a href="#/connections/${esc(c.connection_id)}">${esc(c.connection_id)}</a><br/><small class="dim">${esc(c.name || "")}</small>`,
        esc(c.transport || "—"),
        esc(c.endpoint_url || c.command || "—"),
        c.enabled ? BADGE(c.health_status || "unknown") : "disabled",
        esc(c.imported_tool_count ?? 0),
      ],
      menu: `<button class="btn mini" data-conn="${esc(c.connection_id)}" data-connact="test">Test</button>
             <button class="btn mini" data-conn="${esc(c.connection_id)}" data-connact="discover">Discover</button>
             <button class="btn mini danger" data-conn="${esc(c.connection_id)}" data-connact="delete">Delete</button>`,
    }), "No connections yet. Add one to import external MCP tools."));
  $$("button[data-conn]", el).forEach((btn) => btn.addEventListener("click", async () => {
    const id = btn.dataset.conn;
    const act = btn.dataset.connact;
    if (act === "delete" && !confirm(`Delete connection ${id}?`)) return;
    const map = {
      test: { path: `/connections/${encodeURIComponent(id)}/test`, method: "POST" },
      discover: { path: `/connections/${encodeURIComponent(id)}/discover`, method: "POST", body: "{}" },
      delete: { path: `/connections/${encodeURIComponent(id)}`, method: "DELETE" },
    }[act];
    try { await api(map.path, { method: map.method, body: map.body }); toast(act + " ok"); refreshConnections(); }
    catch (err) { toast(err.message, true); }
  }));
}

function connectionModal() {
  const id = prompt("connection_id (unique):"); if (!id) return;
  const name = prompt("Friendly name:"); if (!name) return;
  const transport = prompt("transport (sse | streamable-http | stdio):", "sse"); if (!transport) return;
  const endpointUrl = transport !== "stdio" ? prompt("endpoint_url:") : "";
  const command = transport === "stdio" ? prompt("command (e.g. npx mcp-server-fs):") : "";
  const payload = { connection_id: id, name, transport };
  if (endpointUrl) payload.endpoint_url = endpointUrl;
  if (command) payload.command = command;
  api("/connections", { method: "POST", body: JSON.stringify(payload) })
    .then(() => { toast("Connection added"); return refreshConnections(); })
    .catch((err) => toast(err.message, true));
}

async function pageConnections() {
  setPageMeta({
    crumb: "MCP Connections", title: "MCP Connections", subtitle: "External servers & imported tool counts",
    actions: [{ label: "Refresh", fn: refreshConnections }, { label: "＋ Add connection", fn: connectionModal }],
  });
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">MCP CONNECTIONS</div><h1>MCP Connections</h1>
    <div class="subtitle">Registered external MCP servers. Test probes connectivity; Discover imports tools (imported as internal visibility by default).</div>`;
  $("#pageBody").innerHTML = `<div id="connTable">Loading…</div>`;
  await refreshConnections();
}

async function pageConnectionDetail(id) {
  setPageMeta({ crumb: "MCP Connections", title: id, subtitle: "Connection detail" });
  const d = await api(`/connections/${encodeURIComponent(id)}`);
  const c = d.connection;
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">MCP CONNECTIONS</div><h1>${esc(id)}</h1>
    <div class="subtitle">${esc(c.name || "")} · transport ${esc(c.transport)} ${BADGE(c.health_status || "unknown")}</div>`;
  $("#pageBody").innerHTML = `
    <div class="detail-actions"><a class="btn ghost" href="#/connections">← back</a></div>
    <div class="panel" style="padding:14px"><pre class="result">${esc(JSON.stringify(c, null, 2))}</pre></div>
    <div class="panel" style="min-height:120px;margin-top:14px">
      <div class="panel-head"><span>Imported tools</span>
        <button class="btn mini" id="discoverBtn">Discover &amp; import</button></div>
      <div style="padding:8px">${table(["Tool", "Visibility"], (d.imported_tools || []).map((t) => ({
        cells: [esc(t.tool_id), esc(t.visibility || "—")],
      })), "Nothing imported from this connection yet.")}</div>
    </div>`;
  $("#discoverBtn").addEventListener("click", async () => {
    try {
      const r = await api(`/connections/${encodeURIComponent(id)}/discover`, { method: "POST", body: "{}" });
      toast(`Imported ${(r.imported_tools || []).length} tools`);
      pageConnectionDetail(id);
    } catch (err) { toast(err.message, true); }
  });
}

/* ── route: agents ─────────────────────────────────────────────────── */

async function refreshAgents() {
  const d = await api("/agents");
  const agents = d.agents || [];
  const el = $("#agentTable");
  if (!el) return;
  el.innerHTML = table(["Profile", "Description", "Default visibility", "Parallel / Timeout", "Grants"],
    agents.map((a) => ({
      cells: [
        `<a href="#/agents/${esc(a.profile_id)}">${esc(a.profile_id)}</a><br/><small class="dim">${esc(a.name || "")}</small>`,
        esc(a.description || "—"),
        esc(a.default_visibility || "internal"),
        `${a.max_parallel_operations ?? "—"} / ${a.max_execution_seconds ?? "—"}s`,
        `tools: ${a.tool_grants ?? 0} · playbooks: ${a.playbook_grants ?? 0}`,
      ],
    })), "No agent profiles. One is created for you on first tool grant.");
}

function agentModal() {
  const id = prompt("profile_id (unique):"); if (!id) return;
  const name = prompt("Friendly name:"); if (!name) return;
  api("/agents", { method: "POST", body: JSON.stringify({ profile_id: id, name }) })
    .then(() => { toast("Agent profile created"); refreshAgents(); })
    .catch((err) => toast(err.message, true));
}

async function pageAgents() {
  setPageMeta({
    crumb: "Agents", title: "Agents", subtitle: "Profiles, tool grants & playbook assignments",
    actions: [{ label: "Refresh", fn: refreshAgents }, { label: "＋ New profile", fn: agentModal }],
  });
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">AGENTS</div><h1>Agents</h1>
    <div class="subtitle">Deny-by-default catalogs: an agent can only call tools and run playbooks explicitly granted to its profile.</div>`;
  $("#pageBody").innerHTML = `<div id="agentTable">Loading…</div>`;
  await refreshAgents();
}

async function pageAgentDetail(id) {
  setPageMeta({ crumb: "Agents", title: id, subtitle: "Agent profile" });
  const d = await api(`/agents/${encodeURIComponent(id)}`);
  const a = d.agent;
  const catalogs = d.effective_catalog || {};
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">AGENTS</div><h1>${esc(id)}</h1>
    <div class="subtitle">${esc(a.name || "")} · parallel ${a.max_parallel_operations ?? "—"} · timeout ${a.max_execution_seconds ?? "—"}s</div>`;
  $("#pageBody").innerHTML = `
    <div class="detail-actions"><a class="btn ghost" href="#/agents">← back</a>
      <button class="btn danger" id="delAgentBtn">Delete profile</button></div>
    ${kpis([
      { label: "Callable tools", value: catalogs.tools?.length ?? 0 },
      { label: "Assignable playbooks", value: catalogs.playbooks?.length ?? 0 },
      { label: "Default visibility", value: a.default_visibility || "internal" },
    ])}
    <div class="panel" style="min-height:140px;margin-top:14px">
      <div class="panel-head"><span>Tool grants</span>
        <button class="btn mini" id="grantBtn">Grant tool</button></div>
      <div style="padding:8px">${table(["Tool", "Granted", "Granted at"],
        (d.permissions || []).filter((p) => p.profile_id === id).map((p) => ({
          cells: [esc(p.tool_id), p.granted ? "<span class='run-state ok'>granted</span>" : "<span class='run-state failed'>denied</span>",
            esc((p.granted_at || "").slice(0, 19))],
          menu: `<button class="btn mini danger" data-tool="${esc(p.tool_id)}" data-toolact="revoke">Revoke</button>`,
        })), "No tool grants yet. Grant one to allow this agent to call a tool.")}</div>
    </div>
    <div class="panel" style="min-height:140px;margin-top:14px">
      <div class="panel-head"><span>Playbook assignments</span>
        <button class="btn mini" id="assignBtn">Assign playbook</button></div>
      <div style="padding:8px">${table(["Playbook", "Granted", "Granted at"],
        (d.assignments || []).filter((x) => x.profile_id === id).map((x) => ({
          cells: [esc(x.playbook_id), x.granted ? "<span class='run-state ok'>assigned</span>" : "<span class='run-state failed'>blocked</span>",
            esc((x.granted_at || "").slice(0, 19))],
          menu: `<button class="btn mini danger" data-pb="${esc(x.playbook_id)}" data-pbact="unassign">Unassign</button>`,
        })), "No playbook assignments yet.")}</div>
    </div>`;
  $("#grantBtn").addEventListener("click", () => {
    const toolId = prompt("tool_id to grant:"); if (!toolId) return;
    api(`/agents/${encodeURIComponent(id)}/tools/${encodeURIComponent(toolId)}`, { method: "PUT", body: "{}" })
      .then(() => { toast("Granted"); pageAgentDetail(id); })
      .catch((err) => toast(err.message, true));
  });
  $("#assignBtn").addEventListener("click", () => {
    const pbId = prompt("playbook_id to assign:"); if (!pbId) return;
    api(`/agents/${encodeURIComponent(id)}/playbooks/${encodeURIComponent(pbId)}`, { method: "PUT", body: "{}" })
      .then(() => { toast("Assigned"); pageAgentDetail(id); })
      .catch((err) => toast(err.message, true));
  });
  $("#delAgentBtn").addEventListener("click", () => {
    if (!confirm(`Delete agent profile ${id}?`)) return;
    api(`/agents/${encodeURIComponent(id)}`, { method: "DELETE" })
      .then(() => { toast("Deleted"); location.hash = "#/agents"; })
      .catch((err) => toast(err.message, true));
  });
  $$("button[data-tool]", $("#pageBody")).forEach((b) => b.addEventListener("click", async () => {
    await api(`/agents/${encodeURIComponent(id)}/tools/${encodeURIComponent(b.dataset.tool)}`, { method: "DELETE" });
    pageAgentDetail(id);
  }));
  $$("button[data-pb]", $("#pageBody")).forEach((b) => b.addEventListener("click", async () => {
    await api(`/agents/${encodeURIComponent(id)}/playbooks/${encodeURIComponent(b.dataset.pb)}`, { method: "DELETE" });
    pageAgentDetail(id);
  }));
}

/* ── route: findings ───────────────────────────────────────────────── */

let findingsTimer = null;

async function refreshFindings() {
  const params = new URLSearchParams();
  const sev = $("#fndSeverity")?.value;
  const tgt = $("#fndTarget")?.value?.trim();
  const tool = $("#fndTool")?.value?.trim();
  if (sev && sev !== "all") params.set("severity", sev);
  if (tgt) params.set("target", tgt);
  if (tool) params.set("tool", tool);
  const d = await api(`/findings?${params}`);
  const el = $("#findingTable");
  if (!el) return;
  el.innerHTML = `${kpis([{ label: "Matching findings", value: d.count ?? 0 }])}${table(["Test", "Severity", "Tool", "Status", "Created"],
    (d.findings || []).map((f) => ({
      cells: [esc(f.test_name || f.checkname || f.name || "—"), BADGE(f.severity), esc(f.tool), esc(f.status || f.validation_status || "—"), esc((f.created_at || "").slice(0, 19))],
    })), "No findings match these filters.")}`;
}

async function pageFindings() {
  setPageMeta({
    crumb: "Findings", title: "Findings", subtitle: "Normalized findings across all scans",
    actions: [{ label: "Refresh", fn: refreshFindings }],
  });
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">FINDINGS</div><h1>Findings</h1>
    <div class="subtitle">Query the normalized findings table. Filters hit the database directly.</div>`;
  $("#pageBody").innerHTML = `
    <div class="filterbar">
      <select id="fndSeverity" class="select">
        <option value="all">All severities</option>
        <option value="critical">critical</option><option value="high">high</option>
        <option value="medium">medium</option><option value="low">low</option>
        <option value="info">info</option>
      </select>
      <input class="select" id="fndTarget" placeholder="target (exact)…" />
      <input class="select" id="fndTool" placeholder="tool id…" />
      <button class="btn primary" id="fndGo">Apply</button>
    </div>
    <div id="findingTable">Loading…</div>`;
  $("#fndGo").addEventListener("click", refreshFindings);
  $("#fndSeverity").addEventListener("change", refreshFindings);
  await refreshFindings();
}

/* ── route: scope ──────────────────────────────────────────────────── */

async function pageScope() {
  setPageMeta({ crumb: "Scopes & Policies", title: "Scopes & Policies", subtitle: "Scope enforcement (read-only)" });
  const s = await api("/scope");
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">SCOPES &amp; POLICIES</div><h1>Scope enforcement</h1>
    <div class="subtitle">Scope is controlled via MCP_SCOPE_* environment variables on the server process — this panel is read-only by design.</div>`;
  $("#pageBody").innerHTML = `
    ${kpis([
      { label: "Scope", value: s.is_empty ? "unrestricted (allow-all)" : "restricted" },
      { label: "Expired", value: s.is_expired ? "yes — all denied" : "no" },
      { label: "Policy", value: s.policy || "safe_active" },
      { label: "Expiration", value: s.expiration || "never" },
    ])}
    <div class="two-col" style="margin-top:14px">
      <div class="panel"><div class="panel-head"><span>Allowed targets</span></div>
        <div style="padding:12px">${(s.allowed_targets?.length ? s.allowed_targets : ["* (all targets)"]).map((t) => `<span class="chip" style="margin:2px">${esc(t)}</span>`).join("")}</div></div>
      <div class="panel"><div class="panel-head"><span>Excluded targets</span></div>
        <div style="padding:12px">${(s.excluded_targets?.length ? s.excluded_targets : ["none"]).map((t) => `<span class="chip" style="margin:2px">${esc(t)}</span>`).join("")}</div></div>
      <div class="panel"><div class="panel-head"><span>Allowed operations</span></div>
        <div style="padding:12px">${(s.allowed_operations?.length ? s.allowed_operations : ["* (all operations)"]).map((t) => `<span class="chip" style="margin:2px">${esc(t)}</span>`).join("")}</div></div>
    </div>`;
}

/* ── route: settings ───────────────────────────────────────────────── */

async function pageSettings() {
  setPageMeta({ crumb: "Settings", title: "Settings", subtitle: "Server runtime configuration (read-only)" });
  const s = await api("/server");
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">SETTINGS</div><h1>Server</h1>
    <div class="subtitle">Runtime configuration comes from config.py (MCP_* environment variables) — shown read-only.</div>`;
  $("#pageBody").innerHTML = `
    ${kpis([
      { label: "Server", value: `${s.server_name} v${s.server_version}` },
      { label: "Bind", value: `${s.host}:${s.port}` },
      { label: "Transport", value: s.transport || "—" },
      { label: "Auth", value: s.auth_enabled ? "token required" : "disabled (insecure)" },
    ])}
    <div class="two-col" style="margin-top:14px">
      <div class="panel"><div class="panel-head"><span>Limits</span></div>
        <div style="padding:12px;line-height:2;font-size:12px">
          Default timeout: <strong>${esc(s.default_timeout)}s</strong><br/>
          Max timeout: <strong>${esc(s.max_timeout)}s</strong><br/>
          Max concurrent operations: <strong>${esc(s.max_concurrent)}</strong><br/>
          Debug mode: <strong>${s.debug ? "on" : "off"}</strong></div></div>
      <div class="panel"><div class="panel-head"><span>Token</span></div>
        <div style="padding:12px;font-size:12px;line-height:1.8">
          ${s.auth_enabled
            ? "This server requires a bearer token for every /api call. It is stored in this browser only."
            : "No token required (KALI_MCP_INSECURE or unset MCP_API_TOKEN)."}
          <div style="margin-top:10px"><button class="btn" id="resetTokenBtn">Clear stored token</button></div>
        </div></div>
    </div>`;
  $("#resetTokenBtn").addEventListener("click", () => {
    localStorage.removeItem(TOKEN_KEY);
    toast("Stored token cleared");
    refreshAuthBadge();
  });
}

/* ── auth badge ────────────────────────────────────────────────────── */

async function refreshAuthBadge() {
  const badge = $("#authState");
  const srv = $("#serverMeta");
  try {
    const s = await api("/server");
    if (badge) badge.textContent = s.auth_enabled ? "Token protected" : "Insecure mode";
    if (srv) srv.textContent = `${s.server_name} v${s.server_version}`;
  } catch {
    if (badge) badge.textContent = "Token required";
    if (srv) srv.textContent = "unauthenticated";
  }
}

/* ── router ────────────────────────────────────────────────────────── */

const ROUTES = {
  overview: { title: "Overview", render: pageOverview, crumb: "Overview" },
  playbooks: { title: "Playbook Studio", render: pagePlaybooks, crumb: "Playbook Studio" },
  executions: { title: "Executions", render: pageExecutions, crumb: "Executions" },
  tools: { title: "Tool Registry", render: pageTools, crumb: "Tool Registry" },
  connections: { title: "MCP Connections", render: pageConnections, crumb: "MCP Connections" },
  agents: { title: "Agents", render: pageAgents, crumb: "Agents" },
  findings: { title: "Findings", render: pageFindings, crumb: "Findings" },
  scope: { title: "Scopes & Policies", render: pageScope, crumb: "Scopes & Policies" },
  settings: { title: "Settings", render: pageSettings, crumb: "Settings" },
};

function parseHash() {
  const hash = (location.hash || "").replace(/^#\/?/, "");
  const [route, id] = hash.split("/");
  return { route: ROUTES[route] ? route : "overview", id };
}

async function route() {
  if (execTimer) { clearInterval(execTimer); execTimer = null; }
  const { route: name, id } = parseHash();
  $$("#mainNav .nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.route === name));
  setPageMeta({ crumb: ROUTES[name].crumb, title: ROUTES[name].title });
  await render();
  try {
    if (name === "executions" && id) await pageExecutionDetail(decodeURIComponent(id));
    else if (name === "connections" && id) await pageConnectionDetail(decodeURIComponent(id));
    else if (name === "agents" && id) await pageAgentDetail(decodeURIComponent(id));
    else await ROUTES[name].render();
  } catch (err) {
    $("#pageBody").insertAdjacentHTML("beforeend", `<p class="error" style="padding:20px">${esc(err.message)}</p>`);
  }
}

function bootShell() {
  $$("#mainNav .nav-item").forEach((btn) =>
    btn.addEventListener("click", () => { location.hash = `#/${btn.dataset.route}`; }));
  const wsBtn = $("#workspaceBtn");
  if (wsBtn) wsBtn.addEventListener("click", () => toast("Single workspace — the running server is this workspace."));
  $("#tokenSave").addEventListener("click", saveTokenAndRetry);
  $("#tokenInput").addEventListener("keydown", (e) => { if (e.key === "Enter") saveTokenAndRetry(); });
  window.addEventListener("hashchange", route);
}

bootShell();
await refreshAuthBadge();
await route();
