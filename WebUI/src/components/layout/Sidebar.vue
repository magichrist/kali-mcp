<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";
import { computed } from "vue";

const route = useRoute();
const router = useRouter();

const navItems = [
  { route: "overview", label: "Overview", icon: "◫" },
  { route: "playbooks", label: "Playbook Studio", icon: "⌘" },
  { route: "executions", label: "Executions", icon: "◷" },
  { route: "tools", label: "Tool Registry", icon: "▦" },
  { route: "connections", label: "MCP Connections", icon: "⌁" },
  { route: "agents", label: "Agents", icon: "◉" },
  { route: "findings", label: "Findings", icon: "◐" },
  { route: "settings", label: "Settings", icon: "⚙" },
];

function isActive(itemRoute: string): boolean {
  return route.name === itemRoute || route.path === `/${itemRoute}`;
}

function go(itemRoute: string): void {
  void router.push(`/${itemRoute}`);
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brandmark">K</div>
      <div>
        <div class="brandname">KALI-MCP</div>
        <div class="brandmeta">Security workspace</div>
      </div>
    </div>
    <div class="nav-label">Navigation</div>
    <nav class="nav" id="mainNav">
      <button
        v-for="item in navItems"
        :key="item.route"
        class="nav-item"
        :class="{ active: isActive(item.route) }"
        @click="go(item.route)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </nav>
    <div class="side-bottom">
      <div class="user">
        <div class="avatar" id="authBadge">·</div>
        <div>
          <strong id="authState">Checking auth…</strong>
          <small id="serverMeta">—</small>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped></style>
