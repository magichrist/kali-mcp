<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useNotificationsStore } from "@/stores/notifications";
import {
  fetchConnection,
  discoverConnection,
  type Connection,
} from "@/api/client";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseBadge from "@/components/common/BaseBadge.vue";
import { badgeVariant } from "@/components/common/badgeVariant";
import BaseButton from "@/components/common/BaseButton.vue";

const route = useRoute();
const router = useRouter();
const notifications = useNotificationsStore();

const id = computed(() => String(route.params.id ?? ""));
const loading = ref(true);
const error = ref<string | null>(null);
const connection = ref<Connection | null>(null);

async function load(): Promise<void> {
  if (!id.value) return;
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchConnection(id.value);
    connection.value = data.connection;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load connection";
    notifications.notify(error.value, "error");
  } finally {
    loading.value = false;
  }
}

async function handleDiscover(): Promise<void> {
  if (!id.value) return;
  try {
    const r = await discoverConnection(id.value);
    notifications.notify(`Imported ${r.count} tools`, "success");
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Discover failed", "error");
  }
}

function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div v-if="loading" style="min-height:300px">
    <LoadingState message="Loading connection…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else-if="connection" class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">MCP CONNECTIONS</div>
      <h1>{{ connection.connection_id }}</h1>
      <div class="subtitle">
        {{ connection.name || "" }} · transport {{ connection.transport }}
        <span style="margin-left:8px">
          <BaseBadge :variant="badgeVariant(connection.enabled ? connection.health_status : undefined)">
            {{ connection.enabled ? (connection.health_status || 'unknown') : 'disabled' }}
          </BaseBadge>
        </span>
      </div>
    </div>

    <div id="pageHeadActions">
      <BaseButton variant="ghost" :to="{ name: 'connections' }">← back</BaseButton>
      <BaseButton @click="handleDiscover">Discover &amp; import</BaseButton>
    </div>

    <div class="panel" style="margin-top:10px; padding:14px">
      <pre class="result">{{ prettyJson(connection) }}</pre>
    </div>

    <div class="panel" style="min-height:140px; margin-top:14px">
      <div class="panel-head">
        <span>Imported tools</span>
      </div>
      <div style="padding:8px">
        <div v-if="!(connection.imported_tools || []).length" class="empty">Nothing imported from this connection yet.</div>
        <div v-else class="table-panel">
          <div class="table-head" style="grid-template-columns:repeat(2,minmax(0,1fr))">
            <span>Tool</span>
            <span>Visibility</span>
          </div>
          <div
            v-for="t in connection.imported_tools"
            :key="t.tool_id"
            class="table-row"
            :style="{ 'grid-template-columns': 'repeat(2,minmax(0,1fr))' }"
          >
            <span>{{ t.tool_id }}</span>
            <span>{{ t.visibility || "—" }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
