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
  setPageMeta({
    crumb: "Playbook Studio", subtitle: "Plan & edit playbooks",
    actions: [{ label: "New", fn: newPlaybook }, { label: "Refresh", fn: refreshPlaybooks }],
  });
  $("#pageHeadInfo").innerHTML = `
    <div class="eyebrow">PLAYBOOK STUDIO</div><h1>Playbooks</h1>
    <div class="subtitle">Select a playbook to edit its definition. Save drafts, publish versions, roll back or export.</div>`;
  $("#pageHeadActions").innerHTML = headActionsHtml([
    { id: "refreshBtn", label: "↻ Refresh" },
    { id: "newPlaybookBtn", label: "＋ New", cls: "primary" },
  ]);
  $("#pageBody").innerHTML = `
  <section class="studio-grid">
    <aside class="playbook-list" id="playbookList">Loading…</aside>
    <section class="editor">
      <div class="panel-head"><span id="editorTitle">Select a playbook</span><span id="editorStatus"></span></div>
      <textarea class="code-area" id="dslCode" spellcheck="false" placeholder="Playbook definition (JSON as returned by /definition)…"></textarea>
      <div class="editor-actions">
        <button class="btn" id="validateBtn">✓ Validate</button>
        <button class="btn" id="saveDraftBtn">Save draft</button>
        <button class="btn primary" id="publishBtn">Publish</button>
        <span style="flex:1"></span>
        <button class="btn ghost" id="versionsBtn">Versions / rollback</button>
        <button class="btn ghost" id="exportBtn">↗ Export</button>
        <button class="btn ghost" id="importBtn">↙ Import</button>
        <button class="btn danger" id="deleteBtn">Delete</button>
      </div>
      <pre class="result" id="editorResult" hidden></pre>
    </section>
  </section>`;
  $("#refreshBtn").addEventListener("click", () => refreshPlaybooks());
  $("#newPlaybookBtn").addEventListener("click", newPlaybook);
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
  $("#versionsBtn").addEventListener("click", showVersions);
  $("#exportBtn").addEventListener("click", exportPlaybook);
  $("#importBtn").addEventListener("click", importPlaybook);
  $("#deleteBtn").addEventListener("click", deletePlaybook);
  await refreshPlaybooks();
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

async function pageExecutions() {
  setPageMeta({
    crumb: "Executions", title: "Executions", subtitle: "Live workflow runs",
    actions: [{ label: "Refresh", fn: () => refreshExecutions($("#execFilter")?.value || "all") }],
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
  const d = await api("/tools?limit=500");
  toolsCache = d.tools || [];
  renderTools();
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
    })), "No connections yet. Add one to import external MCP tools.")}`;
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
