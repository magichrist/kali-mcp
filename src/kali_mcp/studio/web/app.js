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

/* ── route: playbook studio (library + editor) ─────────────────────── */

let selectedId = null;
let playbooksCache = [];

async function refreshPlaybooks() {
  const d = await api("/playbooks?limit=200");
  playbooksCache = d.playbooks || [];
  if ($("#pbGrid")) renderPlaybookGrid();
}

function pbFiltered() {
  const q = ($("#pbSearch")?.value || "").toLowerCase().trim();
  const st = $("#pbStatusFilter")?.value || "";
  const cat = $("#pbCategoryFilter")?.value || "";
  let rows = playbooksCache.filter((p) =>
    (!q || `${p.name} ${p.playbook_id} ${p.description || ""}`.toLowerCase().includes(q)) &&
    (!st || (p.status || "") === st) &&
    (!cat || (p.category || "custom") === cat));
  const sort = $("#pbSort")?.value || "newest";
  if (sort === "name") rows = rows.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  else if (sort === "oldest") rows = rows.sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
  else rows = rows.sort((a, b) => (b.id ?? 0) - (a.id ?? 0));
  return rows;
}

function renderPlaybookGrid() {
  const el = $("#pbGrid");
  if (!el) return;
  const rows = pbFiltered();
  if (!playbooksCache.length) {
    el.innerHTML = `
      <div class="lib-empty">
        <div class="lib-empty-glyph">⌘</div>
        <h2>Create your first playbook</h2>
        <p>Build a security workflow out of registered tools, shell commands and internal stages — visually on the graph, in the DSL, or both.</p>
        <div class="lib-empty-actions">
          <button class="btn primary" id="pbNewBtn2">＋ Create playbook</button>
          <button class="btn" id="pbImportBtn2">↙ Import playbook</button>
        </div>
      </div>`;
    $("#pbNewBtn2")?.addEventListener("click", newPlaybook);
    $("#pbImportBtn2")?.addEventListener("click", importPlaybook);
    return;
  }
  if (!rows.length) {
    el.innerHTML = `<p class="empty">No playbooks match this filter.</p>`;
    return;
  }
  el.innerHTML = rows.map((p) => `
    <a class="pb-card ${p.playbook_id === selectedId ? "active" : ""}" href="#/playbooks/${esc(p.playbook_id)}">
      <div class="pb-card-top">
        <span class="pb-card-name">${esc(p.name)}</span>${BADGE(p.status)}
      </div>
      <p class="pb-card-desc">${esc(p.description || "No description yet.")}</p>
      <div class="pb-card-meta">
        <span class="chip">${esc(p.category || "custom")}</span>
        <span class="chip mono">${esc(p.playbook_id)}</span>
        <span class="dim">v ${esc(p.current_version_id || "—")}</span>
        <span class="dim">${esc((p.created_at || "").slice(0, 10))}</span>
      </div>
    </a>`).join("");
}

async function pagePlaybooks() {
  selectedId = null;
  setPageMeta({ crumb: "Playbook Studio" });
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">PLAYBOOK STUDIO</div><h1>Playbooks</h1>
    <div class="subtitle">Create, manage and organize security workflows. Open one to edit it on the graph or in the DSL.</div>`;
  $("#pageHeadActions").innerHTML = headActionsHtml([
    { id: "pbImportBtn", label: "↙ Import" },
    { id: "pbNewBtn", label: "＋ New playbook", cls: "primary" },
  ]);
  $("#pageBody").innerHTML = `
    <div class="filterbar lib-filter">
      <input class="select" id="pbSearch" placeholder="Search playbooks…" style="flex:1;min-width:220px">
      <select class="select" id="pbStatusFilter">
        <option value="">All statuses</option><option value="draft">draft</option><option value="published">published</option>
      </select>
      <select class="select" id="pbCategoryFilter"><option value="">All categories</option></select>
      <select class="select" id="pbSort">
        <option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="name">Name A–Z</option>
      </select>
    </div>
    <div class="lib-grid" id="pbGrid"><p class="empty">Loading…</p></div>`;
  $("#pbNewBtn").addEventListener("click", newPlaybook);
  $("#pbImportBtn").addEventListener("click", importPlaybook);
  ["input", "change"].forEach((ev) => {
    $("#pbSearch").addEventListener(ev, renderPlaybookGrid);
    $("#pbStatusFilter").addEventListener(ev, renderPlaybookGrid);
    $("#pbCategoryFilter").addEventListener(ev, renderPlaybookGrid);
    $("#pbSort").addEventListener(ev, renderPlaybookGrid);
  });
  await refreshPlaybooks();
  const cats = [...new Set(playbooksCache.map((p) => p.category || "custom"))].sort();
  $("#pbCategoryFilter").innerHTML =
    `<option value="">All categories</option>` + cats.map((c) => `<option>${esc(c)}</option>`).join("");
}

async function pagePlaybookEditor(id) {
  selectedId = id;
  builderView = "graph";
  graphDef = null; graphSel = null; graphPos = {};
  graphZoom = 1; graphPan = { x: 0, y: 0 };
  historyStack = []; futureStack = [];
  inspectTab = "general";
  runStatus = {};
  if (runStatusTimer) { clearInterval(runStatusTimer); runStatusTimer = null; }

  const crumbEl = $("#crumbPage");
  if (crumbEl) crumbEl.textContent = id;
  $("#pageHeadInfo").innerHTML = "";
  $("#pageHeadActions").innerHTML = "";
  const ph = $(".pagehead");
  if (ph) ph.classList.add("hide");
  $("#pageBody").className = "pagebody editor-body";

  $("#pageBody").innerHTML = `
  <section class="editor-shell" id="editorShell">
    <header class="pb-head">
      <div class="pb-head-l">
        <a class="btn ghost back-btn" href="#/playbooks" title="Back to playbooks">↩ Playbooks</a>
        <div class="pb-title">
          <h2 id="pbName">…</h2>
          <div class="pb-meta" id="pbMeta"></div>
        </div>
      </div>
      <div class="pb-head-r">
        <button class="btn" id="pbValidate">Validate</button>
        <button class="btn" id="pbSave" title="Save draft">Save draft</button>
        <button class="btn accent" id="pbRun" title="Run published version with test inputs">▶ Run test</button>
        <button class="btn primary" id="pbPublish">Publish</button>
        <div class="menu" id="pbMenuWrap">
          <button class="btn ghost" id="pbMore" title="More actions">⋯</button>
          <div class="menu-list" id="pbMenuList" hidden>
            <button data-mact="versions">Versions &amp; rollback</button>
            <button data-mact="export">Export JSON</button>
            <button data-mact="import">Import over…</button>
            <button data-mact="delete" class="danger">Delete playbook</button>
          </div>
        </div>
      </div>
    </header>
    <div class="pb-bar">
      <div class="segmented" id="builderSwitch">
        <button data-view="graph" class="active">Graph</button>
        <button data-view="dsl">DSL</button>
      </div>
      <span class="pb-hint dim" id="pbHint"></span>
    </div>
    <div class="editor-grid" id="editorGrid">
      <div class="canvas-col">
        <div class="graph-toolbar" id="graphToolbar">
          <span class="tool-sep"></span>
          <button class="btn icon" id="undoBtn" title="Undo">↶</button>
          <button class="btn icon" id="redoBtn" title="Redo">↷</button>
          <span class="tool-sep"></span>
          <button class="btn" id="addToolBtn" title="Add a registered-tool step">＋ Tool</button>
          <button class="btn" id="addShellBtn" title="Add a shell-command node (inputs → command → filter)">＋ Shell</button>
          <span class="tool-sep"></span>
          <button class="btn icon" id="resetLayoutBtn" title="Auto-layout">⇋</button>
          <button class="btn icon" id="zoomOut" title="Zoom out">−</button>
          <button class="btn icon" id="zoomReset" title="Fit to screen">⛶</button>
          <button class="btn icon" id="zoomIn" title="Zoom in">＋</button>
          <button class="btn icon" id="delSelBtn" title="Delete selected node">✕</button>
          <span class="tool-sep"></span>
          <span class="count" id="graphCount">0 steps</span>
        </div>
        <div class="canvas-area" id="canvasArea">
          <div class="canvas-inner" id="canvasInner">
            <svg class="edges" id="edgeLayer" width="6000" height="4000" xmlns="http://www.w3.org/2000/svg"></svg>
          </div>
          <div class="canvas-legend">
            <span><i class="legend-dot" style="background:#edc57c"></i>tool</span>
            <span><i class="legend-dot" style="background:#f09685"></i>shell</span>
            <span><i class="legend-dot" style="background:#92dbad"></i>scope / report</span>
            <span><i class="legend-dot" style="background:#aabaff"></i>correlation</span>
          </div>
          <div class="canvas-empty" id="canvasEmpty" hidden>
            <div class="ce-glyph">⌘</div>
            <h3>Your workflow starts here</h3>
            <p>Add a step to begin — use ＋ Tool (registered security tool) or ＋ Shell (command node) in the graph toolbar.</p>
            <button class="btn primary" id="firstStepBtn">Add first step</button>
          </div>
        </div>
      </div>
      <div class="ins-resizer" id="insResizer" title="Drag to resize the inspector"></div>
      <div class="ins-col" id="insCol">
        <aside class="inspector" id="inspector"></aside>
      </div>
    </div>
    <div class="dsl-panel" id="dslPanel" hidden>
      <textarea class="code-area" id="dslCode" spellcheck="false" placeholder="Playbook definition (JSON as returned by /definition)…"></textarea>
      <div class="dsl-bar"><span class="dim">Canonical model — the graph above edits this same JSON. Graph ⇄ DSL is always in sync.</span></div>
    </div>
    <div class="result-wrap"><pre class="result" id="editorResult" hidden></pre></div>
  </section>`;

  /* ── load playbook meta + definition ── */
  try {
    const [d, defn] = await Promise.all([
      api(`/playbooks/${encodeURIComponent(id)}`),
      api(`/playbooks/${encodeURIComponent(id)}/definition`).catch(() => ({ definition: null })),
    ]);
    const def = defn.definition;
    $("#pbName").textContent = d.name || id;
    if (crumbEl) crumbEl.textContent = d.name || id;
    $("#pbMeta").innerHTML = `${BADGE(d.status)} <span class="version">v ${esc(d.current_version_id || "no version")}</span><span class="dim mono">${esc(id)}</span>`;
    $("#dslCode").value = def ? JSON.stringify(def, null, 2) : "";
  } catch (err) {
    $("#pbName").textContent = id;
    $("#pbMeta").innerHTML = `<span class="error">${esc(err.message)}</span>`;
  }

  $("#editorShell").style.setProperty("--ins-w", "380px");

  $("#firstStepBtn").addEventListener("click", () => addToolStep());
  $("#undoBtn").addEventListener("click", undoGraph);
  $("#redoBtn").addEventListener("click", redoGraph);
  $("#addToolBtn").addEventListener("click", () => addToolStep());
  $("#addShellBtn").addEventListener("click", () => addShellStep());
  $("#resetLayoutBtn").addEventListener("click", resetGraphLayout);
  $("#zoomIn").addEventListener("click", () => nudgeZoom(+0.2));
  $("#zoomOut").addEventListener("click", () => nudgeZoom(-0.2));
  $("#zoomReset").addEventListener("click", fitToScreen);
  $("#delSelBtn").addEventListener("click", () => { if (graphSel) deleteGraphStep(graphSel); else toast("Select a node on the canvas first"); });

  $$("#builderSwitch button").forEach((btn) =>
    btn.addEventListener("click", () => switchBuilderView(btn.dataset.view)));

  $("#pbValidate").addEventListener("click", validateDefinition);
  $("#pbSave").addEventListener("click", saveDraft);
  $("#pbPublish").addEventListener("click", publish);
  $("#pbRun").addEventListener("click", () => runModal(selectedId));
  $("#pbMore").addEventListener("click", () => {
    const l = $("#pbMenuList");
    if (l) l.hidden = !l.hidden;
  });
  $$("#pbMenuList button").forEach((btn) =>
    btn.addEventListener("click", () => {
      $("#pbMenuList").hidden = true;
      const act = btn.dataset.mact;
      if (act === "versions") showVersions();
      else if (act === "export") exportPlaybook();
      else if (act === "import") importPlaybook();
      else if (act === "delete") deletePlaybook();
    }));
  document.addEventListener("click", pbCloseMenuOnOutside);

  initInspectorResizer();
  initCanvasGestures();
  refreshTools().catch(() => {});
  loadRunStatus(selectedId).catch(() => {});
  switchBuilderView("graph");
  // keep large graphs fully visible on entry — the user should never land
  // on a canvas where the last step is off-screen.
  if (getGraphSteps().length >= 3) {
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => fitToScreen());
    else fitToScreen();
  }
}

function pbCloseMenuOnOutside(e) {
  const wrap = $("#pbMenuWrap");
  if (!wrap) { document.removeEventListener("click", pbCloseMenuOnOutside); return; }
  if (!wrap.contains(e.target)) { const l = $("#pbMenuList"); if (l) l.hidden = true; }
}

/* ── canvas gestures: trackpad pinch-zoom, scroll pan, drag pan ───── */
/* macOS trackpad: two-finger pinch → wheel + ctrlKey (Chrome/Edge) or
   gesturechange (Safari). Two-finger scroll pans. Click-drag on empty
   canvas pans too, like the run-detail graphs you already know. */

function initCanvasGestures() {
  const area = $("#canvasArea");
  if (!area || area.dataset.gestures) return;
  area.dataset.gestures = "1";

  /* two-finger scroll / shift-wheel → pan (natural-scroll friendly) */
  area.addEventListener("wheel", (e) => {
    if (e.ctrlKey) {
      // trackpad pinch — zoom anchored at the pointer
      e.preventDefault();
      // cap per-event step so momentum pinch doesn't overshoot
      const factor = Math.min(1.6, Math.max(0.6, Math.exp(-e.deltaY * 0.01)));
      canvasZoomAt(e.clientX, e.clientY, factor);
      return;
    }
    // plain two-finger scroll: pan the workflow instead of scrolling the page
    e.preventDefault();
    const lines = e.deltaMode === 1 ? 16 : 1; // normalize firefox "lines" mode
    graphPan = { x: graphPan.x - e.deltaX * lines, y: graphPan.y - e.deltaY * lines };
    applyZoom();
  }, { passive: false });

  /* Safari pinch (aspect=0 for full zoom pinches) */
  let gestureScale = null;
  area.addEventListener("gesturestart", (e) => { gestureScale = e.scale || 1; e.preventDefault(); });
  area.addEventListener("gesturechange", (e) => {
    if (!gestureScale) return;
    e.preventDefault();
    const factor = Math.min(1.6, Math.max(0.6, (e.scale || 1) / gestureScale));
    canvasZoomAt(e.clientX, e.clientY, factor);
    gestureScale = e.scale || 1;
  });
  area.addEventListener("gestureend", () => { gestureScale = null; });

  /* click-drag on empty canvas → pan */
  area.addEventListener("mousedown", (e) => {
    if (e.button !== 0 && e.button !== 1) return;
    if (e.target instanceof Element &&
        e.target.closest(".node, .port, .canvas-empty button")) return;
    const sx = e.clientX, sy = e.clientY, ox = graphPan.x, oy = graphPan.y;
    let moved = false;
    document.body.classList.add("canvas-panning");
    const move = (ev) => {
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (!moved && Math.hypot(dx, dy) < 4) return;
      moved = true;
      graphPan = { x: ox + dx, y: oy + dy };
      applyZoom();
    };
    const up = () => {
      document.body.classList.remove("canvas-panning");
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
    e.preventDefault();
  });
}

function initInspectorResizer() {
  const handle = $("#insResizer");
  const shell = $("#editorShell");
  if (!handle || !shell) return;
  let startX = 0, startW = 0, dragging = false;
  const move = (ev) => {
    if (!dragging) return;
    const w = Math.min(640, Math.max(300, Math.round(startW + (startX - ev.clientX))));
    shell.style.setProperty("--ins-w", `${w}px`);
  };
  const up = () => {
    dragging = false;
    document.body.classList.remove("resizing");
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", up);
  };
  handle.addEventListener("mousedown", (e) => {
    dragging = true;
    document.body.classList.add("resizing");
    startX = e.clientX;
    startW = parseInt(getComputedStyle($("#insCol")).width, 10) || 380;
    e.preventDefault();
  });
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
}

/* ── canonical model: graphDef ⇄ DSL — a single source of truth ────── */

const NODE_W = 280, NODE_H = 140, X_GAP = 360, Y_GAP = 200;
let builderView = "graph";
let graphDef = null;          // canonical definition object while editing
let graphSel = null;          // selected step id
let graphPos = {};            // {stepId:{x,y}} drag overrides
let graphZoom = 1;
let graphPan = { x: 0, y: 0 };
let historyStack = [];
let futureStack = [];
let inspectTab = "general";
let runStatus = {};           // {stepId: status} from the latest execution
let runStatusTimer = null;

const TYPE_ICONS = {
  tool: { cls: "scan", glyph: "◎" },
  shell: { cls: "cmd", glyph: "❯" },
  scope_check: { cls: "dns", glyph: "✓" },
  finding_correlation: { cls: "web", glyph: "⇄" },
  assessment_report: { cls: "out", glyph: "▤" },
  custom: { cls: "mod", glyph: "▣" },
};
const iconFor = (s) => TYPE_ICONS[s?.type] || { cls: "scan", glyph: "◈" };

function getGraphSteps() { return Array.isArray(graphDef?.steps) ? graphDef.steps : []; }

function stepById(id) { return getGraphSteps().find((s) => s.id === id); }

function emptyDefinition(name) {
  return { name: name || "draft", version: "1.0.0", inputs: {}, steps: [], execution: { timeout: 900, max_parallel: 4 } };
}

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
    graphDef = emptyDefinition(selectedId);
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
  if (builderView === "graph") { applyTabFields(stepById(graphSel)); captureGraphToDSL(); }
  if (view === "graph") {
    if (!loadGraphFromDSL()) return;   // invalid JSON: stay in DSL with a toast
  }
  builderView = view;
  const dv = $("#dslPanel"), gr = $("#editorGrid");
  if (dv) dv.hidden = view !== "dsl";
  if (gr) gr.hidden = view !== "graph";
  $$("#builderSwitch button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (view === "graph") renderBuilder();
}

/* ── undo / redo (JSON snapshots of the canonical model) ───────────── */

function pushHistory() {
  if (builderView !== "graph" || !graphDef) return;
  historyStack.push(JSON.stringify(graphDef));
  if (historyStack.length > 40) historyStack.shift();
  futureStack = [];
}

function undoGraph() {
  if (!historyStack.length) return toast("Nothing to undo");
  if (builderView !== "graph") return;
  futureStack.push(JSON.stringify(graphDef));
  graphDef = JSON.parse(historyStack.pop());
  graphSel = null;
  captureGraphToDSL();
  renderBuilder();
}

function redoGraph() {
  if (!futureStack.length) return toast("Nothing to redo");
  if (builderView !== "graph") return;
  historyStack.push(JSON.stringify(graphDef));
  graphDef = JSON.parse(futureStack.pop());
  graphSel = null;
  captureGraphToDSL();
  renderBuilder();
}

/* ── layout: layering + positions ─────────────────────────────────── */

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
  return { x: 40 + depth * X_GAP, y: 40 + yIdx * Y_GAP };
}

function applyZoom() {
  const inner = $("#canvasInner");
  if (inner) inner.style.transform = `translate(${graphPan.x}px,${graphPan.y}px) scale(${graphZoom})`;
}

/* zoom keeping the canvas point under clientX/clientY anchored in place */
function canvasZoomAt(clientX, clientY, factor) {
  const area = $("#canvasArea");
  if (!area) return;
  const rect = area.getBoundingClientRect();
  const ox = clientX - rect.left, oy = clientY - rect.top;
  const nz = Math.round(Math.min(2.5, Math.max(0.2, graphZoom * factor)) * 1000) / 1000;
  if (nz === graphZoom) return;
  const k = nz / graphZoom;
  graphZoom = nz;
  graphPan = { x: ox - (ox - graphPan.x) * k, y: oy - (oy - graphPan.y) * k };
  applyZoom();
}

function nudgeZoom(delta) {
  const area = $("#canvasArea");
  if (!area) return;
  const rect = area.getBoundingClientRect();
  canvasZoomAt(rect.left + area.clientWidth / 2, rect.top + area.clientHeight / 2, 1 + delta);
}

function fitToScreen() {
  const steps = getGraphSteps();
  if (!steps.length || builderView !== "graph") { graphZoom = 1; graphPan = { x: 0, y: 0 }; applyZoom(); return; }
  const area = $("#canvasArea");
  if (!area) return;
  const depths = {};
  graphLayout(depths);
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const s of steps) {
    const p = nodePos(s.id, depths);
    minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + NODE_W); maxY = Math.max(maxY, p.y + NODE_H);
  }
  const pad = 48;
  const w = Math.max(1, area.clientWidth - 2 * pad), h = Math.max(1, area.clientHeight - 2 * pad);
  const z = Math.max(0.25, Math.min(1.25, w / (maxX - minX), h / (maxY - minY)));
  graphZoom = Math.round(z * 100) / 100;
  graphPan = {
    x: Math.round((w - (maxX - minX) * graphZoom) / 2 - minX * graphZoom + pad),
    y: Math.round((h - (maxY - minY) * graphZoom) / 2 - minY * graphZoom + pad),
  };
  applyZoom();
}

function resetGraphLayout() { pushHistory(); graphPos = {}; graphZoom = 1; graphPan = { x: 0, y: 0 }; renderBuilder(); toast("Layout reset"); }

/* ── node rendering ────────────────────────────────────────────────── */

function runStatusClass(id) {
  const st = runStatus[id];
  if (!st) return "";
  if (st === "completed" || st === "ok") return "ok";
  if (st === "failed" || st === "cancelled") return "failed";
  if (st === "running" || st === "pending") return "run";
  return "";
}

function renderBuilder() {
  const inner = $("#canvasInner");
  if (!inner) return;
  if (!graphDef) loadGraphFromDSL();
  const steps = getGraphSteps();
  const depths = {};
  graphLayout(depths);

  $$(".node", inner).forEach((n) => n.remove());
  applyZoom();
  const empty = $("#canvasEmpty");
  if (empty) empty.hidden = steps.length > 0;
  const legend = $(".canvas-legend");
  if (legend) legend.style.display = steps.length ? "" : "none";

  for (const s of steps) {
    const p = nodePos(s.id, depths);
    const ic = iconFor(s);
    let bodyHtml = "";
    if (s.type === "shell") {
      const inRows = Object.entries(s.inputs || {})
        .filter(([k]) => k)
        .map(([k, v]) => `<div class="shell-line in"><i>in</i><b>${esc(k)}</b><span>${esc(String(v))}</span></div>`)
        .join("") || `<div class="shell-line in"><i>in</i><span class="dim">no inputs</span></div>`;
      const cmd = s.command ? esc(s.command) : '<span class="dim">no command</span>';
      const f = s.filter && s.filter.type !== "none" ? s.filter : null;
      const fLine = f
        ? `<div class="shell-line flt"><i>⌕</i><b>${esc(f.type || "grep")}</b><span>${esc(String(f.pattern || "").slice(0, 46))}</span></div>`
        : `<div class="shell-line flt"><i>⌕</i><span class="dim">no filter</span></div>`;
      bodyHtml = `${inRows}<div class="shell-line cmd"><i>❯</i><span class="cmd-txt">${cmd}</span></div>${fLine}`;
    } else {
      const isTool = s.type === "tool";
      const argSummary = isTool
        ? `tool: ${s.tool || "?"} · ${Object.keys(s.args || {}).length} arg(s)`
        : Object.keys(s.args || {}).length ? `${Object.keys(s.args || {}).length} arg(s)` : "internal stage";
      bodyHtml = esc(argSummary) + (s.when ? `<br/>when: ${esc(s.when)}` : "");
    }
    const stCls = runStatusClass(s.id);
    const stTxt = runStatus[s.id] ? `run status: ${runStatus[s.id]}` : "";
    const el = document.createElement("div");
    el.className = `node ${s.type === "shell" ? "shell " : ""}${graphSel === s.id ? "selected" : ""}`;
    el.style.left = `${p.x}px`; el.style.top = `${p.y}px`;
    el.dataset.step = s.id;
    el.innerHTML = `
      <div class="node-top">
        <div class="node-icon ${ic.cls}">${ic.glyph}</div>
        <div class="node-names"><div class="node-title">${esc(s.id)}</div>
          <div class="node-kind">${esc(s.type || "step")}${s.tool ? ` · ${esc(s.tool)}` : ""}</div></div>
        <span class="node-status ${stCls}" title="${esc(stTxt)}"></span>
      </div>
      <div class="node-body">${bodyHtml}</div>
      <div class="node-foot">
        <span class="chip">${(s.depends_on || []).length} in</span>
        ${Object.keys(s.inputs || {}).length ? `<span class="chip">${Object.keys(s.inputs || {}).length} inputs</span>` : ""}
        ${s.filter && s.filter.type !== "none" ? `<span class="chip accent">⌕ out</span>` : ""}
        ${s.checkpoint ? '<span class="chip ck">checkpoint</span>' : ""}
      </div>
      <span class="port left" title="input port"></span><span class="port right" title="drag or click to connect"></span>`;
    el.addEventListener("mousedown", (e) => startNodeDrag(e, s.id, p));
    const rightPort = el.querySelector(".port.right");
    if (rightPort) rightPort.addEventListener("mousedown", (e) => startPortConnect(e, s.id));
    inner.appendChild(el);
  }

  // edges
  const svg = $("#edgeLayer");
  let edges = "";
  for (const s of steps) {
    for (const dep of s.depends_on || []) {
      if (!depths.hasOwnProperty(dep) || dep === s.id) continue;
      const a = nodePos(dep, depths), b = nodePos(s.id, depths);
      const y1 = a.y + NODE_H / 2, y2 = b.y + NODE_H / 2;
      const hot = graphSel === dep || graphSel === s.id ? " hot" : "";
      edges += `<path class="edge${hot}" d="M${a.x + NODE_W},${y1} C${(a.x + NODE_W + b.x) / 2},${y1} ${(a.x + NODE_W + b.x) / 2},${y2} ${b.x},${y2}"/>`;
    }
  }
  svg.innerHTML = edges;

  // toolbar state
  const cnt = $("#graphCount");
  if (cnt) cnt.textContent = `${steps.length} step${steps.length === 1 ? "" : "s"}`;
  const ub = $("#undoBtn"), rb = $("#redoBtn"), db = $("#delSelBtn");
  if (ub) ub.disabled = !historyStack.length;
  if (rb) rb.disabled = !futureStack.length;
  if (db) db.disabled = !graphSel;

  renderInspector();
}

/* ── inspector (tabbed, type-aware) ────────────────────────────────── */

const INS_TABS = ["general", "inputs", "outputs", "advanced"];
const INS_TAB_LABELS = { general: "General", inputs: "Inputs", outputs: "Outputs", advanced: "Advanced" };

function parseRef(v) {
  const t = String(v ?? "").trim();
  const m = t.match(/^\{\{(\w+)\}\}$/);
  if (m) return { mode: "run", name: m[1] };
  const u = t.match(/^\{\{(\w+)\.(\w+)\}\}$/);
  if (u) return { mode: "upstream", step: u[1], field: u[2] };
  return { mode: "literal", val: t };
}

function defInputs(def) {
  const raw = def?.inputs;
  if (Array.isArray(raw)) return raw.filter((x) => typeof x === "object" && x?.name).map((x) => ({ name: x.name, spec: x }));
  if (raw && typeof raw === "object") return Object.entries(raw).map(([name, spec]) => ({ name, spec: typeof spec === "object" && spec ? spec : {} }));
  return [];
}

/* collect run-input names referenced as {{name}} across step inputs, args and
   shell commands — these are the inputs a playbook actually takes at launch */
function collectRunInputs(def) {
  const names = new Set();
  const stepInputDefaults = {};
  const add = (v) => {
    if (typeof v !== "string") return;
    for (const m of v.matchAll(/\{\{\s*([a-zA-Z_][\w]*)\s*\}\}/g)) names.add(m[1]);
  };
  for (const s of def?.steps || []) {
    if (s.inputs) {
      for (const [k, v] of Object.entries(s.inputs)) {
        stepInputDefaults[k] = v; // literal default for this input key
        add(v);
      }
    }
    if (s.command) add(s.command);
    if (s.args) for (const v of Object.values(s.args)) add(v);
  }
  const result = [...names].map((name) => ({ name, spec: { type: "string", required: true } }));
  // step input keys that aren't run-input references become optional literal inputs
  for (const [k, v] of Object.entries(stepInputDefaults)) {
    if (!names.has(k) && typeof v === "string" && !v.match(/^\{\{[a-zA-Z_]\w*\}\}$/)) {
      result.push({ name: k, spec: { type: "string", required: false, default: v } });
    }
  }
  return result;
}

function namedGroups(pattern) {
  const out = [];
  const re = /\(\?P<([A-Za-z_]\w*)>/g;
  let m;
  while ((m = re.exec(String(pattern || "")))) out.push(m[1]);
  return out;
}

function upstreamOutFields(stepId) {
  const s = stepById(stepId);
  if (!s) return [];
  return namedGroups(s.filter?.pattern);
}

/* ── inspector help (hover tooltip "icons") ─────────────────────────── */

function helpTip(text) {
  const t = String(text || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "").trim();
  if (!t) return "";
  return `<span class="help-tip-wrap"><button type="button" class="help-tip" data-tip="${esc(t)}" aria-label="Help: ${esc(t)}" tabindex="0">?</button></span>`;
}

function insLabel(text, control, tip) {
  return `<label class="ins-field">
    <span class="ins-flabel"><span class="ins-flabel-txt">${esc(text)}</span>${helpTip(tip)}</span>${control}</label>`;
}

/* same affordance for section headings */
function subLabel(text, tip, extra = "") {
  return `<div class="ins-subhead">${esc(text)}${extra}${helpTip(tip)}</div>`;
}

function insDependsField(s) {
  return insLabel("Depends on", `<input class="select" id="insDeps" value="${esc((s.depends_on || []).join(", "))}" placeholder="comma separated upstream step ids">`,
    "Steps that must finish before this one runs. Enter their <b>Step ids</b>, comma separated — e.g. <code>recon_1, parse_2</code>. Upstream steps are always implicit prerequisites, this wires extra ones.");
}

function insGeneralTab(s) {
  const typeFixed = `
    <div class="ins-field">
      <span class="ins-flabel">Step type</span>
      <div class="type-static"><span class="node-icon cmd">❯</span> shell command <span class="dim">(inputs → command → output filter)</span></div>
    </div>`;
  const typeSel = insLabel("Step type", `
    <select class="select" id="insType">
      ${["tool", "shell", "scope_check", "finding_correlation", "assessment_report", "custom"]
        .map((v) => `<option value="${v}" ${v === (s.type || "tool") ? "selected" : ""}>${v}</option>`).join("")}
    </select>`,
    "<b>tool</b> runs a registry tool · <b>shell</b> runs your own command · <b>custom</b> = internal module stage · the rest are built-in reporting/scope stages. Changing type resets tool-specific settings.");
  const toolSel = s.type === "tool" ? insLabel("Tool", `
    <input class="select" id="insTool" value="${esc(s.tool || "")}" placeholder="e.g. nuclei" list="dlTools">` +
    `<datalist id="dlTools">${(toolsCache || []).map((t) => `<option value="${esc(t.name)}"></option>`).join("")}</datalist>`,
    "Pick a registered tool — its argument form on the Inputs tab follows this choice. Names come from the Tool Registry (see the Tools page).") : "";
  const cmdField = s.type === "shell" ? insLabel("Shell command", `
    <textarea class="select area mono" id="insCommand" style="min-height:64px" spellcheck="false" placeholder="nmap {ip} -sn — {name} placeholders fill from the Inputs tab">${esc(s.command || "")}</textarea>`,
    "Any shell command. Put <code>{name}</code> placeholders where mapped inputs land — e.g. <code>nmap -sn {ip}</code> with an input named <b>ip</b> mapped to the run input or an upstream field.") : "";
  return `
    ${insLabel("Step id", `<input class="select mono" id="insId" value="${esc(s.id)}">`,
      "Unique name used on the canvas and to reference this step's outputs as <code>{{thisid.field}}</code> downstream. Renaming updates all references automatically.")}
    ${s.type === "shell" ? typeFixed : typeSel}
    ${toolSel}
    ${cmdField}
    ${insDependsField(s)}
    <div class="checkline">${insLabel("Checkpoint", `<input type="checkbox" id="insCheckpoint" ${s.checkpoint ? "checked" : ""}>`, "Persists the run state after this step so a failed run can be resumed from here instead of starting over.")}</div>`;
}

/* ── schema-driven tool arguments ─────────────────────────────────── */

function toolInputSchema(toolName) {
  if (!toolName) return null;
  const t = (toolsCache || []).find(
    (x) => String(x.name || "").toLowerCase() === String(toolName).toLowerCase());
  const sc = t?.input_schema;
  if (!sc || sc.type !== "object" || !sc.properties || !Object.keys(sc.properties).length) return null;
  return sc;
}

function argControlHtml(name, prop, val) {
  const type = String(prop?.type || "string");
  const common = `data-arg="${esc(name)}" data-argtype="${type}"`;
  if (type === "boolean") {
    const v = val === undefined ? (prop?.default ?? null) : val;
    return `<select class="select" ${common}>
      <option value="" ${v === null || v === undefined ? "selected" : ""}>— not set</option>
      <option value="true" ${v === true ? "selected" : ""}>true</option>
      <option value="false" ${v === false ? "selected" : ""}>false</option>
    </select>`;
  }
  if (type === "integer" || type === "number") {
    const v = val !== undefined ? val : prop?.default;
    return `<input class="select" type="number" ${common}
      value="${v === undefined || v === null ? "" : esc(String(v))}" placeholder="${type === "number" ? "e.g. 1.5" : "e.g. 30"}">`;
  }
  if (type === "array" || type === "object") {
    const v = val !== undefined ? val : prop?.default;
    return `<textarea class="select area mono" ${common} style="min-height:46px" spellcheck="false"
      placeholder="${type === "array" ? '[ "item1", "item2" ]' : '{ "key": "value" }'}">${esc(v === undefined || v === null ? "" : JSON.stringify(v, null, 1))}</textarea>`;
  }
  const v = val !== undefined ? val : prop?.default;
  return `<input class="select" ${common} value="${v === undefined || v === null ? "" : esc(String(v))}">`;
}

function argRowHtml(name, prop, val, required) {
  const req = Array.isArray(required) && required.includes(name);
  return `<div class="arg-row${req ? " arg-required" : ""}">
    <div class="arg-head">
      <code class="arg-key">${esc(name)}</code>
      <span class="chip">${esc(String(prop?.type || "string"))}</span>
      ${req ? `<span class="chip accent">required</span>` : ""}
      ${helpTip(prop?.description || `Argument “${name}” of type ${prop?.type || "string"}.`)}
    </div>
    ${argControlHtml(name, prop, val)}
  </div>`;
}

function argExtraRowHtml(name, val) {
  return `<div class="arg-row arg-extra">
    <div class="arg-head">
      <input class="select inp mono arg-extra-name" data-argname value="${esc(name)}" placeholder="extra argument name">
      ${helpTip("Not in this tool's schema — usually a runtime/execution option. Extra keys are still passed to the runner.")}
    </div>
    <textarea class="select area mono arg-extra-val" style="min-height:40px" spellcheck="false" placeholder="JSON value">${esc(JSON.stringify(val, null, 1))}</textarea>
  </div>`;
}

/* best-effort read of builder fields → args object; also used to seed raw JSON */
function collectBuilderArgs() {
  const args = {};
  let missing = [];
  $$("#argBuilder [data-arg]").forEach((el) => {
    const name = el.dataset.arg;
    const type = el.dataset.argtype || "string";
    const raw = el.value;
    if (type === "boolean") {
      if (raw === "") return;
      args[name] = raw === "true";
      return;
    }
    if (type === "integer") {
      if (String(raw).trim() === "") return;
      args[name] = parseInt(raw, 10);
      return;
    }
    if (type === "number") {
      if (String(raw).trim() === "") return;
      args[name] = parseFloat(raw);
      return;
    }
    if (type === "array" || type === "object") {
      const txt = String(raw).trim();
      if (!txt) return;
      try { args[name] = JSON.parse(txt); }
      catch { missing.push(`${name} must be valid ${type} JSON (e.g. ${type === "array" ? '["a","b"]' : '{"k":"v"}'})`); }
      return;
    }
    const txt = String(raw).trim();
    if (txt) args[name] = txt;
  });
  // extras (unknown keys)
  $$("#argBuilder .arg-extra").forEach((row) => {
    const name = (row.querySelector(".arg-extra-name")?.value || "").trim();
    const txt = (row.querySelector(".arg-extra-val")?.value || "").trim();
    if (!name && !txt) return;
    if (!name || !txt) { missing.push(`extra argument: fill both name and JSON value (or clear them)`); return; }
    try { args[name] = JSON.parse(txt); }
    catch { missing.push(`extra argument "${name}" must be a JSON value (true, 90, "text", …)`); }
  });
  return { args, missing };
}

function insInputsTab(s) {
  if (s.type === "shell") {
    const rows = Object.entries(s.inputs || {}).map(([k, v], i) => mapRowHtml(i, k, v, s)).join("");
    return `
      <div class="ins-note dim"><code>{{name}}</code> = run input · <code>{{step.field}}</code> = previous step output · bare text = literal. Use the source selector so you don't have to type references.</div>
      ${subLabel("Input parameters", "Values fed to this step. <b>Run input</b> asks at launch (wraps as <code>{{name}}</code>); <b>Previous step</b> pipes an upstream output field (<code>{{step.field}}</code>); <b>Literal value</b> hardcodes text, a number or a value like an IP or URL.", `<button class="btn icon" id="insAddInput" title="Add input parameter">＋</button>`)}
      <div id="insInputRows">${rows || `<p class="dim map-none">No inputs mapped yet — add one below.</p>`}</div>`;
  }
  const isTool = s.type === "tool";
  const schema = isTool ? toolInputSchema(s.tool) : null;
  if (isTool && schema) {
    const req = schema.required || [];
    const props = schema.properties;
    const argd = s.args || {};
    const rows = Object.entries(props).map(([k, p]) => argRowHtml(k, p, argd[k], req)).join("");
    const extras = Object.keys(argd).filter((k) => !props[k]).map((k) => argExtraRowHtml(k, argd[k])).join("");
    return `
      ${subLabel("Tool arguments", `Arguments for <b>${esc(s.tool || "tool")}</b>, straight from the registry's input schema — names and types are fixed, hover each <b>?</b> for what the argument does. Filled values become the JSON shown on the <i>Edit raw JSON</i> view.`)}
      <div id="argBuilder">${rows || `<p class="dim map-none">This tool takes no arguments.</p>`}${extras}</div>
      <button class="btn ghost sm" id="argAddExtra" type="button">＋ Extra argument</button>
      <button class="btn ghost sm" id="argRawToggle" type="button">Edit raw JSON</button>
      <textarea class="select area" id="insArgs" hidden style="min-height:150px;font-family:ui-monospace,Menlo,monospace" spellcheck="false">${esc(JSON.stringify(s.args || {}, null, 2))}</textarea>
      <div class="ins-note dim">Prefer a JSON blob? <i>Edit raw JSON</i> switches this same data to a raw view.</div>`;
  }
  return `
    ${subLabel(isTool ? "Tool arguments (JSON object)" : "Module arguments (JSON object)", isTool
      ? `No schema registered for <code>${esc(s.tool || "this tool")}</code> — write the arguments object by hand, e.g. <code>{"target":"10.0.0.5","verbose":true}</code>. Keys should match the tool's input schema in the Tool Registry.`
      : `Internal module stage arguments. The required keys depend on the module — the server reports a precise error if one is missing. Run inputs are referenced as <code>{{name}}</code>.`)}
    <textarea class="select area" id="insArgs" style="min-height:150px;font-family:ui-monospace,Menlo,monospace" spellcheck="false">${esc(JSON.stringify(s.args || {}, null, 2))}</textarea>`;
}

function insOutputsTab(s) {
  if (s.type === "shell") {
    const f = s.filter && s.filter.type === "none" ? { type: "none" } : (s.filter || { type: "grep", pattern: "" });
    const fields = namedGroups(f.pattern);
    return `
      ${subLabel("Output extraction", "Cut structured values out of the command output. <b>grep</b> returns the first/last matching line, <b>regex</b> applies a pattern with named capture groups <code>(?P&lt;field&gt;…)</code> — each named group becomes an output field the next step can map as <code>{{thisstepid.field}}</code>.")}
      <div class="ins-filter-row">
        <select class="select" id="insFilterType">
          ${["grep", "regex", "none"].map((v) => `<option value="${v}" ${v === (s.filter?.type || "grep") ? "selected" : ""}>${v}</option>`).join("")}
        </select>
        <label class="checkline sm">first match only <input type="checkbox" id="insFilterFirst" ${s.filter?.first_only ? "checked" : ""}></label>
      </div>
      ${insLabel("Pattern", `<input class="select mono" id="insFilterPattern" value="${esc(f.pattern || "")}" placeholder='(?P<ip>[0-9]+\\.[0-9.]+)'>`,
        "Applies to the raw command output. Named groups become mapped fields — e.g. <code>(?P<host>[a-z0-9.-]+)</code> becomes <code>{{&lt;this step's id&gt;.host}}</code> for the next step.")}
      ${subLabel("Extracted fields", "Preview of what downstream steps can map — comes from the named <code>(?P&lt;group&gt;…)</code> groups above.")}
      ${fields.length ? `<div class="chip-row">${fields.map((x) => `<span class="chip accent mono">${esc(s.id)}.${esc(x)}</span>`).join("")}</div>` : `<p class="dim">No named fields — downstream steps will only see raw text unless you add (?P&lt;name&gt;…) groups.</p>`}`;
  }
  return `<div class="ins-note">This step type produces its outputs internally (findings, correlations, scope checks or the assessment report) — no manual output extraction to configure.</div>`;
}

function insAdvancedTab(s) {
  return `
    ${subLabel("Execution arguments", "Extra JSON settings for the runner. Shell nodes can use <code>{name}</code> placeholders filled from the Inputs tab. Common keys: <code>timeout</code>, <code>verbose</code>.")}
    <textarea class="select area" id="insArgs" style="min-height:130px;font-family:ui-monospace,Menlo,monospace" spellcheck="false">${esc(JSON.stringify(s.args || {}, null, 2))}</textarea>
    ${insLabel("Condition (when)", `<input class="select mono" id="insWhen" value="${esc(s.when || "")}" placeholder="e.g. outputs? no match => skip">`,
      "Skips this step when the expression is falsy (0, false, empty). Leave blank to always run.")}`;
}

function insTabsHtml(s) {
  return `
    <div class="ins-head">
      <div class="ins-idline"><span class="mono">${esc(s.id)}</span><span class="chip">${esc(s.type || "step")}</span>
        <button class="btn ghost icon ins-close" id="insClose" title="Close inspector">×</button></div>
      <div class="ins-tabs" role="tablist">
        ${INS_TABS.map((t) => `<button class="${t === inspectTab ? "active" : ""}" data-tab="${t}" role="tab">${INS_TAB_LABELS[t]}</button>`).join("")}
      </div>
    </div>
    <div class="ins-body" id="insBody">${
      inspectTab === "general" ? insGeneralTab(s)
      : inspectTab === "inputs" ? insInputsTab(s)
      : inspectTab === "outputs" ? insOutputsTab(s)
      : insAdvancedTab(s)}</div>
    <div class="ins-foot">
      <span class="dim" id="insNote"></span>
      <div class="ins-foot-btns">
        <button class="btn danger" id="insDel">Delete node</button>
        <button class="btn primary" id="insApply">Apply</button>
      </div>
    </div>`;
}

function renderInspector() {
  const inj = $("#inspector");
  if (!inj) return;
  const s = graphSel ? stepById(graphSel) : null;
  if (!s) {
    inj.innerHTML = `
      <div class="ins-empty">
        <div class="eyebrow">INSPECTOR</div>
        <p class="empty">Select a step on the canvas to edit its configuration. Graph and DSL always edit the same canonical model.</p>
      </div>`;
    return;
  }
  inj.innerHTML = insTabsHtml(s);

  $$("#inspector .ins-tabs button").forEach((btn) =>
    btn.addEventListener("click", () => {
      const s = stepById(graphSel);
      if (s) applyTabFields(s);   // persist this tab's edits before switching
      inspectTab = btn.dataset.tab;
      renderInspector();
    }));

  $("#insApply")?.addEventListener("click", () => applyNodeInspector());
  $("#insDel")?.addEventListener("click", () => deleteGraphStep(graphSel));
  $("#insClose")?.addEventListener("click", () => $("#insCol")?.classList.remove("ins-open"));
  $("#insAddInput")?.addEventListener("click", () => addMapRow());

  // tool-argument schema builder wiring
  const bld = $("#argBuilder");
  if (bld) {
    $("#argRawToggle")?.addEventListener("click", () => {
      const ta = $("#insArgs");
      if (!ta) return;
      if (ta.hidden) {
        // seed raw view from the current builder fields
        const { args, missing } = collectBuilderArgs();
        if (!missing.length && Object.keys(args).length) {
          ta.value = JSON.stringify(args, null, 2);
        }
      }
      ta.hidden = !ta.hidden;
      bld.style.display = ta.hidden ? "" : "none";
      $("#argAddExtra") && ($("#argAddExtra").style.display = ta.hidden ? "" : "none");
      $("#argRawToggle").textContent = ta.hidden ? "Edit raw JSON" : "Use form fields";
      $("#argRawToggle").focus();
    });
    $("#argAddExtra")?.addEventListener("click", () => {
      const wrap = document.createElement("div");
      wrap.innerHTML = argExtraRowHtml("", "");
      const row = wrap.firstElementChild;
      bld.appendChild(row);
      row.querySelector(".arg-extra-name").focus();
    });
    // switching the tool re-opens the inspector on Inputs so the schema follows
    $("#insTool")?.addEventListener("change", () => {
      const s2 = stepById(graphSel);
      if (!s2) return;
      const t = $("#insTool").value.trim();
      if (t) s2.tool = t; else delete s2.tool;
      inspectTab = "inputs";
      renderInspector();
    });
  }

  // flip tooltips near the right edge / top of the scroll area so bubbles aren't clipped
  const bodyEl = $("#insBody");
  const bodyRect = bodyEl && typeof bodyEl.getBoundingClientRect === "function"
    ? bodyEl.getBoundingClientRect() : null;
  $$("#insBody .help-tip").forEach((b) => {
    const r = b.getBoundingClientRect();
    if (r.right + 270 > document.documentElement.clientWidth - 12) b.classList.add("tip-left");
    if (bodyRect && r.top - 130 < bodyRect.top) b.classList.add("tip-down");
  });

  // mapper wiring
  $$("#insBody .map-row").forEach((row) => {
    row.querySelectorAll(".map-mode").forEach((sel) => sel.addEventListener("change", () => {
      row.dataset.mode = sel.value;
    }));
    const stepSel = row.querySelector(".map-step");
    const fieldInp = row.querySelector(".map-field");
    if (stepSel && fieldInp) stepSel.addEventListener("change", () => {
      const dl = row.querySelector("datalist");
      if (dl) dl.innerHTML = upstreamOutFields(stepSel.value).map((x) => `<option value="${esc(x)}"></option>`).join("");
      fieldInp.value = "";
    });
    const whole = row.querySelector(".map-field-whole");
    if (whole && stepSel) {
      whole.addEventListener("change", () => {
        const m = whole.value.match(/^(\w+)\.(\w+)$/);
        if (m) { stepSel.value = m[1]; fieldInp.value = m[2]; }
      });
    }
    row.querySelector(".map-del")?.addEventListener("click", () => row.remove());
  });
}

function mapRowHtml(i, key, rawVal, s) {
  const ref = parseRef(rawVal);
  const upstreamSteps = getGraphSteps().filter((x) => x.id !== s.id);
  const preferred = ref.mode === "upstream" ? ref.step
    : ((s.depends_on || []).find((d) => stepById(d)) || upstreamSteps[0]?.id || "");
  const fields = upstreamOutFields(preferred);
  return `
    <div class="map-row" data-mode="${ref.mode}">
      <div class="map-k"><input class="select inp map-key" value="${esc(key)}" placeholder="parameter name"></div>
      <div class="map-src">
        <select class="select map-mode" title="Where is the value coming from?">
          <option value="run" ${ref.mode === "run" ? "selected" : ""}>Run input</option>
          <option value="upstream" ${ref.mode === "upstream" ? "selected" : ""}>Previous step</option>
          <option value="literal" ${ref.mode === "literal" ? "selected" : ""}>Literal value</option>
        </select>
      </div>
      <div class="map-arg">
        <div class="mf mf-run"><input class="select map-run" list="dlRunInputs" value="${ref.mode === "run" ? esc(ref.name) : ""}" placeholder="run input name"></div>
        <div class="mf mf-up">
          <select class="select map-step">
            <option value="">— step —</option>
            ${upstreamSteps.map((x) => `<option value="${esc(x.id)}" ${x.id === preferred ? "selected" : ""}>${esc(x.id)}</option>`).join("")}
          </select>
          <input class="select map-field" list="dlFields_${i}" value="${ref.mode === "upstream" ? esc(ref.field) : ""}" placeholder="output field">
          <datalist id="dlFields_${i}">${fields.map((x) => `<option value="${esc(x)}"></option>`).join("")}</datalist>
        </div>
        <div class="mf mf-lit"><input class="select map-lit" value="${ref.mode === "literal" ? esc(ref.val) : ""}" placeholder="literal value"></div>
      </div>
      <button class="btn danger icon map-del" title="Remove input">×</button>
    </div>`;
}

function addMapRow() {
  const rows = $("#insInputRows");
  if (!rows || !graphSel) return;
  const s = stepById(graphSel);
  const none = rows.querySelector(".map-none");
  if (none) none.remove();
  const wrap = document.createElement("div");
  wrap.innerHTML = mapRowHtml(999, "", "", s).replace(/999/g, `n${Date.now().toString(36)}`);
  const row = wrap.firstElementChild;
  rows.appendChild(row);
  row.querySelector(".map-mode").addEventListener("change", () => { row.dataset.mode = row.querySelector(".map-mode").value; });
  const stepSel = row.querySelector(".map-step");
  const fieldInp = row.querySelector(".map-field");
  if (stepSel) stepSel.addEventListener("change", () => {
    const dl = row.querySelector("datalist");
    if (dl) dl.innerHTML = upstreamOutFields(stepSel.value).map((x) => `<option value="${esc(x)}"></option>`).join("");
    fieldInp.value = "";
  });
  row.querySelector(".map-del").addEventListener("click", () => row.remove());
  row.querySelector(".map-key").focus();
}

/* apply: merges whichever fields are present in the current tab */
/* pull the currently-shown inspector fields into step object s from the DOM.
   Best-effort, no toasts, no canvas re-render — used to persist a tab's edits
   before switching tabs/pages so nothing the user typed is thrown away. */
function applyTabFields(s) {
  if (!s) return;
  const oldId = s.id;

  const idEl = $("#insId");
  if (idEl) {
    const newId = (idEl.value || "").trim();
    if (newId && newId !== oldId && !getGraphSteps().some((x) => x.id === newId)) {
      getGraphSteps().forEach((x) => {
        if (Array.isArray(x.depends_on)) x.depends_on = x.depends_on.map((d) => (d === oldId ? newId : d));
      });
      delete graphPos[oldId];
      s.id = newId;
    }
  }

  const depsEl = $("#insDeps");
  if (depsEl) {
    s.depends_on = depsEl.value.split(",").map((d) => d.trim()).filter(Boolean) || [];
  }

  const typeEl = $("#insType");
  if (typeEl && typeEl.value !== s.type) {
    s.type = typeEl.value;
    if (s.type !== "tool") delete s.tool;
  } else if (s.type === "shell" && !typeEl) {
    s.type = "shell";
  }

  const toolEl = $("#insTool");
  if (toolEl && s.type === "tool") {
    const t = toolEl.value.trim();
    if (t) s.tool = t; else delete s.tool;
  }

  const rowsEl = $("#insInputRows");
  if (rowsEl) {
    const inputs = {};
    $$("#insInputRows .map-row").forEach((row) => {
      const k = (row.querySelector(".map-key")?.value || "").trim();
      if (!k) return;
      const mode = row.querySelector(".map-mode")?.value || "literal";
      let v = "";
      if (mode === "run") v = `{{${(row.querySelector(".map-run")?.value || "").trim()}}}`;
      else if (mode === "upstream") {
        const st = (row.querySelector(".map-step")?.value || "").trim();
        const fl = (row.querySelector(".map-field")?.value || "").trim();
        if (!st || !fl) return; // keep previous value for this row
        v = `{{${st}.${fl}}}`;
      } else v = (row.querySelector(".map-lit")?.value || "").trim();
      if (v) inputs[k] = v;
    });
    if (Object.keys(inputs).length) s.inputs = inputs; else delete s.inputs;
  }

  const cmdEl = $("#insCommand");
  if (cmdEl) {
    const cmd = (cmdEl.value || "").trim();
    if (cmd) s.command = cmd; else delete s.command;
    s.type = "shell";
  }

  const ftypeEl = $("#insFilterType");
  if (ftypeEl) {
    const ftype = ftypeEl.value || "none";
    const fpat = ($("#insFilterPattern")?.value || "").trim();
    if (ftype === "none") {
      s.filter = { type: "none" };
    } else if (ftype && ftype !== "none" && fpat) {
      s.filter = { type: ftype, pattern: fpat };
      if ($("#insFilterFirst")?.checked) s.filter.first_only = true;
    } else delete s.filter;
  }

  const argsEl = $("#insArgs");
  if (argsEl) {
    const builder = $("#argBuilder");
    if (builder && argsEl.hidden) {
      const { args, missing } = collectBuilderArgs();
      if (!missing.length) {
        const sc = toolInputSchema(s.tool);
        const lack = sc ? (sc.required || []).filter((k) => args[k] === undefined || args[k] === "" || args[k] === null) : [];
        if (!lack.length) {
          if (Object.keys(args).length) s.args = args; else delete s.args;
        }
      }
    } else {
      try {
        const parsed = JSON.parse(argsEl.value || "{}");
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          if (Object.keys(parsed).length) s.args = parsed; else delete s.args;
        }
      } catch { /* keep previous args */ }
    }
  }

  const whenEl = $("#insWhen");
  if (whenEl) {
    const when = whenEl.value.trim();
    if (when) s.when = when; else delete s.when;
  }

  const ckEl = $("#insCheckpoint");
  if (ckEl && ckEl.checked) s.checkpoint = true; else if (ckEl) delete s.checkpoint;
}

function applyNodeInspector() {
  const s = stepById(graphSel);
  if (!s) return;
  const oldId = s.id;
  const ids = new Set(getGraphSteps().map((x) => x.id).filter((x) => x !== oldId));

  const idEl = $("#insId");
  if (idEl) {
    const newId = (idEl.value || "").trim();
    if (!newId) return toast("Step id required", true);
    if (newId !== oldId && ids.has(newId)) return toast(`Step id "${newId}" already used`, true);
  }

  applyTabFields(s);

  // required-argument / invalid-arg guards (only on explicit Save)
  const rowsEl = $("#insInputRows");
  if (rowsEl) {
    $$("#insInputRows .map-row").forEach((row) => {
      const k = (row.querySelector(".map-key")?.value || "").trim();
      if (!k) return;
      const mode = row.querySelector(".map-mode")?.value || "literal";
      if (mode === "upstream") {
        const st = (row.querySelector(".map-step")?.value || "").trim();
        const fl = (row.querySelector(".map-field")?.value || "").trim();
        if (!st || !fl) { toast(`${k}: pick a step and an output field`, true); }
      }
    });
  }
  const argsEl = $("#insArgs");
  if (argsEl) {
    const builder = $("#argBuilder");
    if (builder && argsEl.hidden) {
      const sc = toolInputSchema(s.tool);
      if (sc) {
        const argd = s.args || {};
        const lack = (sc.required || []).filter((k) => argd[k] === undefined || argd[k] === "" || argd[k] === null);
        if (lack.length) return toast(`Required argument${lack.length > 1 ? "s" : ""} ${lack.map((k) => `"${k}"`).join(", ")} missing for ${s.tool}`, true);
      }
    }
  }

  graphSel = s.id;
  captureGraphToDSL();
  renderBuilder();
  toast(`Step ${s.id} updated`);
}

/* compat wrappers (graph engine kept API-compatible for tooling) */
function applyShellInspector() { applyNodeInspector(); }
function applyInspector() { applyNodeInspector(); }

/* ── node mutations ────────────────────────────────────────────────── */

function deleteGraphStep(id) {
  pushHistory();
  graphDef.steps = getGraphSteps().filter((s) => s.id !== id);
  getGraphSteps().forEach((s) => {
    if (Array.isArray(s.depends_on)) s.depends_on = s.depends_on.filter((d) => d !== id);
  });
  graphSel = null;
  captureGraphToDSL();
  renderBuilder();
  toast(`Step ${id} deleted`);
}

function nextId(prefix) {
  let n = 1, id;
  do { id = `${prefix}_${n++}`; } while (stepById(id));
  return id;
}

function addGraphStep() {
  if (builderView !== "graph") { if (!loadGraphFromDSL()) return; }
  pushHistory();
  getGraphSteps().push({ id: nextId("step"), type: "tool", depends_on: [] });
  graphSel = getGraphSteps().slice(-1)[0].id;
  captureGraphToDSL();
  renderBuilder();
}

function addToolStep(toolName, forcedType) {
  if (builderView !== "graph") { if (!loadGraphFromDSL()) return; }
  pushHistory();
  const base = (toolName || "tool").replace(/[^a-zA-Z0-9_]/g, "_").slice(0, 24) || "tool";
  const s = { id: nextId(base), type: forcedType || "tool", depends_on: [] };
  if (toolName && (forcedType || "tool") === "tool") s.tool = toolName;
  getGraphSteps().push(s);
  graphSel = s.id;
  captureGraphToDSL();
  renderBuilder();
  inspectTab = "inputs";
  renderInspector();
  toast(`Added ${s.id}`);
}

function addShellStep() {
  if (builderView !== "graph") { if (!loadGraphFromDSL()) return; }
  pushHistory();
  const id = nextId("shell");
  getGraphSteps().push({
    id, type: "shell", command: "", inputs: {},
    filter: { type: "grep", pattern: "" }, depends_on: [],
  });
  graphSel = id;
  captureGraphToDSL();
  renderBuilder();
  inspectTab = "inputs";
  renderInspector();
  toast(`Added shell node ${id} — configure inputs, command and filter in the inspector`);
}

/* ── node dragging ────────────────────────────────────────────────── */

let dragCtx = null;
function startNodeDrag(e, id, origin) {
  if (e.button !== 0) return;
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
  const up = (ev) => {
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", up);
    if (!moved) {
      const isPort = ev.target instanceof Element && ev.target.classList.contains("port");
      if (pendingConnect && isPort && pendingConnect !== id) { disarmConnect(); completeConnect(pendingConnect, id); return; }
      const sel = getGraphSteps().find((x) => x.id === id);
      graphSel = id;
      if (sel) inspectTab = "general";
      renderBuilder();
      if (window.matchMedia("(max-width: 1023px)").matches) $("#insCol")?.classList.add("ins-open");
    }
  };
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
}

/* ── edge creation ────────────────────────────────────────────────── */

let connectCtx = null;
function wouldCreateCycle(srcId, tgtId) {
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

let pendingConnect = null;

function armConnect(srcId) {
  pendingConnect = srcId;
  $$(".port").forEach((p) => p.classList.remove("armed"));
  const el = $(`.node[data-step="${CSS.escape(srcId)}"] .port.right`);
  if (el) el.classList.add("armed");
  toast(`Connect: click the target node's ○ left port (Esc to cancel)`);
}

function disarmConnect() {
  pendingConnect = null;
  $$(".port").forEach((p) => p.classList.remove("armed"));
}

function completeConnect(srcId, tgtId) {
  if (tgtId === srcId) { toast("A step cannot depend on itself", true); disarmConnect(); return; }
  if (wouldCreateCycle(srcId, tgtId)) { toast(`Wire ${srcId} → ${tgtId} would create a cycle`, true); disarmConnect(); return; }
  const s = stepById(tgtId);
  if (!s) { disarmConnect(); return; }
  s.depends_on = Array.isArray(s.depends_on) ? s.depends_on : [];
  if (s.depends_on.includes(srcId)) { toast(`${tgtId} already depends on ${srcId}`); disarmConnect(); return; }
  pushHistory();
  s.depends_on.push(srcId);
  disarmConnect();
  captureGraphToDSL();
  renderBuilder();
  toast(`Connected ${srcId} → ${tgtId}`);
}

function clearConnectPreview() {
  const p = $("#connectPreview");
  if (p) p.remove();
}

function startPortConnect(e, srcId) {
  e.preventDefault();
  e.stopPropagation();
  const startX = e.clientX, startY = e.clientY;
  const depths = {};
  graphLayout(depths);
  const a = nodePos(srcId, depths);
  const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2;
  connectCtx = { srcId, depths };
  const inner = $("#canvasInner");
  const toCanvas = (ev) => {
    const r = inner.getBoundingClientRect();
    return { x: (ev.clientX - r.left) / graphZoom, y: (ev.clientY - r.top) / graphZoom };
  };
  const move = (ev) => {
    const dx = ev.clientX - startX, dy = ev.clientY - startY;
    if (Math.hypot(dx, dy) < 4) return;
    disarmConnect();
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
    if (Math.hypot(ev.clientX - startX, ev.clientY - startY) < 4) { disarmConnect(); armConnect(srcId); return; }
    const hit = document.elementFromPoint(ev.clientX, ev.clientY)?.closest(".node");
    if (!hit) return;
    const tgtId = hit.dataset.step;
    if (!tgtId) return;
    completeConnect(srcId, tgtId);
  };
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", up);
}

/* Esc cancels an armed click-connect */
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && pendingConnect) {
    disarmConnect();
    const col = $("#insCol");
    if (col) col.classList.remove("ins-open");
  }
  /* Delete / Backspace removes the selected node (when not typing in a field). */
  if ((e.key === "Delete" || e.key === "Backspace") && graphSel) {
    const active = document.activeElement;
    if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA"
      || active.tagName === "SELECT" || active.isContentEditable)) return;
    e.preventDefault();
    deleteGraphStep(graphSel);
  }
});

/* Clicking the ? help icon toggles its bubble; hover still works too. */
document.addEventListener("click", (e) => {
  const tip = e.target.closest(".help-tip");
  if (!tip) return;
  e.stopPropagation();
  tip.classList.toggle("open");
});

function redrawEdges() {
  const depths = {};
  graphLayout(depths);
  const svg = $("#edgeLayer");
  if (!svg) return;
  let edges = "";
  for (const s of getGraphSteps()) {
    for (const dep of s.depends_on || []) {
      if (!depths.hasOwnProperty(dep) || dep === s.id) continue;
      const a = nodePos(dep, depths), b = nodePos(s.id, depths);
      const y1 = a.y + NODE_H / 2, y2 = b.y + NODE_H / 2;
      const hot = graphSel === dep || graphSel === s.id ? " hot" : "";
      edges += `<path class="edge${hot}" d="M${a.x + NODE_W},${y1} C${(a.x + NODE_W + b.x) / 2},${y1} ${(a.x + NODE_W + b.x) / 2},${y2} ${b.x},${y2}"/>`;
    }
  }
  svg.innerHTML = edges;
}

function addStage(type) {
  if (builderView !== "graph") { if (!loadGraphFromDSL()) return; }
  pushHistory();
  const id = nextId(type === "scope_check" ? "scope" : type === "finding_correlation" ? "corr" : "report");
  getGraphSteps().push({ id, type, depends_on: [] });
  graphSel = id;
  captureGraphToDSL();
  renderBuilder();
  toast(`Added ${id} (${type})`);
}

/* ── run: input modal built from the playbook's input specs ────────── */

async function runModal(id) {
  let def = null;
  try { def = (await api(`/playbooks/${encodeURIComponent(id)}/definition`)).definition; } catch { /* not saved yet */ }
  // Always prefer the live editor graph (graphDef) — it holds the user's
  // unsaved step inputs / {{name}} references. Only fall back to the server
  // definition when the editor graph hasn't been loaded yet.
  if (graphDef) {
    applyTabFields(stepById(graphSel));
    def = graphDef;
  } else if (!def) {
    // server returned null (unsaved draft, server not yet restarted); nothing to show
    def = null;
  }
  const declared = defInputs(def);
  const stepDerived = collectRunInputs(def);
  const byName = new Map();
  for (const sp of [...stepDerived, ...declared]) byName.set(sp.name, sp); // declared overrides step-derived
  const specs = [...byName.values()];
  const rows = specs.map((sp) => {
    const type = String(sp.spec?.type || "string");
    const required = sp.spec?.required ? "required" : "optional";
    let field;
    if (type === "boolean") {
      field = `<select class="select run-in" data-name="${esc(sp.name)}"><option value="true">true</option><option value="false">false</option></select>`;
    } else if (type === "integer" || type === "number") {
      field = `<input class="select run-in" data-name="${esc(sp.name)}" type="number" value="${sp.spec?.default ?? ""}">`;
    } else if (type === "array" || type === "object") {
      field = `<textarea class="select area run-in" data-name="${esc(sp.name)}" spellcheck="false" style="min-height:56px;font-family:ui-monospace,Menlo,monospace" placeholder="JSON ${type}">${esc(JSON.stringify(sp.spec?.default ?? (type === "array" ? [] : {})))}</textarea>`;
    } else {
      field = `<input class="select run-in" data-name="${esc(sp.name)}" value="${esc(String(sp.spec?.default ?? ""))}">`;
    }
    return `
      <div class="run-row">
        <div class="run-row-head"><b class="mono">${esc(sp.name)}</b>
          <span class="chip ${sp.spec?.required ? "ck" : ""}">${esc(type)} · ${esc(required)}</span></div>
        ${field}
      </div>`;
  }).join("");
  const bd = document.createElement("div");
  bd.className = "modal-backdrop show";
  bd.innerHTML = `
    <div class="modal run-modal">
      <h3>Run “${esc(id)}”</h3>
      <p class="dim">Runs the published version. This playbook takes ${specs.length} input${specs.length === 1 ? "" : "s"} — anything omitted falls back to its default.</p>
      ${rows || `<p class="dim">No declared inputs — start a run directly, or add extra ones as JSON below.</p>`}
      <div class="run-row">
        <div class="run-row-head"><b>Extra inputs</b><span class="chip">JSON · optional</span></div>
        <textarea class="select area" id="runExtra" spellcheck="false" style="min-height:64px;font-family:ui-monospace,Menlo,monospace">{}</textarea>
      </div>
      <div class="run-row">
        <label class="checkline" style="margin:0">
          <input type="checkbox" id="runDebug" checked />
          Debug run (marks this execution as a manual debug run)
        </label>
      </div>
      <div class="modal-actions">
        <button class="btn" id="runCancel">Cancel</button>
        <button class="btn primary" id="runStart">▶ Start run</button>
      </div>
    </div>`;
  document.body.appendChild(bd);
  bd.querySelector("#runCancel").addEventListener("click", () => bd.remove());
  bd.addEventListener("mousedown", (e) => { if (e.target === bd) bd.remove(); });
  bd.querySelector("#runStart").addEventListener("click", async () => {
    const inputs = {};
    let ok = true;
    bd.querySelectorAll(".run-in").forEach((f) => {
      const k = f.dataset.name;
      if (f.tagName === "TEXTAREA") {
        const raw = (f.value || "").trim();
        if (!raw) return;
        try { inputs[k] = JSON.parse(raw); }
        catch { toast(`Input ${k} must be valid JSON`, true); ok = false; }
        return;
      }
      if (f.value === "") return;
      inputs[k] = f.getAttribute("type") === "number" ? Number(f.value) : f.value;
    });
    let extra = {};
    const rawExtra = (bd.querySelector("#runExtra").value || "").trim();
    if (rawExtra) {
      try { extra = JSON.parse(rawExtra); }
      catch { toast("Extra inputs must be valid JSON", true); ok = false; }
    }
    if (!ok) return;
    Object.assign(inputs, extra || {});
    bd.remove();
    const debug = bd.querySelector("#runDebug")?.checked === true;
    await startRun(id, inputs, { debug: true, trigger: "studio" });
  });
}

async function startRun(id, inputs, opts = {}) {
  toast(`Starting ${id}${opts.debug ? " (debug)" : ""}…`);
  try {
    const r = await api("/executions", { method: "POST", body: JSON.stringify({ playbook_id: id, inputs, debug: !!opts.debug, trigger: opts.trigger || "studio" }) });
    const execId = r?.execution?.execution_id || r?.execution_id || "";
    toast(`Run started${execId ? `: ${execId}` : ""}`);
    location.hash = execId ? `#/executions/${encodeURIComponent(execId)}` : "#/executions";
  } catch (err) { toast(err.message, true); }
}

/* surface the latest execution's per-step status on the graph */
async function loadRunStatus(id) {
  try {
    const d = await api("/executions?limit=25");
    const mine = (d.executions || []).filter((e) => e.playbook_id === id);
    if (!mine.length) return;
    const det = await api(`/executions/${encodeURIComponent(mine[0].execution_id)}`);
    const map = {};
    for (const s of det.steps || []) map[s.step_id] = s.status;
    runStatus = map;
    if (builderView === "graph" && $("#canvasInner")) renderBuilder();
  } catch { /* best-effort only */ }
}

/* ── playbook-level actions ────────────────────────────────────────── */

async function validateDefinition() {
  const out = $("#editorResult");
  if (!selectedId) return toast("Select a playbook first", true);
  if (builderView === "graph") { applyTabFields(stepById(graphSel)); captureGraphToDSL(); }
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
}

async function saveDraft() {
  if (!selectedId) return toast("Select a playbook first", true);
  if (builderView === "graph") { applyTabFields(stepById(graphSel)); captureGraphToDSL(); }
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
  if (builderView === "graph") { applyTabFields(stepById(graphSel)); captureGraphToDSL(); }
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

/* ── create: structured modal (name → auto id → category → description) */

async function newPlaybook() {
  const existing = new Set(playbooksCache.map((p) => p.playbook_id));
  const bd = document.createElement("div");
  bd.className = "modal-backdrop show";
  bd.innerHTML = `
    <div class="modal new-pb-modal" role="dialog" aria-modal="true" aria-labelledby="npTitle">
      <div class="np-head">
        <div class="np-glyph">✦</div>
        <div>
          <h3 id="npTitle">New playbook</h3>
          <p class="dim">Name it here — the workflow canvas opens right after, so you can start wiring steps immediately.</p>
        </div>
      </div>
      <label class="np-field">
        <span class="np-label">Name <em>shown in the library and editor header</em></span>
        <input class="select" id="npName" placeholder="e.g. External recon sweep" autocomplete="off" spellcheck="false">
      </label>
      <label class="np-field">
        <span class="np-label">Playbook ID <em>stable identifier used in runs and URLs — auto-filled from the name</em></span>
        <input class="select mono" id="npId" placeholder="external_recon_sweep" autocomplete="off" spellcheck="false">
        <span class="np-hint" id="npHint"></span>
      </label>
      <div class="np-row2">
        <label class="np-field">
          <span class="np-label">Category</span>
          <select class="select" id="npCat">
            <option value="custom">custom</option>
            <option value="recon">recon</option>
            <option value="assessment">assessment</option>
            <option value="reporting">reporting</option>
            <option value="response">response</option>
          </select>
        </label>
        <label class="np-field np-col">
          <span class="np-label">Description <em>optional</em></span>
          <input class="select" id="npDesc" placeholder="What does this workflow do?">
        </label>
      </div>
      <div class="modal-actions">
        <button class="btn" id="npCancel">Cancel</button>
        <button class="btn primary" id="npCreate" disabled>Create playbook</button>
      </div>
    </div>`;
  document.body.appendChild(bd);

  const nameEl = bd.querySelector("#npName"), idEl = bd.querySelector("#npId"),
    hintEl = bd.querySelector("#npHint"), catEl = bd.querySelector("#npCat"),
    descEl = bd.querySelector("#npDesc"), createBtn = bd.querySelector("#npCreate");
  let idDirty = false;

  function slugify(v) {
    const s = String(v).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);
    return s || (v ? `pb_${Date.now().toString(36)}` : "");
  }
  function validate() {
    let err = "";
    const id = idEl.value;
    if (id && existing.has(id)) err = `A playbook with ID “${id}” already exists`;
    else if (/[^\w-]/.test(id)) err = "Letters, numbers, dashes and underscores only";
    hintEl.textContent = err;
    hintEl.classList.toggle("warn", !!err);
    if (err) { createBtn.disabled = true; return false; }
    createBtn.disabled = !(nameEl.value.trim() && id);
    return true;
  }

  idEl.addEventListener("input", () => { idDirty = true; validate(); });
  nameEl.addEventListener("input", () => { if (!idDirty) idEl.value = slugify(nameEl.value); validate(); });
  descEl.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  [nameEl, idEl].forEach((el) => el.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); }));
  document.addEventListener("keydown", escClose);

  function escClose(e) { if (e.key === "Escape") close(); }
  function close() {
    document.removeEventListener("keydown", escClose);
    bd.remove();
  }
  async function submit() {
    if (!validate() || createBtn.disabled) return;
    const name = nameEl.value.trim().slice(0, 120);
    const pid = idEl.value.trim();
    if (existing.has(pid)) { nameEl.reportValidity?.(); return; }
    const payload = { playbook_id: pid, name, category: catEl.value };
    if (descEl.value.trim()) payload.description = descEl.value.trim();
    createBtn.disabled = true;
    createBtn.textContent = "Creating…";
    try {
      await api("/playbooks", { method: "POST", body: JSON.stringify(payload) });
    } catch (err) {
      createBtn.disabled = false;
      createBtn.textContent = "Create playbook";
      return toast(err.message, true);
    }
    close();
    toast(`“${name}” created — opening the editor`);
    location.hash = `#/playbooks/${encodeURIComponent(pid)}`;
  }

  bd.querySelector("#npCancel").addEventListener("click", close);
  createBtn.addEventListener("click", submit);
  bd.addEventListener("mousedown", (e) => { if (e.target === bd) close(); });
  nameEl.focus();
}

async function deletePlaybook() {
  if (!selectedId) return toast("Select a playbook first", true);
  if (!confirm(`Delete playbook ${selectedId}? This cannot be undone.`)) return;
  try {
    await api(`/playbooks/${encodeURIComponent(selectedId)}`, { method: "DELETE" });
    toast("Playbook deleted");
    location.hash = "#/playbooks";
  } catch (err) { toast(err.message, true); }
}

async function showVersions() {
  if (!selectedId) return toast("Select a playbook first", true);
  try {
    const d = await api(`/playbooks/${encodeURIComponent(selectedId)}/versions`);
    const list = d.versions || [];
    if (!list.length) return toast("No versions published yet");
    const pick = list.map((v) => `${v.version_id}. ${v.version}`).join("\n");
    const choice = prompt(`Versions:\n${pick}\n\nEnter version_id to roll back:`, "");
    if (!choice) return;
    await api(`/playbooks/${encodeURIComponent(selectedId)}/rollback`, {
      method: "POST", body: JSON.stringify({ version_id: choice }),
    });
    toast("Rolled back");
    await pagePlaybookEditor(selectedId);
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

/* ── route: executions ─────────────────────────────────────────────── */

let execTimer = null;

async function refreshExecutions(status) {
  const q = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "?limit=100";
  const d = await api(`/executions${q}`);
  const list = d.executions || [];
  const el = $("#execTable");
  if (!el) return;
  el.innerHTML = table(["Execution", "Playbook", "Trigger", "Status", "Started", "Completed"],
    list.map((e) => ({
      cells: [
        `<a href="#/executions/${esc(e.execution_id)}">${esc(e.execution_id)}</a>`,
        esc(e.playbook_id || "—"),
        `${esc(e.trigger || "—")}${Number(e.debug) ? " <span class=\"chip ck\">debug</span>" : ""}`,
        BADGE(e.status),
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
    <div class="subtitle">${esc(e.playbook_id || "")} <span style="margin-left:8px">${BADGE(e.status)}</span>
      ${e.trigger ? ` <span style="margin-left:8px">trigger: <b class="mono">${esc(e.trigger)}</b></span>` : ""}
      ${Number(e.debug) ? ` <span class="chip ck" style="margin-left:8px">debug</span>` : ""}
    </div>`;
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
      <div style="padding:8px">${table(["Step", "Tool", "Status"], (d.steps || []).map((s) => ({
        cells: [esc(s.step_id), esc(s.tool_id || "—"), BADGE(s.status)],
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
  // persist any unsaved inspector edits when leaving the editor page
  const { route: currRoute, id: currId } = parseHash();
  if (currRoute === "playbooks" && currId && graphSel) {
    const s = stepById(graphSel);
    if (s) applyTabFields(s);
  }
  const { route: name, id } = parseHash();
  $$("#mainNav .nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.route === name));
  setPageMeta({ crumb: ROUTES[name].crumb, title: ROUTES[name].title });
  await render();
  try {
    if (name === "executions" && id) await pageExecutionDetail(decodeURIComponent(id));
    else if (name === "connections" && id) await pageConnectionDetail(decodeURIComponent(id));
    else if (name === "agents" && id) await pageAgentDetail(decodeURIComponent(id));
    else if (name === "playbooks" && id) await pagePlaybookEditor(decodeURIComponent(id));
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
