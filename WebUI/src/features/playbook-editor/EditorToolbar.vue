<template>
  <div class="editor-toolbar">
    <div class="toolbar-group">
      <button class="btn ghost" @click="$emit('view-toggle', 'graph')" :class="{ active: currentView === 'graph' }">Graph</button>
      <button class="btn ghost" @click="$emit('view-toggle', 'dsl')" :class="{ active: currentView === 'dsl' }">DSL</button>
    </div>
    <div class="toolbar-group toolbar-actions">
      <button class="btn" @click="$emit('validate')">Validate</button>
      <button class="btn ghost" @click="$emit('reset')">↻ Reset</button>
      <button class="btn" @click="$emit('save-draft')">Save draft</button>
      <button class="btn accent" @click="$emit('run-test')">▶ Run test</button>
      <button class="btn primary" @click="$emit('publish')">Publish</button>
    </div>
    <div class="toolbar-group toolbar-more">
      <div class="dropdown" :class="{ open: moreOpen }">
        <button class="btn ghost" @click="toggleMore" :class="{ active: moreOpen }" title="More actions">⋯</button>
        <div v-if="moreOpen" class="dropdown-menu" @click.self="closeMore">
          <button class="dropdown-item" @click="$emit('import')">↙ Import</button>
          <button class="dropdown-item" @click="$emit('export')">⤓ Export</button>
          <button class="dropdown-item" @click="$emit('versions')">📦 Versions</button>
          <button class="dropdown-item" @click="$emit('rollback')">⏪ Rollback</button>
          <button class="dropdown-item danger" @click="$emit('delete')">✕ Delete</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
const props = defineProps<{
  currentView: "graph" | "dsl";
}>();

const emit = defineEmits<{
  (e: "view-toggle", view: "graph" | "dsl"): void;
  (e: "validate"): void;
  (e: "reset"): void;
  (e: "save-draft"): void;
  (e: "run-test"): void;
  (e: "publish"): void;
  (e: "import"): void;
  (e: "export"): void;
  (e: "versions"): void;
  (e: "rollback"): void;
  (e: "delete"): void;
}>();

const moreOpen = ref(false);

function toggleMore(): void { moreOpen.value = !moreOpen.value; }
function closeMore(): void { moreOpen.value = false; }
</script>

<style scoped>
.editor-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  background: #0d1117;
  flex-wrap: wrap;
}
.toolbar-group {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.toolbar-actions { flex: 1; justify-content: flex-end; }
.toolbar-more { flex-shrink: 0; }
.btn.active { background: var(--panel3); color: var(--text); box-shadow: inset 0 0 0 1px var(--line2); }
.dropdown { position: relative; display: inline-block; }
.dropdown-menu {
  position: absolute;
  top: 100%;
  right: 0;
  min-width: 160px;
  background: #161b22;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  z-index: 40;
  display: flex;
  flex-direction: column;
  margin-top: 6px;
}
.dropdown-item {
  width: 100%;
  text-align: left;
  padding: 8px 12px;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
}
.dropdown-item:hover { background: var(--panel2); }
.dropdown-item.danger { color: var(--red); }
.dropdown-item.danger:hover { background: var(--red2); }
</style>
