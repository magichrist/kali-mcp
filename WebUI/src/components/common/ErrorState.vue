<script setup lang="ts">
const props = defineProps<{ message?: string; detail?: string }>();
</script>

<template>
  <div class="error">{{ message || "An error occurred." }}</div>
  <p v-if="detail" class="dim small">{{ detail }}</p>
</template>
