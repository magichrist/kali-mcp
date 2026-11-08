<script setup lang="ts">
const props = defineProps<{
  open: boolean;
  title?: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  dangerous?: boolean;
}>();

const emit = defineEmits(["confirm", "cancel", "update:open"]);
</script>

<template>
  <div
    v-if="open"
    class="modal-backdrop show"
    @click.self="cancel"
  >
    <div class="modal" @click.stop>
      <div class="modal-header">
        <h3>{{ title || "Confirm" }}</h3>
      </div>
      <div class="modal-body">
        <p>{{ message || "Are you sure?" }}</p>
      </div>
      <div class="modal-footer">
        <button class="btn ghost" @click="cancel">{{ cancelLabel || "Cancel" }}</button>
        <button :class="['btn', dangerous ? 'btn-danger' : 'btn-primary']" @click="confirm">
          {{ confirmLabel || "Confirm" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.btn-danger {
  border-color: #552a31;
  color: var(--red);
  background: rgba(58, 34, 38, 0.4);
}
.btn-danger:hover {
  background: var(--red2);
  border-color: #6d323c;
}
</style>
