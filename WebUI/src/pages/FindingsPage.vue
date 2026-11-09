<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useNotificationsStore } from "@/stores/notifications";
import { fetchFindings, type Finding } from "@/api/client";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseBadge from "@/components/common/BaseBadge.vue";
import { badgeVariant } from "@/components/common/badgeVariant";
import BaseButton from "@/components/common/BaseButton.vue";
import BaseInput from "@/components/common/BaseInput.vue";
import BaseSelect from "@/components/common/BaseSelect.vue";

const notifications = useNotificationsStore();

/* ── state ── */
const loading = ref(true);
const error = ref<string | null>(null);
const findings = ref<Finding[]>([]);
const count = ref(0);

const severityFilter = ref("all");
const targetFilter = ref("");
const toolFilter = ref("");

/* ── actions ── */
async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchFindings({
      severity: severityFilter.value === "all" ? undefined : severityFilter.value,
      target: targetFilter.value || undefined,
      tool: toolFilter.value || undefined,
      limit: 100,
    });
    findings.value = data.findings || [];
    count.value = data.count ?? findings.value.length;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load findings";
    notifications.notify(error.value, "error");
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div v-if="loading" style="min-height:300px">
    <LoadingState message="Loading findings…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">FINDINGS</div>
      <h1>Findings</h1>
      <div class="subtitle">Query normalized findings. Filters hit the database directly.</div>
    </div>

    <div id="pageHeadActions">
      <BaseButton variant="ghost" @click="load">Refresh</BaseButton>
    </div>

    <div class="filterbar" style="gap:8px">
      <BaseSelect
        v-model="severityFilter"
        :options="[
          { value: 'all', label: 'All severities' },
          { value: 'critical', label: 'critical' },
          { value: 'high', label: 'high' },
          { value: 'medium', label: 'medium' },
          { value: 'low', label: 'low' },
          { value: 'info', label: 'info' },
        ]"
        @change="load"
      />
      <BaseInput v-model="targetFilter" placeholder="target…" style="width:180px" />
      <BaseInput v-model="toolFilter" placeholder="tool…" style="width:180px" />
      <BaseButton variant="primary" @click="load">Apply</BaseButton>
    </div>

    <div style="padding:8px">
      <div v-if="findings.length === 0" class="empty">No findings match these filters.</div>
      <div v-else class="table-panel">
        <div class="table-head" style="grid-template-columns:repeat(5,minmax(0,1fr))">
          <span>Test</span>
          <span>Severity</span>
          <span>Tool</span>
          <span>Status</span>
          <span>Created</span>
        </div>
        <div
          v-for="f in findings"
          :key="((f.test_name || '') + '|' + (f.created_at || ''))"
          class="table-row"
          :style="{ 'grid-template-columns': 'repeat(5,minmax(0,1fr))' }"
        >
          <span>{{ f.test_name || f.checkname || f.name || "—" }}</span>
          <span>
            <BaseBadge :variant="badgeVariant(f.severity)">{{ f.severity }}</BaseBadge>
          </span>
          <span>{{ f.tool || "—" }}</span>
          <span>{{ f.status || f.validation_status || "—" }}</span>
          <span>{{ (f.created_at || "").slice(0, 19) }}</span>
        </div>
      </div>
    </div>

    <div class="head-right" style="margin-top:8px">
      <span style="padding:4px 10px; background:var(--panel2); border:1px solid var(--line); border-radius:9px; font-size:12.5px; color:var(--muted); white-space:nowrap">
        {{ count }} findings
      </span>
    </div>
  </div>
</template>
