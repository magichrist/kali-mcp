<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { useNotificationsStore } from "@/stores/notifications";
import {
  fetchPlaybooks,
  createPlaybook,
  importPlaybook,
  deletePlaybook,
  type Playbook,
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

const router = useRouter();
const notifications = useNotificationsStore();

const loading = ref(true);
const error = ref<string | null>(null);
const playbooks = ref<Playbook[]>([]);

const searchQuery = ref("");
const statusFilter = ref("");
const categoryFilter = ref("");
const sort = ref("newest");

const createModal = ref(false);
const creating = ref(false);
const newName = ref("");
const newId = ref("");
const newCategory = ref("custom");
const newDesc = ref("");
const idHint = ref("");

const importModal = ref(false);
const importing = ref(false);
const importFile = ref<File | null>(null);

const deleteConfirm = ref(false);
const deleteTarget = ref<Playbook | null>(null);

function openCreate() { createModal.value = true; }
function closeCreate() { createModal.value = false; }
function openImport() { importModal.value = true; }
function closeImport() { importModal.value = false; importFile.value = null; }
function handleImportFile(e: Event) { const f = (e.target as HTMLInputElement).files?.[0] || null; if (f) importFile.value = f; }
function closeDelete() { deleteConfirm.value = false; deleteTarget.value = null; }

const categories = computed(() => {
  const set = new Set<string>();
  for (const p of playbooks.value) {
    if (p.category) set.add(p.category);
  }
  return Array.from(set).sort();
});

const filtered = computed(() => {
  const q = searchQuery.value.toLowerCase().trim();
  const st = statusFilter.value;
  const cat = categoryFilter.value;
  let rows = playbooks.value.filter((p) =>
    (!q ||
      `${p.name} ${p.playbook_id} ${p.description || ""}`.toLowerCase().includes(q)) &&
    (!st || (p.status || "") === st) &&
    (!cat || (p.category || "custom") === cat)
  );
  if (sort.value === "name") {
    rows = rows.slice().sort((a, b) => String(a.name).localeCompare(String(b.name)));
  } else if (sort.value === "oldest") {
    rows = rows.slice().sort((a, b) => (a.playbook_id || "").localeCompare(b.playbook_id || ""));
  } else {
    rows = rows.slice().sort((a, b) => (b.playbook_id || "").localeCompare(a.playbook_id || ""));
  }
  return rows;
});

function validateCreate(): boolean {
  const ids = new Set(playbooks.value.map((p) => p.playbook_id));
  const id = newId.value.trim();
  let err = "";
  if (id && ids.has(id)) err = `A playbook with ID “${id}” already exists`;
  else if (/[^\w-]/.test(id)) err = "Letters, numbers, dashes and underscores only";
  idHint.value = err;
  return Boolean(err === "" && newName.value.trim() && id);
}

async function submitCreate(): Promise<void> {
  if (!validateCreate()) return;
  creating.value = true;
  try {
    const payload: Parameters<typeof createPlaybook>[0] = {
      playbook_id: newId.value.trim(),
      name: newName.value.trim().slice(0, 120),
      category: newCategory.value,
    };
    if (newDesc.value.trim()) payload.description = newDesc.value.trim();
    await createPlaybook(payload);
    notifications.notify(`“${newName.value}” created`, "success");
    createModal.value = false;
    await load();
    void router.push({ name: "playbook-editor", params: { id: newId.value.trim() } });
  } catch (err) {
    creating.value = false;
    notifications.notify(err instanceof Error ? err.message : "Failed to create playbook", "error");
  }
}

async function handleImport(): Promise<void> {
  if (!importFile.value) return;
  importing.value = true;
  try {
    const text = await importFile.value.text();
    const pkg = JSON.parse(text);
    await importPlaybook(pkg);
    notifications.notify("Playbook imported", "success");
    importModal.value = false;
    importFile.value = null;
    await load();
  } catch (err) {
    importing.value = false;
    notifications.notify(err instanceof Error ? err.message : "Import failed", "error");
  }
}

async function confirmDelete(): Promise<void> {
  const p = deleteTarget.value;
  if (!p) return;
  try {
    await deletePlaybook(p.playbook_id);
    notifications.notify("Playbook deleted", "success");
    deleteConfirm.value = false;
    deleteTarget.value = null;
    await load();
  } catch (err) {
    notifications.notify(err instanceof Error ? err.message : "Delete failed", "error");
  }
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const data = await fetchPlaybooks({ limit: 200 });
    playbooks.value = data.playbooks || [];
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load playbooks";
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
    <LoadingState message="Loading playbooks…" />
  </div>
  <div v-else-if="error" style="min-height:300px">
    <ErrorState :message="error" detail="Check your API token and try again." />
  </div>
  <div v-else class="page-content">
    <div id="pageHeadInfo">
      <div class="eyebrow">PLAYBOOK STUDIO</div>
      <h1>Playbooks</h1>
      <div class="subtitle">Create, manage and organize security workflows. Open one to edit it on the graph or in the DSL.</div>
    </div>

    <div id="pageHeadActions">
      <BaseButton variant="ghost" @click="openImport">↙ Import</BaseButton>
      <BaseButton variant="primary" @click="openCreate">＋ New playbook</BaseButton>
    </div>

    <div class="filterbar lib-filter">
      <BaseInput v-model="searchQuery" placeholder="Search playbooks…" style="flex:1;min-width:260px" />
      <BaseSelect
        v-model="statusFilter"
        :options="[
          { value: '', label: 'All statuses' },
          { value: 'draft', label: 'draft' },
          { value: 'published', label: 'published' },
        ]"
      />
      <BaseSelect
        v-model="categoryFilter"
        :options="[{ value: '', label: 'All categories' }, ...categories.map((c) => ({ value: c, label: c }))]"
      />
      <BaseSelect
        v-model="sort"
        :options="[
          { value: 'newest', label: 'Newest first' },
          { value: 'oldest', label: 'Oldest first' },
          { value: 'name', label: 'Name A–Z' },
        ]"
      />
    </div>

    <div class="lib-grid" id="pbGrid">
      <div v-if="playbooks.length === 0" class="lib-empty" style="grid-column:1 / -1; padding:72px 24px 56px; text-align:center">
        <div class="lib-empty-glyph">⌘</div>
        <h2>Create your first playbook</h2>
        <p>Build a security workflow out of registered tools, shell commands and internal stages — visually on the graph, in the DSL, or both.</p>
        <div class="lib-empty-actions" style="margin-top:18px; display:flex; gap:12px; justify-content:center; flex-wrap:wrap">
          <BaseButton variant="primary" @click="openCreate">＋ Create playbook</BaseButton>
          <BaseButton @click="openImport">↙ Import playbook</BaseButton>
        </div>
      </div>
      <div v-else-if="filtered.length === 0" class="empty" style="text-align:center; padding:24px">No playbooks match this filter.</div>
      <div v-else>
        <a
          v-for="p in filtered"
          :key="p.playbook_id"
          class="pb-card"
          :href="`#/playbooks/${encodeURIComponent(p.playbook_id)}`"
        >
          <div class="pb-card-top">
            <span class="pb-card-name">{{ p.name }}</span>
            <BaseBadge :variant="p.status === 'published' ? 'ok' : 'default'">{{ p.status }}</BaseBadge>
          </div>
          <p class="pb-card-desc">{{ p.description || "No description yet." }}</p>
          <div class="pb-card-meta">
            <span class="chip">{{ p.category || "custom" }}</span>
            <span class="chip mono">{{ p.playbook_id }}</span>
            <span class="dim">v {{ p.current_version_id || "—" }}</span>
            <span class="dim">{{ (p.created_at || "").slice(0, 10) }}</span>
          </div>
        </a>
      </div>
    </div>
  </div>

  <BaseModal v-model:open="createModal" title="New playbook">
    <div style="display:flex; flex-direction:column; gap:14px; min-width:320px">
      <div>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Name <em style="font-weight:400; font-size:12px; color:var(--dim); display:block; margin-top:1px;">shown in the library and editor header</em></label>
        <BaseInput v-model="newName" placeholder="e.g. External recon sweep" />
      </div>
      <div>
        <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Playbook ID <em style="font-weight:400; font-size:12px; color:var(--dim); display:block; margin-top:1px;">stable identifier used in runs and URLs — auto-filled from the name</em></label>
        <BaseInput v-model="newId" placeholder="external_recon_sweep" />
        <span v-if="idHint" style="display:block; font-size:12px; margin-top:5px; color:var(--dim)">{{ idHint }}</span>
      </div>
      <div style="display:grid; grid-template-columns:172px minmax(0,1fr); gap:12px; align-items:end">
        <div>
          <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Category</label>
          <BaseSelect v-model="newCategory" :options="[
            { value: 'custom', label: 'custom' },
            { value: 'recon', label: 'recon' },
            { value: 'assessment', label: 'assessment' },
            { value: 'reporting', label: 'reporting' },
            { value: 'response', label: 'response' },
          ]" />
        </div>
        <div>
          <label style="display:block; font-weight:600; font-size:13px; margin-bottom:2px">Description <em style="font-weight:400; font-size:12px; color:var(--dim); display:block; margin-top:1px;">optional</em></label>
          <BaseInput v-model="newDesc" placeholder="What does this workflow do?" />
        </div>
      </div>
    </div>
    <template #footer>
      <BaseButton @click="closeCreate">Cancel</BaseButton>
      <BaseButton variant="primary" :disabled="creating" @click="submitCreate">Create playbook</BaseButton>
    </template>
  </BaseModal>

  <BaseModal v-model:open="importModal" title="Import playbook">
    <div style="min-width:320px">
      <label style="display:block; font-weight:600; font-size:13px; margin-bottom:6px">JSON package file</label>
      <input type="file" accept=".json" @change="handleImportFile" class="select" />
      <p v-if="importFile" class="dim" style="font-size:12px; margin-top:6px">{{ importFile.name }}</p>
    </div>
    <template #footer>
      <BaseButton @click="closeImport">Cancel</BaseButton>
      <BaseButton variant="primary" :disabled="importing || !importFile" @click="handleImport">Import</BaseButton>
    </template>
  </BaseModal>

  <ConfirmDialog
    v-model:open="deleteConfirm"
    title="Delete playbook"
    :message="deleteTarget ? `Delete playbook ${deleteTarget.playbook_id}? This cannot be undone.` : 'Delete playbook?'"
    confirmLabel="Delete"
    cancelLabel="Cancel"
    dangerous
    @confirm="confirmDelete"
    @cancel="closeDelete"
  />
</template>
