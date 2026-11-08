<script setup lang="ts">
/*
 * GraphCanvas — central Vue Flow canvas.
 * Renders nodes/edges from the store, handles dragging, connecting,
 * edge double-click delete, palette drag-and-drop, fit-to-screen and zoom.
 */
import { ref, onMounted, onUnmounted, watch } from "vue";
import {
  useVueFlow,
  Background,
  Controls,
  MiniMap,
  type VueFlowNode,
  type VueFlowEdge,
} from "@vue-flow/core";
import { usePlaybookEditorStore } from "@/stores/playbook-editor";
import { useGraphKeyboard } from "@/features/playbook-editor/composables/useGraphKeyboard";
import { useNotificationsStore } from "@/stores/notifications";

import ToolNode from "./nodes/ToolNode.vue";
import ShellNode from "./nodes/ShellNode.vue";
import ScopeNode from "./nodes/ScopeNode.vue";
import FindingNode from "./nodes/FindingNode.vue";
import AssessmentNode from "./nodes/AssessmentNode.vue";
import CustomNode from "./nodes/CustomNode.vue";

const store = usePlaybookEditorStore();
const notifications = useNotificationsStore();

const nodeTypes = {
  tool: ToolNode,
  shell: ShellNode,
  scope_check: ScopeNode,
  finding_correlation: FindingNode,
  assessment_report: AssessmentNode,
  custom: CustomNode,
};

const vf = useVueFlow();
const { fitView, zoomIn, zoomOut, setZoom, getZoom, toSnapPoint, setNodes, setEdges } = vf;

const dragEndTimer = ref<number | null>(null);

function toastError(msg: string) { notifications.notify(msg, "error"); }
function toastInfo(msg: string) { notifications.notify(msg, "info"); }

/* Keyboard shortcuts: undo/redo/delete. */
const keyboard = useGraphKeyboard({
  onUndo: () => store.undo(),
  onRedo: () => store.redo(),
  onDelete: () => store.removeSelectedNode(),
  isEditing: () => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return false;
    const tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
  },
});
onMounted(() => keyboard.start());
onUnmounted(() => keyboard.stop());

/* Keep Vue Flow in sync with the store's nodes/edges. */
watch(
  () => store.nodes,
  (ns) => setNodes(ns),
  { deep: true },
);
watch(
  () => store.edges,
  (es) => setEdges(es),
  { deep: true },
);

/* Exposed for the toolbar (ref="graph"). */
const fitToScreen = () => { fitView({ pad: 0.1, maxZoom: 1.25, minZoom: 0.25 }); };
const setZoomLevel = (z: number) => setZoom(z);

/* ── dragging: keep graphPos in sync while dragging, snapshot on drag end ── */
function onNodesChange(changes: any[]) {
  for (const change of changes) {
    if (change.type === "position" && change.position) {
      store.setNodePosition(change.id, { x: change.position.x, y: change.position.y });
    }
  }
}

function scheduleDragEndSnapshot() {
  if (dragEndTimer.value) clearTimeout(dragEndTimer.value);
  dragEndTimer.value = window.setTimeout(() => {
    store.pushHistory();
    dragEndTimer.value = null;
  }, 120);
}

function onNodeDragEnd(event: any) {
  const node = event?.node ?? event;
  if (node?.id && node.position) {
    store.setNodePosition(node.id, { x: node.position.x, y: node.position.y });
  }
  scheduleDragEndSnapshot();
}

function onNodeClick(event: any) {
  const node = event?.node ?? event;
  if (node?.id) store.setSelection(node.id);
}

function onPaneClick() {
  store.setSelection(null);
}

/* ── connections ── */
function onConnect(params: any) {
  const source = params?.source ?? params?.sourceHandle;
  const target = params?.target ?? params?.targetHandle;
  if (!source || !target || source === target) return;
  const result = store.addEdge(source, target);
  if (!result.ok) toastError(result.message);
}

function onEdgeDblClick(event: any) {
  const edge = event?.edge ?? event;
  if (edge?.source && edge?.target) store.removeEdge(edge.source, edge.target);
}

function onEdgesChange(changes: any[]) {
  for (const change of changes) {
    if (change.type === "remove" && change.id) {
      /* edge id is "e:source->target" */
      const m = /^e:(.+)→?->(.+)$|^e:(.+) -> (.+)$/.exec(change.id);
      if (m) {
        const src = m[1] ?? m[3];
        const tgt = m[2] ?? m[4];
        if (src && tgt) store.removeEdge(src, tgt);
      }
    }
  }
}

/* ── palette drag-and-drop ── */
let draggedType: string | null = null;
function onDragStart(event: DragEvent, type: string) {
  draggedType = type;
  event.dataTransfer?.setData("type", type);
  event.dataTransfer?.setData("text/plain", type);
  setTimeout(() => { draggedType = null; }, 0);
}
function onDragEnd() { draggedType = null; }
function onPaneDrop(event: DragEvent) {
  const type = event.dataTransfer?.getData("type") || draggedType;
  if (!type) return;
  const point = toSnapPoint([event.clientX, event.clientY]);
  switch (type) {
    case "tool": store.addToolStep(undefined, { x: point.x, y: point.y }); break;
    case "shell": store.addShellStep({ x: point.x, y: point.y }); break;
    case "scope_check": store.addScopeStep({ x: point.x, y: point.y }); break;
    case "finding_correlation": store.addFindingStep({ x: point.x, y: point.y }); break;
    case "assessment_report": store.addReportStep({ x: point.x, y: point.y }); break;
    case "custom": store.addCustomStep({ x: point.x, y: point.y }); break;
  }
  toastInfo(`Added ${type} step`);
}

/* live execution state from the store is reflected via node __status (computed). */
</script>

<template>
  <vue-flow
    ref="flow"
    :node-types="nodeTypes"
    :nodes="store.nodes"
    :edges="store.edges"
    fit-on-init
    :fit-view-on-init="true"
    @init="onInit"
    @nodes-change="onNodesChange"
    @edges-change="onEdgesChange"
    @connect="onConnect"
    @edge-dblclick="onEdgeDblClick"
    @node-click="onNodeClick"
    @pane-click="onPaneClick"
    @node-drag-end="onNodeDragEnd"
    @pane-drop="onPaneDrop"
    @dragover.prevent
  >
    <Background gap={16} offset={0} />
    <Controls />
    <MiniMap />
  </vue-flow>
</template>

<script lang="ts">
import { defineComponent } from "vue";
export default defineComponent({
  expose: { fitToScreen, setZoomLevel, zoomIn, zoomOut, getZoom },
});
</script>

<style scoped>
/deep/ .vue-flow { background: #0b1016; }
</style>
