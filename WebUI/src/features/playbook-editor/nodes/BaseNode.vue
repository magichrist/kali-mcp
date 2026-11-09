<script setup lang="ts">
import { Handle } from "@vue-flow/core";
import type { StepType } from "@/features/playbook-editor/types/graph";
import { TYPE_ICONS } from "@/features/playbook-editor/types/graph";

const props = defineProps<{
  id: string;
  data: { step: any; __status?: string };
  selected?: boolean;
}>();
const emit = defineEmits<{ (e: "click", id: string): void }>();
const step = props.data.step;
const type: StepType = step?.type || "tool";
const icon = TYPE_ICONS[type] ?? TYPE_ICONS.tool;
const nodeStatus = props.data.__status || "";
const running = nodeStatus === "running" || nodeStatus === "pending";
function handleClick(e: MouseEvent) { e.stopPropagation(); emit("click", props.id); }
</script>

<template>
  <div class="node" :class="{ 'node-shell': type === 'shell', selected, running }" :style="{ width: '280px', minHeight: '140px' }" @click="handleClick">
    <div class="node-top">
      <div class="node-icon" :class="icon.cls">{{ icon.glyph }}</div>
      <div class="node-names">
        <div class="node-title">{{ step.id }}</div>
        <div class="node-kind">{{ type }} <span v-if="step.tool" class="mono">· {{ step.tool }}</span></div>
      </div>
      <span class="node-status" :class="nodeStatus" :title="`run status: ${nodeStatus || '—'}`"></span>
    </div>
    <div class="node-body"><slot></slot></div>
    <div class="node-foot">
      <span class="chip">{{ (step.depends_on || []).length }} in</span>
      <span v-if="step.inputs && Object.keys(step.inputs).length" class="chip">{{ Object.keys(step.inputs).length }} inputs</span>
      <span v-if="step.filter && step.filter.type !== 'none'" class="chip accent">⌕ out</span>
      <span v-if="step.checkpoint" class="chip ck">checkpoint</span>
    </div>
    <span class="port left" title="input port"></span>
    <span class="port right" title="drag or click to connect"></span>
    <Handle type="target" class="handle-left" />
    <Handle type="source" class="handle-right" />
  </div>
</template>

<style scoped>
.node { position: absolute; width: 280px; min-height: 140px; z-index: 2; background: var(--panel); border: 1px solid var(--line2); border-radius: 14px; box-shadow: var(--shadow-soft); padding: 12px 14px 10px; cursor: grab; user-select: none; transition: border-color 0.12s, box-shadow 0.12s, z-index 0.12s; display: flex; flex-direction: column; }
.node * { user-select: none; }
.node:hover { border-color: #46586e; }
.node.selected { border-color: var(--green-strong); box-shadow: 0 0 0 1px var(--green2), var(--shadow-soft); z-index: 50; }
.node.running { border-color: var(--amber); box-shadow: 0 0 0 1px var(--amber2), 0 0 14px rgba(212, 141, 36, 0.35); }
.node.running .node-body { animation: nodePulse 1.2s ease-in-out infinite; }
.node-top { display: flex; align-items: flex-start; gap: 10px; }
.node-icon { width: 34px; height: 34px; flex: none; border-radius: 9px; display: grid; place-items: center; font-size: 15px; border: 1px solid var(--line2); background: #0d1219; }
.node-icon.scan { color: var(--amber); border-color: #5d4a26; background: var(--amber2); }
.node-icon.cmd { color: var(--red); border-color: #59303a; background: var(--red2); }
.node-icon.dns { color: var(--green); border-color: #2c5743; background: var(--green2); }
.node-icon.web { color: var(--blue); border-color: #2b4a6e; background: var(--blue2); }
.node-icon.out { color: var(--cyan); border-color: #2b5a5e; background: #122e31; }
.node-icon.mod { color: var(--purple); border-color: #4a3a68; background: #241d38; }
.node-names { min-width: 0; flex: 1; }
.node-title { font-size: 15px; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-kind { color: var(--dim); font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.node-status { width: 11px; height: 11px; flex: none; margin-top: 4px; border-radius: 50%; background: var(--line2); }
.node-status.ok { background: var(--green-strong); box-shadow: 0 0 8px rgba(53, 179, 122, 0.7); }
.node-status.failed { background: var(--red); box-shadow: 0 0 8px rgba(241, 142, 142, 0.7); }
.node-status.run, .node-status.pending { background: var(--amber); animation: pulse 1.2s ease-in-out infinite; }
.node-status.completed { background: var(--green-strong); }
.node-body { margin: 10px 0 8px; display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--muted); min-width: 0; }
.node-body * { min-width: 0; }
.node-foot { display: flex; flex-wrap: wrap; gap: 6px; }
.node-foot .chip { height: 22px; font-size: 11.5px; padding: 0 8px; }
.port { position: absolute; top: 50%; width: 15px; height: 15px; border-radius: 50%; background: var(--panel3); border: 2px solid #4b6076; transform: translateY(-50%); cursor: crosshair; z-index: 4; transition: border-color 0.12s, background 0.12s; }
.port.left { left: -8px; }
.port.right { right: -8px; }
.port:hover { border-color: var(--green); background: var(--green2); }
.handle-left, .handle-right { position: absolute; top: 50%; width: 15px; height: 15px; transform: translateY(-50%); z-index: 5; }
.handle-left { left: -8px; }
.handle-right { right: -8px; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
@keyframes nodePulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.85; } }
