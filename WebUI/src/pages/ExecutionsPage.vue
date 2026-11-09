<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { useNotificationsStore } from "@/stores/notifications";
import {
  fetchExecutions,
  startExecution,
  type Execution,
} from "@/api/client";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseBadge from "@/components/common/BaseBadge.vue";
import { badgeVariant } from "@/components/common/badgeVariant";
import BaseButton from "@/components/common/BaseButton.vue";
import BaseSelect from "@/components/common/BaseSelect.vue";

const router = useRouter();
const notifications = useNotificationsStore();

const loading = ref(true);
const error = ref<string | null>(null);
const executions = ref<Execution[]>([]);
const statusFilter = ref("all");
const autoRefresh = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;

const filtered = computed(() => {
  const st = statusFilter.value;
  if (st === "all") return executions.value;
  return executions.value.filter((e) => e.status === st);
});

function startTimer(): void {
  stopTimer();
  if (autoRefresh.value) {
    timer = setInterval(load, 5000);
  }
}

function stopTimer(): void {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchExecutions({
      status: statusFilter.value === "all" ? undefined : statusFilter.value,
      limit: 100,
    });
    executions.value = data.executions || [];
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load executions";
    notifications.notify(error.value, "error");
  } finally {
    loading.value = false;
  }
}

async function runPlaybook(): Promise<void> {
  const pid = prompt("Playbook id to run:", "");
  if (!pid) return;
  const raw = prompt(`Run "${pid}" now (runs the published version).\nInputs JSON (optional, e.g. {"target":"127.0.0.1"}):`, "{}");
  if (raw === null) return;
  let inputs: Record<string, unknown> = {};
  if (raw.trim()) {
    try {
      inputs = JSON.parse(raw);
    } catch {
      notifications.notify("Inputs must be valid JSON", "error");
      return;
    }
  }
  notifications.notify(`Starting ${pid}…`, "info");
  try {
    const r = await startExecution({ playbook_id: pid, inputs, debug: false, trigger: "studio" });
    const execId = r.execution?.execution_id || r.execution_id || "";
    if (!execId) {
      notifications.notify("Run started but no execution id", "warn");
      return;
    }
    notifications.notify(`Run started: ${execId}`, "success");
    void router.push({ name: "execution-detail", params: { id: execId } });
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Failed to start execution", "error");
  }
}

onMounted(() => {
  void load();
  startTimer();
});

onUnmounted(() => {
  stopTimer();
});
</script>

<template>
  <div v-if="loading" style="min-height:300px">
    <LoadingState message="Loading executions…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">EXECUTIONS</div>
      <h1>Executions</h1>
      <div class="subtitle">Workflow runs from the DAG engine, newest first. Click an execution for step detail.</div>
    </div>

    <div id="pageHeadActions">
      <BaseButton variant="primary" @click="runPlaybook">▶ Run…</BaseButton>
      <BaseButton variant="ghost" @click="load">Refresh</BaseButton>
    </div>

    <div class="filterbar">
      <BaseSelect v-model="statusFilter" :options="[
        { value: 'all', label: 'All statuses' },
        { value: 'running', label: 'running' },
        { value: 'pending', label: 'pending' },
        { value: 'completed', label: 'completed' },
        { value: 'failed', label: 'failed' },
        { value: 'cancelled', label: 'cancelled' },
      ]" />
      <label class="checkline" style="margin-left:16px">
        <input type="checkbox" id="execAuto" v-model="autoRefresh" @change="startTimer" />
        auto-refresh every 5s
      </label>
    </div>

    <div style="padding:8px">
      <div v-if="filtered.length === 0" class="empty">No executions match this filter.</div>
      <div v-else class="table-panel">
        <div class="table-head" style="grid-template-columns:repeat(5,minmax(0,1fr)) auto">
          <span>Execution</span>
          <span>Playbook</span>
          <span>Trigger</span>
          <span>Status</span>
          <span>Completed</span>
          <span></span>
        </div>
        <div
          v-for="e in filtered"
          :key="e.execution_id"
          class="table-row"
          :style="{ 'grid-template-columns': 'repeat(5,minmax(0,1fr)) auto' }"
        >
          <span>
            <a :href="`#/executions/${encodeURIComponent(e.execution_id)}`">
              {{ e.execution_id }}
            </a>
          </span>
          <span>{{ e.playbook_id || "—" }}</span>
          <span>
            {{ e.trigger || "—" }}
            <span v-if="e.debug" class="chip ck" style="font-size:11px; margin-left:6px">debug</span>
          </span>
          <span>
            <BaseBadge :variant="badgeVariant(e.status)">{{ e.status }}</BaseBadge>
          </span>
          <span>{{ (e.completed_at || "").slice(0, 19) || "—" }}</span>
          <span>
            <a :href="`#/executions/${encodeURIComponent(e.execution_id)}`">detail</a>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
