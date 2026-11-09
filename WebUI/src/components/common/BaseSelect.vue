<script setup lang="ts">
/* Accessible select.
 * - When `label` is given, a real <label> is rendered and associated via for/id.
 * - `aria-invalid` / `aria-required` expose state to assistive tech.
 */
const props = defineProps<{
  modelValue?: string | number;
  options: Array<{ value: string | number; label: string }>;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  error?: string;
  required?: boolean;
}>();

const emit = defineEmits(["update:modelValue"]);

const selectId = `km-select-${Math.random().toString(36).slice(2)}`;
</script>

<template>
  <div class="ins-field" v-if="label">
    <label
      :for="selectId"
      class="ins-flabel"
    >
      <span class="ins-flabel-txt">{{ label }}</span>
      <span v-if="error" class="dim" style="color:var(--red)">{{ error }}</span>
    </label>
  </div>
  <select
    :id="label ? selectId : undefined"
    class="select"
    :value="modelValue ?? ''"
    :disabled="disabled"
    :aria-invalid="error ? 'true' : 'false'"
    :aria-required="required ? 'true' : 'false'"
    :aria-label="!label ? placeholder : undefined"
    @change="$emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
  >
    <option value="">{{ placeholder || "" }}</option>
    <option v-for="opt in options" :key="opt.value" :value="opt.value">
      {{ opt.label }}
    </option>
  </select>
</template>
