<template>
  <div class="dsl-editor">
    <div class="dsl-toolbar">
      <span class="dsl-label">Canonical model (JSON)</span>
      <span class="chip" :class="{ 'ck': valid, danger: !valid }">{{ valid ? "valid JSON" : "invalid JSON" }}</span>
      <button class="btn ghost" @click="$emit('capture-graph')" :disabled="!valid">Sync graph → DSL</button>
    </div>
    <textarea
      ref="codeEl"
      v-model="text"
      class="code-area"
      spellcheck="false"
      :class="{ invalid: !valid }"
      @input="onInput"
    ></textarea>
    <div v-if="error && !valid" class="syntax-error">⚠ {{ error }} — your text is preserved; graph sync is blocked until resolved.</div>
    <div v-else-if="valid" class="dsl-hint">Graph ⇄ DSL stay in sync. Edit here or switch to Graph view.</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  text: string;
  valid: boolean;
  error: string | null;
  definition: any;
}>();

const emit = defineEmits<{ (e: "input", text: string): void; (e: "capture-graph"): void }>();

const text = computed({
  get: () => props.text,
  set: (v: string) => emit("input", v),
});

function onInput(e: Event) {
  const target = e.target as HTMLTextAreaElement;
  emit("input", target.value);
}
</script>

<style scoped>
.dsl-editor { display: flex; flex-direction: column; height: 100%; border-left: 1px solid var(--line); background: var(--panel); }
.dsl-toolbar { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--line); background: var(--panel2); flex-shrink: 0; }
.dsl-label { font-size: 12px; font-weight: 600; color: var(--muted); }
.code-area { flex: 1; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px; color: var(--text); background: #0c1018; border: none; outline: none; padding: 12px; resize: none; min-height: 240px; }
.code-area.invalid { border-left: 4px solid var(--red); }
.syntax-error { padding: 8px 12px; font-size: 12px; color: var(--red); background: var(--red2); border-bottom: 1px solid var(--line); }
.dsl-hint { padding: 6px 12px; font-size: 12px; color: var(--dim); border-bottom: 1px solid var(--line); }
</style>
