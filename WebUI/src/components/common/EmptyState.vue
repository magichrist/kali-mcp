<script setup lang="ts">
const props = defineProps<{ message?: string; glyph?: string }>();
</script>

<template>
  <p class="empty">{{ message || "Nothing here yet." }}</p>
</template>
