<script setup lang="ts">
const props = defineProps<{
  modelValue?: string;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  type?: "text" | "number" | "password" | "email";
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
  <input
    :type="type"
    :class="['select', error ? 'error-input' : '']"
    :value="modelValue ?? ''"
    :placeholder="placeholder"
    :disabled="disabled"
    @input="$emit('update:modelValue', $event.target.value)"
  />
</template>

<style scoped>
.error-input {
  border-color: #59303a;
}
</style>
