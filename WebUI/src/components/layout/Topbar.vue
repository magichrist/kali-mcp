<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const auth = useAuthStore();

const crumbTitle = computed(() => route.meta?.title || route.name || "");
</script>

<template>
  <header class="topbar">
    <button class="btn ghost icon" id="sidebarToggle" title="Hide/show sidebar">☰</button>
    <div class="crumb">
      <span>Workspace</span><span class="slash">/</span>
      <span id="crumbPage">{{ crumbTitle }}</span>
      <template id="crumbTail"></template>
      <b id="crumbTitle"></b>
    </div>
    <div class="top-actions" id="topActions"></div>
  </header>
</template>

<style scoped></style>
