<script setup lang="ts">
const props = defineProps<{
  variant?: "ok" | "failed" | "warn" | "default" | "accent";
}>();
</script>

<template>
  <span class="run-state" :class="{ ok: variant === 'ok', failed: variant === 'failed', warn: variant === 'warn', 'run-run': variant === 'ok' }">
    <slot />
  </span>
</template>
