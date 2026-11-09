<script setup lang="ts">
import { ref, watch, onUnmounted, nextTick } from "vue";

const props = defineProps<{
  open: boolean;
  title?: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  dangerous?: boolean;
}>();

const emit = defineEmits(["confirm", "cancel", "update:open"]);

const dialogRef = ref<HTMLElement | null>(null);
let previouslyFocused: HTMLElement | null = null;

function handleCancel() { emit("cancel"); }
function handleConfirm() { emit("confirm"); }

function handleKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") { handleCancel(); }
}

function manageFocus(isOpen: boolean) {
  if (isOpen) {
    previouslyFocused = document.activeElement as HTMLElement | null;
    nextTick(() => {
      dialogRef.value?.querySelector<HTMLElement>('button:not([disabled])')?.focus();
    });
  } else {
    previouslyFocused?.focus();
    previouslyFocused = null;
  }
}

watch(
  () => props.open,
  (isOpen) => { manageFocus(isOpen); },
  { immediate: true },
);

onUnmounted(() => {
  if (props.open) { previouslyFocused?.focus(); previouslyFocused = null; }
});
</script>

<template>
  <div
    ref="dialogRef"
    v-if="open"
    class="modal-backdrop show"
    role="dialog"
    aria-modal="true"
    aria-labelledby="confirm-title"
    @click.self="handleCancel"
    @keydown="handleKeydown"
  >
    <div class="modal" @click.stop>
      <div class="modal-header">
        <h3 id="confirm-title">{{ title || "Confirm" }}</h3>
      </div>
      <div class="modal-body">
        <p id="confirm-message">{{ message || "Are you sure?" }}</p>
      </div>
      <div class="modal-footer">
        <button class="btn ghost" @click="handleCancel">{{ cancelLabel || "Cancel" }}</button>
        <button :class="['btn', dangerous ? 'btn-danger' : 'btn-primary']" @click="handleConfirm">
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
