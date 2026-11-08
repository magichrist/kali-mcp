<script setup lang="ts">
const props = defineProps<{
  variant?: "primary" | "accent" | "ghost" | "danger" | "icon";
  disabled?: boolean;
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
    @click="$emit('click')"
  >
    <slot />
  </button>
</template>
