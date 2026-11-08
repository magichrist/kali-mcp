<template>
  <div class="validation-panel">
    <div class="panel-head">
      <span>Validation findings</span>
      <span class="chip" :class="summaryChipClass">{{ summary }}</span>
    </div>
    <div v-if="!findings.length" class="empty">No findings. Run Validate to check the definition.</div>
    <div v-else class="findings-list">
      <div
        v-for="f in findings"
        :key="f.field + '|' + f.step_id + '|' + f.message"
        class="validation-finding"
      >
        <span class="severity" :class="sevClass(f)">{{ f.severity }}</span>
        <span class="finding-meta">
          <span v-if="f.step_id" class="mono">step: {{ f.step_id }}</span>
          <span v-if="f.field" class="mono">· field: {{ f.field }}</span>
        </span>
        <span class="finding-msg">{{ f.message }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ findings: any[] }>();

const findings = computed(() => props.findings ?? []);
const errorCount = computed(() => findings.value.filter((f: any) => f.severity === "error").length);
const summary = computed(() => {
  const e = errorCount.value;
  const total = findings.value.length;
  if (!total) return "—";
  return e ? `${e} error${e > 1 ? "s" : ""} / ${total} finding${total > 1 ? "s" : ""}` : `valid (${total} finding${total > 1 ? "s" : ""})`;
});
const summaryChipClass = computed(() => {
  const e = errorCount.value;
  return e ? "danger" : findings.value.length ? "ck" : "";
});

function sevClass(f: any) {
  return { "sev-error": f.severity === "error", "sev-warning": f.severity === "warning", "sev-info": f.severity === "info" }[f.severity] || "";
}
</script>
