<script setup lang="ts">
const props = defineProps<{
  open: boolean;
  title?: string;
  width?: string;
  closable?: boolean;
}>();

const emit = defineEmits(["update:open", "close"]);
</script>

<template>
  <div
    v-if="open"
    class="modal-backdrop show"
    @click.self="close"
  >
    <div class="modal" :style="{ width: width }" @click.stop>
      <div class="modal-header" v-if="title || $slots.header">
        <slot name="header">
          <h3>{{ title }}</h3>
        </slot>
        <button
          v-if="closable !== false"
          class="btn ghost icon"
          @click="close"
          title="Close"
        >
          ×
        </button>
      </div>
      <div class="modal-body">
        <slot />
      </div>
      <div class="modal-footer" v-if="$slots.footer">
        <slot name="footer" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 8px;
}
.modal-header h3 {
  margin: 0;
  font-size: 18px;
}
.modal-body {
  overflow: auto;
  max-height: 60vh;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}
</style>
