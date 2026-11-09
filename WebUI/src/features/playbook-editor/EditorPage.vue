<script setup lang="ts">
/*
 * EditorPage — main playbook editor container.
 * Composes: EditorToolbar, NodePalette, GraphCanvas, NodeInspector, DslEditor.
 * The store is the single source of truth; all sub-components read from it.
 */
import { onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { usePlaybookEditorStore } from "@/stores/playbook-editor";

import EditorToolbar from "./EditorToolbar.vue";
import NodePalette from "./NodePalette.vue";
import GraphCanvas from "./GraphCanvas.vue";
import NodeInspector from "./NodeInspector.vue";
import DslEditor from "./DslEditor.vue";

const route = useRoute();
const store = usePlaybookEditorStore();

const editorId = route.params.id as string;

onMounted(() => {
  void store.loadPlaybook(editorId);
  void store.refreshTools();
});

watch(
  () => route.params.id,
  (id) => {
    if (id && id !== editorId) {
      void store.loadPlaybook(id as string);
    }
  },
  { immediate: false },
);
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
      <EditorToolbar />
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
          <button class="btn" id="addToolBtn" @click="store.addToolStep" title="Add a registered-tool step">＋ Tool</button>
          <button class="btn" id="addShellBtn" @click="store.addShellStep" title="Add a shell-command node">＋ Shell</button>
          <button class="btn ghost" id="addScopeBtn" @click="store.addScopeStep" title="Add a scope-check step">Scope</button>
          <button class="btn ghost" id="addFindingBtn" @click="store.addFindingStep" title="Add a finding-correlation step">Correlate</button>
          <button class="btn ghost" id="addReportBtn" @click="store.addReportStep" title="Add an assessment-report step">Report</button>
          <button class="btn ghost" id="addCustomBtn" @click="store.addCustomStep" title="Add a custom stage step">Custom</button>
          <span class="tool-sep"></span>
          <button class="btn icon" id="resetLayoutBtn" @click="store.relayout" title="Auto-layout">⇋</button>
          <button class="btn icon" id="zoomOut" @click="graph.zoomOut" title="Zoom out">−</button>
          <button class="btn icon" id="zoomReset" @click="graph.fitToScreen" title="Fit to screen">⛶</button>
          <button class="btn icon" id="zoomIn" @click="graph.zoomIn" title="Zoom in">＋</button>
          <span class="tool-sep"></span>
          <button class="btn icon" id="inspectorToggle" :title="store.inspectorOpen ? 'Hide inspector' : 'Show inspector'" @click="store.toggleInspector">{{ store.inspectorOpen ? '◀' : '▶' }}</button>
          <button class="btn icon" id="delSelBtn" :disabled="!store.selectedNodeId" @click="store.removeSelectedNode" title="Delete selected node">✕</button>
          <span class="tool-sep"></span>
          <span class="count" id="graphCount">{{ store.nodes.length }} step{{ store.nodes.length === 1 ? "" : "s" }}</span>
        </div>
        <GraphCanvas ref="graph" />
      </div>

      <div class="ins-resizer" id="insResizer" title="Drag to resize the inspector"></div>
      <NodeInspector />
    </div>

    <DslEditor v-if="store.view === 'dsl'" />
  </section>
</template>

<style scoped>
#editorShell { height: calc(100vh - var(--topbar-h, 60px)); }
</style>
