<script setup lang="ts">
import { ref, watch, onUnmounted, nextTick } from "vue";

const props = defineProps<{
  open: boolean;
  title?: string;
  width?: string;
  closable?: boolean;
}>();

const emit = defineEmits(["update:open", "close"]);

const modalRef = ref<HTMLElement | null>(null);
const closeBtnRef = ref<HTMLElement | null>(null);
let previouslyFocused: HTMLElement | null = null;

function handleClose() { emit("close"); emit("update:open", false); }

function getFocusables(): HTMLElement[] {
  if (!modalRef.value) return [];
  return Array.from(
    modalRef.value.querySelectorAll<HTMLElement>(
      "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
    )
  );
}

function trapFocus(e: KeyboardEvent) {
  if (e.key === "Escape") { handleClose(); return; }
  if (e.key !== "Tab") return;
  const focusables = getFocusables();
  if (!focusables.length) return;
  e.preventDefault();
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement as HTMLElement | null;
  const idx = active ? focusables.indexOf(active) : -1;
  if (e.shiftKey) {
    if (idx <= 0) { last.focus(); } else { focusables[idx - 1]?.focus(); }
  } else {
    if (idx >= focusables.length - 1 || active === null) { first.focus(); }
    else { focusables[idx + 1]?.focus(); }
  }
}

function manageFocus(isOpen: boolean) {
  if (isOpen) {
    previouslyFocused = document.activeElement as HTMLElement | null;
    nextTick(() => {
      const focusTarget = closeBtnRef.value ?? getFocusables()[0] ?? modalRef.value;
      focusTarget?.focus();
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
    v-if="open"
    ref="modalRef"
    class="modal-backdrop show"
    role="dialog"
    aria-modal="true"
    :aria-labelledby="title ? 'modal-title' : undefined"
    :aria-describedby="$slots.default ? 'modal-body' : undefined"
    @click.self="handleClose"
    @keydown="trapFocus"
  >
    <div class="modal" :style="{ width: width }" @click.stop>
      <div class="modal-header" v-if="title || $slots.header">
        <slot name="header">
          <h3 id="modal-title">{{ title }}</h3>
        </slot>
        <button
          v-if="closable !== false"
          ref="closeBtnRef"
          class="btn ghost icon"
          @click="handleClose"
          aria-label="Close"
        >
          ×
        </button>
      </div>
      <div class="modal-body" id="modal-body">
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
