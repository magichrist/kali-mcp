<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useNotificationsStore } from "@/stores/notifications";
import {
  fetchAgent,
  deleteAgent,
  grantAgentTool,
  revokeAgentTool,
  assignAgentPlaybook,
  unassignAgentPlaybook,
  type AgentDetailResponse,
} from "@/api/client";
import LoadingState from "@/components/common/LoadingState.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import ErrorState from "@/components/common/ErrorState.vue";
import BaseBadge from "@/components/common/BaseBadge.vue";
import BaseButton from "@/components/common/BaseButton.vue";
import BaseInput from "@/components/common/BaseInput.vue";
import BaseModal from "@/components/common/BaseModal.vue";
import ConfirmDialog from "@/components/common/ConfirmDialog.vue";

const route = useRoute();
const router = useRouter();
const notifications = useNotificationsStore();

const id = computed(() => String(route.params.id ?? ""));
const loading = ref(true);
const error = ref<string | null>(null);
const agent = ref<AgentDetailResponse | null>(null);

const grantModal = ref(false);
const granting = ref(false);
const grantToolId = ref("");

const assignModal = ref(false);
const assigning = ref(false);
const assignPlaybookId = ref("");

const deleteConfirm = ref(false);

function openGrantModal() { grantModal.value = true; }
function closeGrantModal() { grantModal.value = false; }
function openAssignModal() { assignModal.value = true; }
function closeAssignModal() { assignModal.value = false; }

/* ── actions ── */
async function load(): Promise<void> {
  if (!id.value) return;
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchAgent(id.value);
    agent.value = data;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load agent";
    notifications.notify(error.value, "error");
  } finally {
    loading.value = false;
  }
}

async function handleGrant(): Promise<void> {
  if (!id.value || !grantToolId.value) return;
  granting.value = true;
  try {
    await grantAgentTool(id.value, grantToolId.value);
    notifications.notify(`Granted ${grantToolId.value}`, "success");
    grantModal.value = false;
    grantToolId.value = "";
    await load();
  } catch (err) {
    granting.value = false;
    notifications.notify(err instanceof Error ? err.message : "Grant failed", "error");
  }
}

async function handleRevoke(toolId: string): Promise<void> {
  if (!id.value) return;
  if (!confirm(`Revoke tool ${toolId} from ${id.value}?`)) return;
  try {
    await revokeAgentTool(id.value, toolId);
    notifications.notify(`Revoked ${toolId}`, "success");
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Revoke failed", "error");
  }
}

async function handleAssign(): Promise<void> {
  if (!id.value || !assignPlaybookId.value) return;
  assigning.value = true;
  try {
    await assignAgentPlaybook(id.value, assignPlaybookId.value);
    notifications.notify(`Assigned ${assignPlaybookId.value}`, "success");
    assignModal.value = false;
    assignPlaybookId.value = "";
    await load();
  } catch (err) {
    assigning.value = false;
    notifications.notify(err instanceof Error ? err.message : "Assign failed", "error");
  }
}

async function handleUnassign(playbookId: string): Promise<void> {
  if (!id.value) return;
  if (!confirm(`Unassign playbook ${playbookId} from ${id.value}?`)) return;
  try {
    await unassignAgentPlaybook(id.value, playbookId);
    notifications.notify(`Unassigned ${playbookId}`, "success");
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Unassign failed", "error");
  }
}

async function handleDelete(): Promise<void> {
  if (!id.value) return;
  if (!confirm(`Delete agent profile ${id.value}?`)) return;
  try {
    await deleteAgent(id.value);
    notifications.notify("Deleted", "success");
    void router.push({ name: "agents" });
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
    <LoadingState message="Loading agent…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else-if="agent" class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">AGENTS</div>
      <h1>{{ agent.agent.profile_id }}</h1>
      <div class="subtitle">
        {{ agent.agent.name || "" }}
        <span style="margin-left:8px">parallel {{ agent.agent.max_parallel_operations ?? "—" }}</span>
        <span style="margin-left:8px">timeout {{ agent.agent.max_execution_seconds ?? "—" }}s</span>
      </div>
    </div>

    <div id="pageHeadActions">
      <BaseButton variant="ghost" :to="{ name: 'agents' }">← back</BaseButton>
      <BaseButton variant="danger" @click="handleDelete">Delete profile</BaseButton>
    </div>

    <div class="kpi-grid" style="margin-top:14px">
      <div class="kpi">
        <div class="kpi-label">Callable tools</div>
        <div class="kpi-value">{{ (agent.effective_catalog.tools || []).length }}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Assignable playbooks</div>
        <div class="kpi-value">{{ (agent.effective_catalog.playbooks || []).length }}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">Default visibility</div>
        <div class="kpi-value">{{ agent.agent.default_visibility || "internal" }}</div>
      </div>
    </div>

    <div class="panel" style="min-height:140px; margin-top:14px">
      <div class="panel-head">
        <span>Tool grants</span>
        <BaseButton size="sm" variant="ghost" @click="openGrantModal">Grant tool</BaseButton>
      </div>
      <div style="padding:8px">
        <div v-if="!(agent.permissions || []).length" class="empty">No tool grants yet. Grant one to allow this agent to call a tool.</div>
        <div v-else class="table-panel">
          <div class="table-head" style="grid-template-columns:repeat(3,minmax(0,1fr)) auto">
            <span>Tool</span>
            <span>Granted</span>
            <span>Granted at</span>
            <span></span>
          </div>
          <div
            v-for="p in agent.permissions"
            :key="p.tool_id"
            class="table-row"
            :style="{ 'grid-template-columns': 'repeat(3,minmax(0,1fr)) auto' }"
          >
            <span>{{ p.tool_id }}</span>
            <span>
              <BaseBadge :variant="p.granted ? 'ok' : 'failed'">
                {{ p.granted ? 'granted' : 'denied' }}
              </BaseBadge>
            </span>
            <span>{{ (p.granted_at || "").slice(0, 19) }}</span>
            <span>
              <BaseButton size="sm" variant="danger" @click="() => handleRevoke(p.tool_id)">Revoke</BaseButton>
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="panel" style="min-height:140px; margin-top:14px">
      <div class="panel-head">
        <span>Playbook assignments</span>
        <BaseButton size="sm" variant="ghost" @click="openAssignModal">Assign playbook</BaseButton>
      </div>
      <div style="padding:8px">
        <div v-if="!(agent.assignments || []).length" class="empty">No playbook assignments yet.</div>
        <div v-else class="table-panel">
          <div class="table-head" style="grid-template-columns:repeat(3,minmax(0,1fr)) auto">
            <span>Playbook</span>
            <span>Granted</span>
            <span>Granted at</span>
            <span></span>
          </div>
          <div
            v-for="a in agent.assignments"
            :key="a.playbook_id"
            class="table-row"
            :style="{ 'grid-template-columns': 'repeat(3,minmax(0,1fr)) auto' }"
          >
            <span>{{ a.playbook_id }}</span>
            <span>
              <BaseBadge :variant="a.granted ? 'ok' : 'failed'">
                {{ a.granted ? 'assigned' : 'blocked' }}
              </BaseBadge>
            </span>
            <span>{{ (a.granted_at || "").slice(0, 19) }}</span>
            <span>
              <BaseButton size="sm" variant="danger" @click="() => handleUnassign(a.playbook_id)">Unassign</BaseButton>
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Grant tool modal -->
  <BaseModal v-model:open="grantModal" title="Grant tool">
    <div style="min-width:340px">
      <label style="display:block; font-weight:600; font-size:13px; margin-bottom:6px">Tool ID to grant</label>
      <BaseInput v-model="grantToolId" placeholder="nmap" />
    </div>
    <template #footer>
      <BaseButton @click="closeGrantModal">Cancel</BaseButton>
      <BaseButton variant="primary" :disabled="granting || !grantToolId" @click="handleGrant">Grant</BaseButton>
    </template>
  </BaseModal>

  <!-- Assign playbook modal -->
  <BaseModal v-model:open="assignModal" title="Assign playbook">
    <div style="min-width:340px">
      <label style="display:block; font-weight:600; font-size:13px; margin-bottom:6px">Playbook ID to assign</label>
      <BaseInput v-model="assignPlaybookId" placeholder="my_playbook" />
    </div>
    <template #footer>
      <BaseButton @click="closeAssignModal">Cancel</BaseButton>
      <BaseButton variant="primary" :disabled="assigning || !assignPlaybookId" @click="handleAssign">Assign</BaseButton>
    </template>
  </BaseModal>
</template>
