<template>
  <div class="page">
    <div class="pagehead">
      <div>
        <div class="eyebrow">OVERVIEW</div>
        <h1>Workspace overview</h1>
        <p class="subtitle">Everything below is read live from the database.</p>
      </div>
    </div>
    <div class="kpi-grid">
      <div class="kpi" v-for="k in kpis" :key="k.label">
        <div class="kpi-label">{{ k.label }}</div>
        <div class="kpi-value">{{ k.value }}</div>
        <div class="kpi-sub">{{ k.sub }}</div>
      </div>
    </div>
    <div class="two-col" style="margin-top:20px">
      <div class="panel" style="min-height:220px">
        <div class="panel-head"><span>Recent executions</span></div>
        <div style="padding:8px">{{ recentExecutionsHtml }}</div>
      </div>
      <div class="panel" style="min-height:220px">
        <div class="panel-head"><span>Latest findings</span></div>
        <div style="padding:8px">{{ recentFindingsHtml }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useNotifications } from "@/stores/notifications";
import { apiRequest } from "@/api/client";

const notify = useNotifications();
const kpis = ref<any[]>([]);
const recentExecutionsHtml = ref("");
const recentFindingsHtml = ref("");

function esc(v: any) { return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

async function load() {
  try {
    const o = await apiRequest("/overview");
    const execState = o.executions?.by_status || {};
    const fnd = o.findings?.by_severity || {};
    const runState = ["running","completed","failed","cancelled"]
      .filter((s) => execState[s]).map((s) => `${s}: ${execState[s]}`).join(" · ") || "no runs yet";
    kpis.value = [
      { label: "Playbooks", value: o.playbooks?.total ?? 0, sub: Object.entries(o.playbooks?.by_status || {}).map(([k2,v]: any) => `${k2}: ${v}`).join(" · ") },
      { label: "Executions", value: o.executions?.total ?? 0, sub: runState },
      { label: "Tools", value: o.tools?.total ?? 0, sub: Object.entries(o.tools?.by_visibility || {}).map(([k2,v]: any) => `${k2}: ${v}`).join(" · ") },
      { label: "Findings", value: o.findings?.total ?? 0, sub: Object.entries(fnd).map(([k2,v]: any) => `${k2}: ${v}`).join(" · ") },
      { label: "MCP connections", value: o.connections?.total ?? 0, sub: `healthy: ${o.connections?.healthy ?? 0}` },
      { label: "Agent profiles", value: o.agents?.total ?? 0, sub: "" },
    ];
    const rows = (o.recent_executions || []).map((e: any) => ({
      cells: [esc(e.execution_id), esc(e.playbook_id || "—"), esc(String(e.status)), esc((e.completed_at || "").slice(0, 19))],
      menu: `<a href="#/executions/${esc(e.execution_id)}">view</a>`,
    }));
    recentExecutionsHtml.value = `<div style="padding:6px">${table(["Execution","Playbook","Status","Completed"], rows, "No executions yet.")}</div>`;
    const frows = (o.recent_findings || []).map((f: any) => ({
      cells: [esc(f.port_state || f.status || "—"), esc(f.tool), esc(f.severity || f.validation_status || "—"), esc(f.test_name || f.checkname || f.validation_status || "—")],
    }));
    recentFindingsHtml.value = `<div style="padding:6px">${table(["Target hint","Tool","Severity","Test"], frows, "No findings yet.")}</div>`;
  } catch (err: any) { notify.toast(`Failed to load overview: ${err?.message ?? err}`, "error"); }
}

function table(headers: string[], rows: any[], emptyText = "Nothing here yet.") {
  if (!rows.length) return `<div class="panel table-panel"><p class="empty">${esc(emptyText)}</p></div>`;
  const cols = headers.length;
  return `<div class="panel table-panel" style="overflow:auto">
    <div class="table-head" style="grid-template-columns:repeat(${cols},minmax(0,1fr)) auto">${headers.map((h) => `<span>${esc(h)}</span>`).join("")}<span></span></div>
    ${rows.map((r: any) => `<div class="table-row" style="grid-template-columns:repeat(${cols},minmax(0,1fr)) auto">${r.cells.map((c: any) => `<span>${c}</span>`).join("")}<span>${r.menu || ""}</span></div>`).join("")}
  </div>`;
}

onMounted(load);
</script>
