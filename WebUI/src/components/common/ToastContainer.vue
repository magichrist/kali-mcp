<script setup lang="ts">
import { useNotificationsStore } from "@/stores/notifications";
const notifications = useNotificationsStore();
function dismiss(id: number) { notifications.dismiss(id); }
</script>

<template>
  <transition-group name="toast" tag="div" class="toasts-container">
    <div v-for="toast in notifications.toasts" :key="toast.id" class="toast" :class="`toast--${toast.type}`" @click="dismiss(toast.id)">
      {{ toast.message }}
    </div>
  </transition-group>
</template>

<style scoped>
.toasts-container { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%); z-index: 300; display: flex; flex-direction: column; align-items: center; gap: 8px; pointer-events: none; }
.toast { pointer-events: auto; background: var(--panel3); border: 1px solid var(--line2); border-radius: 10px; color: var(--text); font-size: 13.5px; padding: 11px 18px; box-shadow: var(--shadow); cursor: pointer; }
.toast--error { border-color: #552a31; color: var(--red); background: rgba(58, 34, 38, 0.4); }
.toast--success { border-color: #2c5743; color: var(--green); background: rgba(20, 43, 32, 0.4); }
.toast--warn { border-color: #5d4a26; color: var(--amber); background: rgba(66, 51, 27, 0.4); }
.toast-enter-active, .toast-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(16px); }
</style>
