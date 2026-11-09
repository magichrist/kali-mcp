<template>
  <div class="node-palette">
    <div class="palette-head">
      <span class="palette-title">Add step</span>
      <button class="btn ghost icon" @click="toggleCollapse" :title="collapsed ? 'Expand palette' : 'Collapse palette'" :aria-label="collapsed ? 'Expand palette' : 'Collapse palette'">{{ collapsed ? '▶' : '▼' }}</button>
    </div>
    <div v-if="!collapsed" class="palette-body">
      <button
        v-for="type in stepTypes"
        :key="type"
        class="palette-item"
        @click="$emit('add', type)"
        :title="type"
      >
        <span class="palette-icon">{{ iconFor(type).glyph }}</span>
        <span class="palette-label">{{ labelFor(type) }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { STEP_TYPES, TYPE_ICONS } from "@/features/playbook-editor/types/graph";

const props = defineProps<{
  collapsed?: boolean;
}>();

const emit = defineEmits<{
  (e: "add", type: string): void;
}>();

const localCollapsed = ref(props.collapsed ?? false);

function toggleCollapse() { localCollapsed.value = !localCollapsed.value; }

const collapsed = computed(() => props.collapsed ?? localCollapsed.value);

const stepTypes = STEP_TYPES;

function iconFor(type: string) { return (TYPE_ICONS as any)[type] || { glyph: "◈" }; }
function labelFor(type: string) {
  const labels: Record<string, string> = {
    tool: "Tool", shell: "Shell", scope_check: "Scope Check",
    finding_correlation: "Finding Correlation", assessment_report: "Assessment Report", custom: "Custom",
  };
  return labels[type] || type;
}
</script>

<style scoped>
.node-palette { display: flex; flex-direction: column; gap: 0; border-right: 1px solid var(--line); background: var(--panel2); flex-shrink: 0; }
.palette-head { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border-bottom: 1px solid var(--line); background: #0d1117; flex-shrink: 0; }
.palette-title { font-size: 11.5px; font-weight: 600; color: var(--muted); }
.palette-body { display: flex; flex-direction: column; gap: 2px; padding: 6px; max-height: 400px; overflow-y: auto; }
.palette-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 0; background: transparent; border-radius: 8px; color: var(--muted); font-size: 13px; cursor: pointer; text-align: left; width: 100%; }
.palette-item:hover { background: var(--panel3); color: var(--text); }
.palette-icon { width: 20px; text-align: center; font-size: 15px; }
.palette-label { flex: 1; }
.btn.icon { width: 36px; padding: 0; font-size: 15px; }
</style>
