/* Notifications store — global toast notifications. */

import { defineStore } from "pinia";
import { ref } from "vue";

export interface Notification {
  id: string;
  message: string;
  type: "info" | "success" | "error" | "warn";
  duration?: number;
}

let nextId = 0;

export const useNotificationsStore = defineStore("notifications", () => {
  const notifications = ref<Notification[]>([]);

  function notify(message: string, type: Notification["type"] = "info", duration = 4000): string {
    const id = `notif-${++nextId}`;
    notifications.value.push({ id, message, type, duration });
    if (duration > 0) {
      setTimeout(() => {
        dismiss(id);
      }, duration);
    }
    return id;
  }

  function dismiss(id: string): void {
    notifications.value = notifications.value.filter((n) => n.id !== id);
  }

  function clear(): void {
    notifications.value = [];
  }

  return { notifications, notify, dismiss, clear };
});
