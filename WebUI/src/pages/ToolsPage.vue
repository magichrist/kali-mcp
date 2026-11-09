<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useNotificationsStore } from "@/stores/notifications";
import { fetchTools, setToolVisibility, type Tool } from "@/api/client";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseBadge from "@/components/common/BaseBadge.vue";
import BaseButton from "@/components/common/BaseButton.vue";
import BaseInput from "@/components/common/BaseInput.vue";
import BaseSelect from "@/components/common/BaseSelect.vue";

const notifications = useNotificationsStore();

const VISIBILITY_OPTIONS = [
  { value: "agent_callable", label: "agent_callable" },
  { value: "playbook_selectable", label: "playbook_selectable" },
  { value: "internal", label: "internal" },
  { value: "hidden", label: "hidden" },
];

const loading = ref(true);
const error = ref<string | null>(null);
const tools = ref<Tool[]>([]);
const searchQuery = ref("");
const saving = ref<Set<string>>(new Set());

const filtered = computed(() => {
  const q = searchQuery.value.toLowerCase().trim();
  return tools.value.filter(
    (t) =>
      !q ||
      String(t.tool_id).toLowerCase().includes(q) ||
      String(t.name || "").toLowerCase().includes(q)
  );
});

const isBuiltin = (t: Tool): boolean => t.provider === "native" || t.provider === "builtin";

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchTools({ limit: 500 });
    tools.value = data.tools || [];
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load tools";
    notifications.notify(error.value, "error");
  } finally {
    loading.value = false;
  }
}

async function changeVisibility(tool: Tool, visibility: string): Promise<void> {
  saving.value.add(tool.tool_id);
  try {
    await setToolVisibility(tool.tool_id, visibility);
    notifications.notify(`${tool.tool_id} → ${visibility}`, "success");
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Visibility update failed", "error");
  } finally {
    saving.value.delete(tool.tool_id);
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div v-if="loading" style="min-height:300px">
    <LoadingState message="Loading tools…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">TOOL REGISTRY</div>
      <h1>Tool Registry</h1>
      <div class="subtitle">Every tool known to the backend. Changing visibility writes to the database.</div>
    </div>

    <div id="pageHeadActions">
      <BaseButton variant="ghost" @click="load">Refresh</BaseButton>
    </div>

    <div class="filterbar">
      <BaseInput v-model="searchQuery" placeholder="Search tool id or name…" style="flex:1;min-width:260px" />
    </div>

    <div style="padding:8px">
      <div v-if="filtered.length === 0" class="empty">No tools registered — import MCP connections to populate the registry.</div>
      <div v-else class="table-panel">
        <div class="table-head" style="grid-template-columns:repeat(5,minmax(0,1fr)) auto">
          <span>Tool</span>
          <span>Provider</span>
          <span>Visibility</span>
          <span>Enabled</span>
          <span>Timeout</span>
          <span></span>
        </div>
        <div
          v-for="t in filtered"
          :key="t.tool_id"
          class="table-row"
          :style="{ 'grid-template-columns': 'repeat(5,minmax(0,1fr)) auto' }"
        >
          <span>{{ t.tool_id }}</span>
          <span>{{ t.provider || "—" }}</span>
          <span>
            <BaseSelect
              v-model="t.visibility"
              :options="VISIBILITY_OPTIONS"
              :disabled="saving.has(t.tool_id)"
              @change="(val: string) => changeVisibility(t, val)"
            />
          </span>
          <span>{{ t.enabled ? "yes" : "no" }}</span>
          <span>{{ t.default_timeout ?? "—" }}</span>
          <span v-if="isBuiltin(t)" class="dim">builtin</span>
        </div>
      </div>
    </div>
  </div>
</template>
