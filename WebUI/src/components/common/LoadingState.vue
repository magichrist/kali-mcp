<script setup lang="ts">
const props = defineProps<{ message?: string }>();
</script>

<template>
  <p class="empty">{{ message || "Loading…" }}</p>
</template>
