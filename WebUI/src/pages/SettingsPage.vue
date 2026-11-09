<template>
  <div class="page">
    <div class="pagehead">
      <div>
        <div class="eyebrow">SETTINGS</div>
        <h1>Server</h1>
        <p class="subtitle">Server runtime configuration (read-only) from the running Kali-MCP server.</p>
      </div>
    </div>
    <div v-if="server" class="two-col" style="margin-top:14px">
      <div class="panel"><div class="panel-head"><span>Server</span></div>
        <div style="padding:12px;line-height:2;font-size:13px">
          <div>Name: <strong>{{ server.server_name }}</strong> v{{ server.server_version }}</div>
          <div>Bind: <strong>{{ server.host }}:{{ server.port }}</strong></div>
          <div>Transport: <strong>{{ server.transport || "—" }}</strong></div>
          <div>Auth: <strong>{{ server.auth_enabled ? "token required" : "disabled (insecure)" }}</strong></div>
        </div></div>
      <div class="panel"><div class="panel-head"><span>Limits</span></div>
        <div style="padding:12px;line-height:2;font-size:13px">
          <div>Default timeout: <strong>{{ server.default_timeout }}s</strong></div>
          <div>Max timeout: <strong>{{ server.max_timeout }}s</strong></div>
          <div>Max concurrent: <strong>{{ server.max_concurrent }}</strong></div>
          <div>Debug mode: <strong>{{ server.debug ? "on" : "off" }}</strong></div>
        </div></div>
    </div>
    <div v-if="server && server.auth_enabled" class="panel" style="margin-top:14px">
      <div class="panel-head"><span>Stored token</span></div>
      <div style="padding:12px;font-size:12px;line-height:1.8">
        The bearer token is stored in this browser only (localStorage key "kmcp_token") and sent via the Authorization header.
        <div style="margin-top:10px"><button class="btn danger" @click="clearToken">Clear stored token</button></div>
      </div>
    </div>
    <div v-if="!server && !error" class="empty">Loading server settings…</div>
    <div v-if="error" class="empty" style="color:var(--red)">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useNotificationsStore } from "@/stores/notifications";
import { apiRequest } from "@/api/client";

const { notify } = useNotificationsStore();
const server = ref<any>(null);
const error = ref<string | null>(null);

onMounted(async () => {
  try { server.value = await apiRequest("/server"); }
  catch (err: any) { error.value = err?.message ?? String(err); }
});

function clearToken() {
  localStorage.removeItem("kmcp_token");
  notify("Stored token cleared");
  server.value = null;
  error.value = null;
}
</script>
