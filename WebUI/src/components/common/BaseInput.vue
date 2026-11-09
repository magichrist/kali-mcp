<script setup lang="ts">
/* Accessible text input.
 * - When `label` is given, a real <label> is rendered and associated via for/id.
 * - When no `label` is given, `aria-label` falls back to `placeholder`.
 * - `aria-invalid` / `aria-required` expose state to assistive tech.
 */
const props = defineProps<{
  modelValue?: string;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  type?: "text" | "number" | "password" | "email";
  error?: string;
  required?: boolean;
}>();

const emit = defineEmits(["update:modelValue"]);

const inputId = `km-input-${Math.random().toString(36).slice(2)}`;
</script>

<template>
  <div class="ins-field" v-if="label">
    <label
      :for="inputId"
      class="ins-flabel"
    >
      <span class="ins-flabel-txt">{{ label }}</span>
      <span v-if="error" class="dim" style="color:var(--red)">{{ error }}</span>
    </label>
  </div>
  <input
    :id="label ? inputId : undefined"
    :type="type"
    :class="['select', error ? 'error-input' : '']"
    :value="modelValue ?? ''"
    :placeholder="placeholder"
    :disabled="disabled"
    :aria-invalid="error ? 'true' : 'false'"
    :aria-required="required ? 'true' : 'false'"
    :aria-label="!label ? placeholder : undefined"
    @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>

<style scoped>
.error-input {
  border-color: #59303a;
}
</style>
