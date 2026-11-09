<script setup lang="ts">
import { useRoute } from "vue-router";
import { computed } from "vue";

const route = useRoute();

const breadcrumbItems = computed(() => {
  const items: Array<{ label: string; to?: string }> = [];
  const meta = route.meta as { crumb?: string } | undefined;
  if (meta?.crumb) {
    items.push({ label: meta.crumb });
  }
  if (route.params.id) {
    items.push({ label: String(route.params.id) });
  }
  if (items.length === 0) {
    items.push({ label: "Workspace" });
  }
  return items;
});
</script>

<template>
  <nav class="crumb" aria-label="Breadcrumb">
    <span>Workspace</span>
    <span class="slash">/</span>
    <template v-for="(item, i) in breadcrumbItems" :key="i">
      <span v-if="item.to" @click="$router.push(item.to)">{{ item.label }}</span>
      <span id="crumb-page" v-else>{{ item.label }}</span>
      <span class="slash" v-if="i < breadcrumbItems.length - 1">/</span>
    </template>
    <b id="crumb-title">{{ route.meta?.title ?? "" }}</b>
  </nav>
</template>

<style scoped></style>
