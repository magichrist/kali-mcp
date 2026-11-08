<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useNotificationsStore } from "@/stores/notifications";
import {
  fetchExecution,
  cancelExecution,
  resumeExecution,
  type Execution,
} from "@/api/client";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseBadge from "@/components/common/BaseBadge.vue";
import BaseButton from "@/components/common/BaseButton.vue";

const route = useRoute();
const router = useRouter();
const notifications = useNotificationsStore();

const id = computed(() => String(route.params.id ?? ""));
const loading = ref(true);
const error = ref<string | null>(null);
const execution = ref<Execution | null>(null);

async function load(): Promise<void> {
  if (!id.value) return;
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchExecution(id.value);
    execution.value = data.execution;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load execution";
    notifications.notify(error.value, "error");
  } finally {
    loading.value = false;
  }
}

function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

async function handleCancel(): Promise<void> {
  if (!id.value) return;
  if (!confirm(`Cancel ${id.value}?`)) return;
  try {
    await cancelExecution(id.value);
    notifications.notify("Cancelled", "success");
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Cancel failed", "error");
  }
}

async function handleResume(): Promise<void> {
  if (!id.value) return;
  try {
    await resumeExecution(id.value);
    notifications.notify("Resume requested", "success");
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Resume failed", "error");
  }
}

const isTerminal = computed(() => {
  const s = execution.value?.status || "";
  return !["running", "pending"].includes(s);
});

onMounted(() => {
  void load();
});
</script>

<template>
  <div v-if="loading" style="min-height:300px">
    <LoadingState message="Loading execution…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else-if="execution" class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">EXECUTIONS</div>
      <h1>{{ execution.execution_id }}</h1>
      <div class="subtitle">
        {{ execution.playbook_id || "" }}
        <span style="margin-left:8px">
          <BaseBadge :variant="execution.status">{{ execution.status }}</BaseBadge>
        </span>
        <span v-if="execution.trigger" style="margin-left:8px">trigger: <b class="mono">{{ execution.trigger }}</b></span>
        <span v-if="execution.debug" style="margin-left:8px" class="chip ck">debug</span>
      </div>
    </div>

    <div id="pageHeadActions">
      <span class="exec-kpi-badge" style="padding:4px 10px; background:var(--panel2); border:1px solid var(--line); border-radius:9px; font-size:12.5px; color:var(--muted); white-space:nowrap">
        {{ (execution.steps || []).length }} steps
      </span>
      <span class="exec-kpi-badge" style="padding:4px 10px; background:var(--panel2); border:1px solid var(--line); border-radius:9px; font-size:12.5px; color:var(--muted); white-space:nowrap; margin-left:8px">
        {{ (execution.artifacts || []).length }} artifacts
      </span>
      <span class="exec-kpi-badge" style="padding:4px 10px; background:var(--panel2); border:1px solid var(--line); border-radius:9px; font-size:12.5px; color:var(--muted); white-space:nowrap; margin-left:8px">
        {{ (execution.completed_at || "").slice(0, 19) || "—" }}
      </span>
      <BaseButton variant="danger" :disabled="isTerminal" @click="handleCancel">Cancel</BaseButton>
      <BaseButton @click="handleResume">Resume from checkpoint</BaseButton>
      <BaseButton variant="ghost" :to="{ name: 'executions' }">← back</BaseButton>
    </div>

    <div class="panel" style="margin-top:10px; padding:10px">
      <pre class="result">{{ prettyJson(execution) }}</pre>
    </div>

    <div class="two-col" style="margin-top:10px">
      <div class="panel" style="min-height:auto">
        <div class="panel-head"><span>Steps</span></div>
        <div style="padding:6px">
          <div v-if="!(execution.steps || []).length" class="empty">No steps recorded.</div>
          <div v-else class="table-panel">
            <div class="table-head" style="grid-template-columns:repeat(3,minmax(0,1fr))">
              <span>Step</span>
              <span>Tool</span>
              <span>Status</span>
            </div>
            <div
              v-for="s in execution.steps"
              :key="s.step_id"
              class="table-row"
              :style="{ 'grid-template-columns': 'repeat(3,minmax(0,1fr))' }"
            >
              <span>{{ s.step_id }}</span>
              <span>{{ s.tool_id || "—" }}</span>
              <span>
                <BaseBadge :variant="s.status">{{ s.status }}</BaseBadge>
              </span>
            </div>
          </div>
        </div>
      </div>
      <div class="panel" style="min-height:auto">
        <div class="panel-head"><span>Artifacts</span></div>
        <div style="padding:6px">
          <div v-if="!(execution.artifacts || []).length" class="empty">No artifacts recorded.</div>
          <div v-else class="table-panel">
            <div class="table-head" style="grid-template-columns:repeat(2,minmax(0,1fr))">
              <span>Artifact</span>
              <span>Category</span>
            </div>
            <div
              v-for="a in execution.artifacts"
              :key="a.artifact_id || a.name"
              class="table-row"
              :style="{ 'grid-template-columns': 'repeat(2,minmax(0,1fr))' }"
            >
              <span>{{ a.name || a.artifact_id || a.evidence_id || "—" }}</span>
              <span>{{ a.category || "—" }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
