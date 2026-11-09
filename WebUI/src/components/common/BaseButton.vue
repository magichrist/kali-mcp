<script setup lang="ts">
const props = defineProps<{
  variant?: "primary" | "accent" | "ghost" | "danger" | "icon";
  disabled?: boolean;
  /** Accessible name for icon-only buttons (e.g. "Close", "Undo"). */
  "aria-label"?: string;
}>();
</script>

<template>
  <button
    class="btn"
    :class="[
      { primary: variant === 'primary', accent: variant === 'accent',
        ghost: variant === 'ghost', danger: variant === 'danger',
        icon: variant === 'icon' },
      { disabled: disabled },
    ]"
    :disabled="disabled"
    :aria-label="props['aria-label'] ?? undefined"
    @click="$emit('click')"
  >
    <slot />
  </button>
</template>
