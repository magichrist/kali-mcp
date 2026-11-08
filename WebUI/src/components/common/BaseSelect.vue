<script setup lang="ts">
const props = defineProps<{
  modelValue?: string | number;
  options: Array<{ value: string | number; label: string }>;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  error?: string;
}>();

const emit = defineEmits(["update:modelValue"]);
</script>

<template>
  <div class="ins-field" v-if="label">
    <span class="ins-flabel">
      <span class="ins-flabel-txt">{{ label }}</span>
      <span v-if="error" class="dim" style="color:var(--red)">{{ error }}</span>
    </span>
  </div>
  <select
    class="select"
    :value="modelValue ?? ''"
    :disabled="disabled"
    @change="$emit('update:modelValue', $event.target.value)"
  >
    <option value="">{{ placeholder || "" }}</option>
    <option v-for="opt in options" :key="opt.value" :value="opt.value">
      {{ opt.label }}
    </option>
  </select>
</template>
