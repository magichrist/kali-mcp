<script setup lang="ts">
/* API token modal — shown on 401. Mirrors the original tokenModal behavior. */
import { ref } from "vue";
import { useAuthStore } from "@/stores/auth";

const props = defineProps<{
  show: boolean;
}>();

const emit = defineEmits<{
  (e: "save"): void;
  (e: "close"): void;
}>();

const auth = useAuthStore();
const token = ref("");

function handleSave() {
  if (!token.value.trim()) return;
  auth.setTokenValue(token.value);
  emit("save");
}

function handleClose() {
  emit("close");
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === "Enter") handleSave();
}
</script>

<template>
  <div
    v-if="show"
    class="modal-backdrop show"
    @click.self="handleClose"
    role="dialog"
    aria-modal="true"
    aria-labelledby="token-modal-title"
  >
    <div class="modal">
      <h3 id="token-modal-title">API token required</h3>
      <p>This server is protected by an API token. Paste it once — it is stored only in your browser and sent as a bearer header.</p>
      <input
        id="tokenInput"
        v-model="token"
        placeholder="MCP_API_TOKEN value"
        type="password"
        autocomplete="current-password"
        @keydown="handleKeydown"
        aria-label="API token"
        class="token-input"
      />
      <div class="modal-actions">
        <button class="btn" @click="handleClose">Cancel</button>
        <button class="btn primary" @click="handleSave">Save &amp; retry</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.token-input {
  width: 100%;
  height: 42px;
  padding: 0 12px;
  border-radius: 9px;
  border: 1px solid var(--line2);
  background: #0d1219;
  color: var(--text);
  font-size: 14px;
  margin: 8px 0;
}
.token-input:focus {
  border-color: var(--green-strong);
}
.token-input:focus-visible {
  outline: 2px solid var(--green-strong);
  outline-offset: 1px;
}
</style>
