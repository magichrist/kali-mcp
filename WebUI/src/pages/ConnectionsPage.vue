<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useNotificationsStore } from "@/stores/notifications";
import {
  fetchConnections,
  createConnection,
  testConnection,
  discoverConnection,
  deleteConnection,
  type Connection,
} from "@/api/client";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseBadge from "@/components/common/BaseBadge.vue";
import BaseButton from "@/components/common/BaseButton.vue";
import BaseInput from "@/components/common/BaseInput.vue";
import BaseSelect from "@/components/common/BaseSelect.vue";
import BaseModal from "@/components/common/BaseModal.vue";
import ConfirmDialog from "@/components/common/ConfirmDialog.vue";

const route = useRoute();
const router = useRouter();
const notifications = useNotificationsStore();

const loading = ref(true);
const error = ref<string | null>(null);
const connections = ref<Connection[]>([]);

const addModal = ref(false);
const adding = ref(false);
const newConnId = ref("");
const newConnName = ref("");
const newConnTransport = ref("sse");
const newConnEndpoint = ref("");
const newConnCommand = ref("");

const deleteConfirm = ref(false);
const deleteTarget = ref<Connection | null>(null);

const deleteMessage = computed(() => {
  const c = deleteTarget.value;
  return c ? `Delete connection ${c.connection_id}?` : "Delete connection?";
});

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchConnections();
    connections.value = data.connections || [];
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load connections";
    notifications.notify(error.value, "error");
  } finally {
    loading.value = false;
  }
}

async function handleAdd(): Promise<void> {
  adding.value = true;
  try {
    const payload: Parameters<typeof createConnection>[0] = {
      connection_id: newConnId.value.trim(),
      name: newConnName.value.trim(),
      transport: newConnTransport.value,
    };
    if (newConnTransport.value !== "stdio" && newConnEndpoint.value.trim()) {
      payload.endpoint_url = newConnEndpoint.value.trim();
    }
    if (newConnTransport.value === "stdio" && newConnCommand.value.trim()) {
      payload.command = newConnCommand.value.trim();
    }
    await createConnection(payload);
    notifications.notify("Connection added", "success");
    addModal.value = false;
    await load();
  } catch (err) {
    adding.value = false;
    notifications.notify(err instanceof Error ? err.message : "Add connection failed", "error");
  }
}

async function handleTest(c: Connection): Promise<void> {
  try {
    await testConnection(c.connection_id);
    notifications.notify(`Test ${c.connection_id} ok`, "success");
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Test failed", "error");
  }
}

async function handleDiscover(c: Connection): Promise<void> {
  try {
    const r = await discoverConnection(c.connection_id);
    notifications.notify(`Imported ${r.count} tools`, "success");
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Discover failed", "error");
  }
}

async function confirmDelete(): Promise<void> {
  const c = deleteTarget.value;
  if (!c) return;
  try {
    await deleteConnection(c.connection_id);
    notifications.notify("Connection deleted", "success");
    deleteConfirm.value = false;
    deleteTarget.value = null;
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Delete failed", "error");
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div v-if="loading" style="min-height:300px">
    <LoadingState message="Loading connections…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">MCP CONNECTIONS</div>
      <h1>MCP Connections</h1>
      <div class="subtitle">Registered external MCP servers. Test probes connectivity; Discover imports tools.</div>
    </div>

    <div id="pageHeadActions">
      <BaseButton variant="ghost" @click="load">Refresh</BaseButton>
      <BaseButton variant="primary" @click="() => (addModal.value = true)">＋ Add connection</BaseButton>
    </div>

    <div style="padding:8px">
      <div v-if="connections.length === 0" class="empty">No connections yet. Add one to import external MCP tools.</div>
      <div v-else class="table-panel">
        <div class="table-head" style="grid-template-columns:repeat(5,minmax(0,1fr)) auto">
          <span>Connection</span>
          <span>Transport</span>
          <span>Endpoint</span>
          <span>Health</span>
          <span>Exported tools</span>
          <span></span>
        </div>
        <div
          v-for="c in connections"
          :key="c.connection_id"
          class="table-row"
          :style="{ 'grid-template-columns': 'repeat(5,minmax(0,1fr)) auto' }"
        >
          <span>
            <a :href="`#/connections/${encodeURIComponent(c.connection_id)}`">
              {{ c.connection_id }}
            </a>
            <span v-if="c.name" style="display:block; font-size:12px; color:var(--dim)">{{ c.name }}</span>
          </span>
          <span>{{ c.transport || "—" }}</span>
          <span>{{ c.endpoint_url || c.command || "—" }}</span>
          <span>
            <BaseBadge :variant="c.enabled ? (c.health_status || 'unknown') : 'internal'">
              {{ c.enabled ? (c.health_status || 'unknown') : 'disabled' }}
            </BaseBadge>
          </span>
          <span>{{ c.imported_tool_count ?? 0 }}</span>
          <span style="display:flex; gap:6px">
            <BaseButton size="sm" variant="ghost" @click="() => handleTest(c)">Test</BaseButton>
            <BaseButton size="sm" variant="ghost" @click="() => handleDiscover(c)">Discover</BaseButton>
            <BaseButton size="sm" variant="danger" @click="() => { deleteTarget.value = c; deleteConfirm.value = true; }">Delete</BaseButton>
          </span>
        </div>
      </div>
    </div>
  </div>

  <BaseModal v-model:open="addModal" title="Add connection">
    <div style="display:flex; flex-direction:column; gap:14px; min-width:340px">
      <div>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Connection ID <em style="font-weight:400; font-size:12px; color:var(--dim); display:block; margin-top:1px;">unique</em></label>
        <BaseInput v-model="newConnId" placeholder="my-mcp-server" />
      </div>
      <div>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Friendly name</label>
        <BaseInput v-model="newConnName" placeholder="My MCP Server" />
      </div>
      <div>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Transport</label>
        <BaseSelect v-model="newConnTransport" :options="[
          { value: 'sse', label: 'sse' },
          { value: 'streamable-http', label: 'streamable-http' },
          { value: 'stdio', label: 'stdio' },
        ]" />
      </div>
      <div v-if="newConnTransport !== 'stdio'">
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Endpoint URL</label>
        <BaseInput v-model="newConnEndpoint" placeholder="http://localhost:8000/mcp" />
      </div>
      <div v-else>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Command</label>
        <BaseInput v-model="newConnCommand" placeholder="npx mcp-server-fs" />
      </div>
    </div>
    <template #footer>
      <BaseButton @click="() => (addModal.value = false)">Cancel</BaseButton>
      <BaseButton variant="primary" :disabled="adding" @click="handleAdd">Add connection</BaseButton>
    </template>
  </BaseModal>

  <ConfirmDialog
    v-model:open="deleteConfirm"
    title="Delete connection"
    :message="deleteMessage"
    confirmLabel="Delete"
    cancelLabel="Cancel"
    dangerous
    @confirm="confirmDelete"
    @cancel="() => { deleteConfirm.value = false; deleteTarget.value = null; }"
  />
</template>

<script lang="ts">
import { defineComponent, computed } from "vue";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseBadge from "@/components/common/BaseBadge.vue";
import BaseButton from "@/components/common/BaseButton.vue";
import BaseInput from "@/components/common/BaseInput.vue";
import BaseSelect from "@/components/common/BaseSelect.vue";
import BaseModal from "@/components/common/BaseModal.vue";
import ConfirmDialog from "@/components/common/ConfirmDialog.vue";

export default defineComponent({
  components: {
    LoadingState,
    EmptyState,
    ErrorState,
    BaseBadge,
    BaseButton,
    BaseInput,
    BaseSelect,
    BaseModal,
    ConfirmDialog,
  },
});
</script>
