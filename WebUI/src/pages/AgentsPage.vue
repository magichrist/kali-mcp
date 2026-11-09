<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useNotificationsStore } from "@/stores/notifications";
import {
  fetchAgents,
  createAgent,
  type AgentProfile,
} from "@/api/client";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseButton from "@/components/common/BaseButton.vue";
import BaseInput from "@/components/common/BaseInput.vue";
import BaseModal from "@/components/common/BaseModal.vue";
import ConfirmDialog from "@/components/common/ConfirmDialog.vue";

const notifications = useNotificationsStore();

/* ── state ── */
const loading = ref(true);
const error = ref<string | null>(null);
const agents = ref<AgentProfile[]>([]);

/* create modal */
const createModal = ref(false);
const creating = ref(false);
const newProfileId = ref("");
const newProfileName = ref("");
const newProfileDesc = ref("");

/* delete confirm */
const deleteConfirm = ref(false);
const deleteTarget = ref<AgentProfile | null>(null);

function openCreate() { createModal.value = true; }
function closeCreate() { createModal.value = false; }

/* ── actions ── */
async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchAgents();
    agents.value = data.agents || [];
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load agents";
    notifications.notify(error.value, "error");
  } finally {
    loading.value = false;
  }
}

async function handleCreate(): Promise<void> {
  creating.value = true;
  try {
    const payload: Parameters<typeof createAgent>[0] = {
      profile_id: newProfileId.value.trim(),
      name: newProfileName.value.trim(),
    };
    if (newProfileDesc.value.trim()) payload.description = newProfileDesc.value.trim();
    await createAgent(payload);
    notifications.notify("Agent profile created", "success");
    createModal.value = false;
    await load();
  } catch (err) {
    creating.value = false;
    notifications.notify(err instanceof Error ? err.message : "Create agent failed", "error");
  }
}

async function confirmDelete(): Promise<void> {
  const a = deleteTarget.value;
  if (!a) return;
  if (!confirm(`Delete agent profile ${a.profile_id}?`)) return;
  try {
    /* delete agent via client */
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { deleteAgent: del } = await import("@/api/client");
    await del(a.profile_id);
    notifications.notify("Deleted", "success");
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
    <LoadingState message="Loading agents…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">AGENTS</div>
      <h1>Agents</h1>
      <div class="subtitle">Deny-by-default catalogs: an agent can only call tools and run playbooks explicitly granted to its profile.</div>
    </div>

    <div id="pageHeadActions">
      <BaseButton variant="ghost" @click="load">Refresh</BaseButton>
      <BaseButton variant="primary" @click="openCreate">＋ New profile</BaseButton>
    </div>

    <div style="padding:8px">
      <div v-if="agents.length === 0" class="empty">No agent profiles. One is created for you on first tool grant.</div>
      <div v-else class="table-panel">
        <div class="table-head" style="grid-template-columns:repeat(5,minmax(0,1fr))">
          <span>Profile</span>
          <span>Description</span>
          <span>Default visibility</span>
          <span>Parallel / Timeout</span>
          <span>Grants</span>
        </div>
        <div
          v-for="a in agents"
          :key="a.profile_id"
          class="table-row"
          :style="{ 'grid-template-columns': 'repeat(5,minmax(0,1fr))' }"
        >
          <span>
            <a :href="`#/agents/${encodeURIComponent(a.profile_id)}`">
              {{ a.profile_id }}
            </a>
            <span v-if="a.name" style="display:block; font-size:12px; color:var(--dim)">{{ a.name }}</span>
          </span>
          <span>{{ a.description || "—" }}</span>
          <span>{{ a.default_visibility || "internal" }}</span>
          <span>{{ a.max_parallel_operations ?? "—" }} / {{ a.max_execution_seconds ?? "—" }}s</span>
          <span>tools: 0 · playbooks: 0</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Create agent modal -->
  <BaseModal v-model:open="createModal" title="New agent profile">
    <div style="display:flex; flex-direction:column; gap:14px; min-width:340px">
      <div>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Profile ID <em style="font-weight:400; font-size:12px; color:var(--dim); display:block; margin-top:1px;">unique</em></label>
        <BaseInput v-model="newProfileId" placeholder="my-agent" />
      </div>
      <div>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Friendly name</label>
        <BaseInput v-model="newProfileName" placeholder="My Agent" />
      </div>
      <div>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Description <em style="font-weight:400; font-size:12px; color:var(--dim); display:block; margin-top:1px;">optional</em></label>
        <BaseInput v-model="newProfileDesc" placeholder="What does this agent do?" />
      </div>
    </div>
    <template #footer>
      <BaseButton @click="closeCreate">Cancel</BaseButton>
      <BaseButton variant="primary" :disabled="creating" @click="handleCreate">Create profile</BaseButton>
    </template>
  </BaseModal>
</template>
