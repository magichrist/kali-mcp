<script setup lang="ts">
import { useRoute } from "vue-router";

const route = useRoute();
</script>

<template>
  <div class="page-container">
    <div class="page-head">
      <div class="eyebrow">PLAYBOOK STUDIO</div>
      <h1>Playbook Editor</h1>
      <p class="subtitle">Edit playbook <code>{{ route.params.id }}</code> — graph / DSL views (Vue Flow).</p>
    </div>
    <div class="editor-placeholder panel">
      <p class="dim">Graph editor coming in Plan 5 (Vue Flow).</p>
      <p class="dim small">DSL source of truth preserved — raw JSON definition edited in sync with the graph.</p>
    </div>
  </div>
</template>

<style scoped>
.page-container { padding: 0; max-width: none; width: 100%; height: calc(100vh - 60px); display: flex; flex-direction: column; }
.page-head { flex: none; padding: 10px 20px; border-bottom: 1px solid var(--line); background: #0e1218; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.page-head .eyebrow { margin-bottom: 0; }
.editor-placeholder { flex: 1; padding: 40px; color: var(--muted); display: flex; flex-direction: column; gap: 8px; }
</style>
