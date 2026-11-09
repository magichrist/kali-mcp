<script setup lang="ts">
/*
 * EditorPage — main playbook editor container.
 * Composes: EditorToolbar, NodePalette, GraphCanvas, NodeInspector, DslEditor, RunModal.
 * The store is the single source of truth; all sub-components read from it.
 * All editor actions (validate, save, publish, import, export, versions,
 * rollback, delete, run test) are wired here to the API / store.
 */
import { onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { usePlaybookEditorStore, type PlaybookEditorStore } from "@/stores/playbook-editor";
import { useNotificationsStore } from "@/stores/notifications";
import {
  validateDefinition,
  updatePlaybookDefinition,
  publishPlaybook,
  importPlaybook,
  fetchPlaybookDefinition,
  deletePlaybook,
  startExecution,
  type PlaybookDefinition,
  type StartExecutionResponse,
} from "@/api/client";
import BaseBadge from "@/components/common/BaseBadge.vue";
import { badgeVariant } from "@/components/common/badgeVariant";
import { playbookApi } from "@/api/playbooks";
import type { Version } from "@/api/types";

import EditorToolbar from "./EditorToolbar.vue";
import NodePalette from "./NodePalette.vue";
import GraphCanvas from "./GraphCanvas.vue";
import NodeInspector from "./NodeInspector.vue";
import DslEditor from "./DslEditor.vue";
import ValidationPanel from "./ValidationPanel.vue";
import RunModal from "./RunModal.vue";
import ConfirmDialog from "@/components/common/ConfirmDialog.vue";

type GraphHandle = {
  fitToScreen: () => void;
  setZoomLevel: (z: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  getZoom: () => number;
};

const route = useRoute();
const router = useRouter();
const store = usePlaybookEditorStore() as PlaybookEditorStore;
const notifications = useNotificationsStore();

const editorId = route.params.id as string;

const graph = ref<GraphHandle | null>(null);

/* ──────────────────── action state ──────────────────── */
const validationFindings = ref<any[]>([]);
const validating = ref(false);
const showValidation = ref(false);

const versions = ref<Version[]>([]);
const showVersions = ref(false);

const rollbackConfirm = ref(false);
const rollbackTarget = ref<string | null>(null);

const deleteConfirm = ref(false);

const importModal = ref(false);
const importFile = ref<File | null>(null);
const importing = ref(false);

const runModal = ref(false);

/* ──────────────────── lifecycle ──────────────────── */
onMounted(() => {
  void store.loadPlaybook(editorId);
  void store.refreshTools();
});

watch(
  () => route.params.id,
  (id) => {
    /* Stop live polling before switching playbooks / reloading. */
    store.stopPolling();
    if (id && id !== editorId) {
      void store.loadPlaybook(id as string);
    }
  },
  { immediate: false },
);

onUnmounted(() => {
  store.stopPolling();
});

/* ──────────────────── validate ──────────────────── */
async function handleValidate(): Promise<void> {
  validating.value = true;
  try {
    const res = await validateDefinition(editorId, store.definition);
    const details = (res as any)?.details ?? [];
    validationFindings.value = Array.isArray(details) ? details : [];
    showValidation.value = true;
    const valid = !!(res as any)?.valid;
    notifications.notify(valid ? "Definition valid" : "Validation failed", valid ? "success" : "error");
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Validation failed", "error");
  } finally {
    validating.value = false;
  }
}

/* ──────────────────── save draft ──────────────────── */
async function handleSaveDraft(): Promise<void> {
  try {
    await store.saveDraft();
    notifications.notify("Draft saved", "success");
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Save failed", "error");
  }
}

/* ──────────────────── publish ──────────────────── */
async function handlePublish(): Promise<void> {
  try {
    await store.publish();
    notifications.notify("Published", "success");
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Publish failed", "error");
  }
}

/* ──────────────────── import / export ──────────────────── */
function handleImportFile(e: Event): void {
  const f = (e.target as HTMLInputElement).files?.[0] || null;
  importFile.value = f;
}

async function handleImport(): Promise<void> {
  if (!importFile.value) return;
  importing.value = true;
  try {
    const text = await importFile.value.text();
    const pkg = JSON.parse(text);
    await importPlaybook(pkg);
    notifications.notify("Playbook imported", "success");
    importModal.value = false;
    importFile.value = null;
    await store.loadPlaybook(editorId);
  } catch (err) {
    importing.value = false;
    notifications.notify(err instanceof Error ? err.message : "Import failed", "error");
  }
}

async function handleExport(): Promise<void> {
  try {
    const res = await fetchPlaybookDefinition(editorId);
    const def = (res as any)?.definition ?? res;
    const blob = new Blob([JSON.stringify(def, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(store.playbook as any)?.name || editorId}-definition.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    notifications.notify("Exported", "success");
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Export failed", "error");
  }
}

/* ──────────────────── versions / rollback ──────────────────── */
async function handleVersions(): Promise<void> {
  try {
    const res = await playbookApi.listVersions(editorId);
    versions.value = (res as any)?.versions ?? [];
    showVersions.value = true;
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Failed to load versions", "error");
  }
}

function openRollback(versionId: string | number): void {
  rollbackTarget.value = String(versionId);
  rollbackConfirm.value = true;
}

async function confirmRollback(): Promise<void> {
  if (!rollbackTarget.value) return;
  try {
    await playbookApi.rollback(editorId, { version_id: rollbackTarget.value });
    notifications.notify("Rolled back", "success");
    rollbackConfirm.value = false;
    rollbackTarget.value = null;
    await store.loadPlaybook(editorId);
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Rollback failed", "error");
  }
}

/* ──────────────────── delete ──────────────────── */
async function confirmDelete(): Promise<void> {
  try {
    await deletePlaybook(editorId);
    notifications.notify("Playbook deleted", "success");
    deleteConfirm.value = false;
    void router.push({ name: "playbooks" });
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Delete failed", "error");
  }
}

/* ──────────────────── modal helpers ──────────────────── */
function openRunModal(): void { runModal.value = true; }
function openImportModal(): void { importModal.value = true; }
function closeImport(): void { importModal.value = false; }
function openDeleteConfirm(): void { deleteConfirm.value = true; }
function closeDelete(): void { deleteConfirm.value = false; }
function closeRollback(): void { rollbackTarget.value = null; rollbackConfirm.value = false; }
function closeVersions(): void { showVersions.value = false; }

/* ──────────────────── run test ──────────────────── */
async function handleRunStart(payload: { inputs: Record<string, unknown>; debug: boolean }): Promise<void> {
  runModal.value = false;
  try {
    const res = await startExecution({
      playbook_id: editorId,
      inputs: payload.inputs,
      debug: payload.debug,
      trigger: "studio",
    }) as StartExecutionResponse;
    const executionId = res.execution?.execution_id ?? res.execution_id;
    if (executionId) {
      await store.startPolling(executionId);
      notifications.notify("Run started — live status polling", "success");
    } else {
      notifications.notify("Run started, but no execution id was returned", "warn");
    }
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Run failed", "error");
  }
}

</script>

<template>
  <section class="editor-shell" id="editorShell">
    <header class="pb-head">
      <div class="pb-head-l">
        <a class="btn ghost back-btn" :href="'#/playbooks'" title="Back to playbooks">↩ Playbooks</a>
        <div class="pb-title">
          <h2 id="pbName">{{ store.playbook?.name || store.playbookId }}</h2>
          <div class="pb-meta" id="pbMeta">
            <span class="badge">{{ store.playbook?.status || "draft" }}</span>
            <span class="version">v {{ store.playbook?.current_version_id || "—" }}</span>
            <span class="dim mono">{{ store.playbookId }}</span>
          </div>
        </div>
      </div>
      <EditorToolbar
        :current-view="store.view"
        @validate="handleValidate"
        @save-draft="handleSaveDraft"
        @publish="handlePublish"
        @run-test="openRunModal"
        @import="openImportModal"
        @export="handleExport"
        @versions="handleVersions"
        @rollback="() => { /* handled via versions modal */ }"
        @delete="openDeleteConfirm"
      />
    </header>

    <div class="pb-bar">
      <div class="segmented" id="builderSwitch">
        <button
          data-view="graph"
          :class="{ active: store.view === 'graph' }"
          @click="store.setView('graph')"
        >Graph</button>
        <button
          data-view="dsl"
          :class="{ active: store.view === 'dsl' }"
          @click="store.setView('dsl')"
        >DSL</button>
      </div>
      <span class="pb-hint dim" id="pbHint">
        {{ store.view === "dsl" && store.dslError ? "Invalid JSON — " + store.dslError.message : "" }}
      </span>
    </div>

    <div class="editor-grid" id="editorGrid" :class="{ 'inspector-hidden': !store.inspectorOpen }">
      <NodePalette />

      <div class="canvas-col">
        <div class="graph-toolbar" id="graphToolbar">
          <button class="btn icon" id="undoBtn" :disabled="!store.canUndo" @click="store.undo" title="Undo">↶</button>
          <button class="btn icon" id="redoBtn" :disabled="!store.canRedo" @click="store.redo" title="Redo">↷</button>
          <span class="tool-sep"></span>
          <button class="btn" id="addToolBtn" @click="() => store.addToolStep()" title="Add a registered-tool step">＋ Tool</button>
          <button class="btn" id="addShellBtn" @click="() => store.addShellStep()" title="Add a shell-command node">＋ Shell</button>
          <button class="btn ghost" id="addScopeBtn" @click="() => store.addScopeStep()" title="Add a scope-check step">Scope</button>
          <button class="btn ghost" id="addFindingBtn" @click="() => store.addFindingStep()" title="Add a finding-correlation step">Correlate</button>
          <button class="btn ghost" id="addReportBtn" @click="() => store.addReportStep()" title="Add an assessment-report step">Report</button>
          <button class="btn ghost" id="addCustomBtn" @click="() => store.addCustomStep()" title="Add a custom stage step">Custom</button>
          <span class="tool-sep"></span>
          <button class="btn icon" id="resetLayoutBtn" @click="store.relayout" title="Auto-layout">⇋</button>
          <button class="btn icon" id="zoomOut" @click="() => graph?.zoomOut()" title="Zoom out">−</button>
          <button class="btn icon" id="zoomReset" @click="() => graph?.fitToScreen()" title="Fit to screen">⛶</button>
          <button class="btn icon" id="zoomIn" @click="() => graph?.zoomIn()" title="Zoom in">＋</button>
          <span class="tool-sep"></span>
          <button class="btn icon" id="inspectorToggle" :title="store.inspectorOpen ? 'Hide inspector' : 'Show inspector'" @click="store.toggleInspector">{{ store.inspectorOpen ? '◀' : '▶' }}</button>
          <button class="btn icon" id="delSelBtn" :disabled="!store.selectedNodeId" @click="store.removeSelectedNode" title="Delete selected node">✕</button>
          <span class="tool-sep"></span>
          <span class="count" id="graphCount">{{ store.nodes.length }} step{{ store.nodes.length === 1 ? "" : "s" }}</span>
        </div>
        <GraphCanvas ref="graph" />
      </div>

      <div class="ins-resizer" id="insResizer" title="Drag to resize the inspector"></div>
      <NodeInspector :node="store.selectedStep" :definition="store.definition" :run-status="store.runStatus" :step-results="store.stepResults" />
    </div>

    <!-- Validation findings panel -->
    <div v-if="showValidation" class="validation-section">
      <ValidationPanel :findings="validationFindings" />
    </div>

    <DslEditor v-if="store.view === 'dsl'" :text="store.rawDsl" :valid="!store.dslError" :error="store.dslError?.message ?? null" :definition="store.definition" />
  </section>

  <!-- Run modal -->
  <RunModal
    v-model:show="runModal"
    :playbook-id="editorId"
    :definition="store.definition"
    @run-start="handleRunStart"
  />

  <!-- Confirm dialogs (delete / rollback) -->
  <ConfirmDialog
    v-if="deleteConfirm"
    v-model:open="deleteConfirm"
    title="Delete playbook"
    :message="`Delete playbook ${editorId}? This cannot be undone.`"
    confirmLabel="Delete"
    cancelLabel="Cancel"
    dangerous
    @confirm="confirmDelete"
    @cancel="closeDelete"
  />
  <ConfirmDialog
    v-if="rollbackConfirm"
    v-model:open="rollbackConfirm"
    title="Rollback version"
    :message="rollbackTarget ? `Rollback to version ${rollbackTarget}? This replaces the current draft.` : 'Rollback version?'"
    confirmLabel="Rollback"
    cancelLabel="Cancel"
    dangerous
    @confirm="confirmRollback"
    @cancel="closeRollback"
  />

  <!-- Import modal -->
  <div v-if="importModal" class="modal-backdrop" @click.self="closeImport">
    <div class="modal" @click.stop>
      <div class="modal-head"><h3>Import playbook</h3></div>
      <div class="modal-body">
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:6px">JSON package file</label>
        <input type="file" accept=".json" @change="handleImportFile" class="select" />
        <p v-if="importFile" class="dim" style="font-size:12px; margin-top:6px">{{ importFile.name }}</p>
      </div>
      <div class="modal-actions">
        <button class="btn" @click="closeImport">Cancel</button>
        <button class="btn primary" :disabled="importing || !importFile" @click="handleImport">{{ importing ? "Importing…" : "Import" }}</button>
      </div>
    </div>
  </div>

  <!-- Versions modal -->
  <div v-if="showVersions" class="modal-backdrop" @click.self="closeVersions">
    <div class="modal">
      <div class="modal-head"><h3>Versions</h3></div>
      <div class="modal-body">
        <div v-if="versions.length === 0" class="empty">No versions found.</div>
        <div v-else class="versions-list">
          <div v-for="v in versions" :key="v.version_id" class="version-row">
            <div class="version-info">
              <span class="mono">{{ v.version }}</span>
              <span v-if="v.created_at" class="dim">{{ v.created_at }}</span>
            </div>
            <button class="btn" @click="openRollback(v.version_id)">Rollback</button>
          </div>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn" @click="closeVersions">Close</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
#editorShell { height: calc(100vh - var(--topbar-h, 60px)); }
.validation-section { padding: 12px 16px; border-top: 1px solid var(--line); background: var(--panel2); }
.modal-backdrop { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.55); z-index: 50; }
.modal { background: #1e1e1e; border: 1px solid #3a3a3a; border-radius: var(--radius); width: min(560px, 92vw); max-height: 85vh; overflow: auto; box-shadow: var(--shadow); }
.modal-head { padding: 16px 18px 8px; border-bottom: 1px solid #2a2a2a; }
.modal-head h3 { margin: 0 0 6px; font-size: 17px; color: var(--text); }
.modal-body { padding: 14px 18px; display: flex; flex-direction: column; gap: 12px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid #2a2a2a; }
.empty { color: var(--dim); font-size: 12.5px; }
.versions-list { display: flex; flex-direction: column; gap: 8px; }
.version-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); }
.version-info { display: flex; flex-direction: column; gap: 2px; }
.version-info .mono { font-size: 13px; color: var(--text); }
.version-info .dim { font-size: 11px; }
</style>
