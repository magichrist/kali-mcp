/* Authentication store.
 * Preserves existing token-storage behavior: key "kmcp_token", Bearer header,
 * 401 triggers the token modal. No second auth system is introduced.
 */

import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { clearToken, fetchServerInfo, getToken, onUnauthorized, setToken } from "@/api/client";

export const useAuthStore = defineStore("auth", () => {
  /* ── state ── */
  const _token = ref<string>(getToken());
  const modalVisible = ref(false);
  const authChecked = ref(false);
  const authError = ref<string | null>(null);

  /* server info (for badge) */
  const serverName = ref<string>("");
  const serverVersion = ref<string>("");
  const authEnabled = ref<boolean | null>(null);

  /* ── getters ── */
  const token = computed(() => _token.value);
  const isAuthenticated = computed(() => !!_token.value);

  /* ── actions ── */
  async function checkAuth(): Promise<void> {
    try {
      const info = await fetchServerInfo();
      serverName.value = info.server_name;
      serverVersion.value = info.server_version;
      authEnabled.value = info.auth_enabled;
      authError.value = null;
    } catch (err) {
      authError.value = err instanceof Error ? err.message : "auth check failed";
      authEnabled.value = null;
    } finally {
      authChecked.value = true;
    }
  }

  function setTokenValue(value: string): void {
    _token.value = value;
    setToken(value);
    modalVisible.value = false;
  }

  function clearTokenValue(): void {
    _token.value = "";
    clearToken();
    modalVisible.value = false;
  }

  function showModal(): void {
    modalVisible.value = true;
  }

  function hideModal(): void {
    modalVisible.value = false;
  }

  return {
    /* state */
    token,
    isAuthenticated,
    modalVisible,
    authChecked,
    authError,
    serverName,
    serverVersion,
    authEnabled,
    /* actions */
    checkAuth,
    setTokenValue,
    clearTokenValue,
    showModal,
    hideModal,
  };
});

/* Wire the API client's 401 channel to the store so the token modal shows. */
const authStore = useAuthStore();
onUnauthorized(() => {
  authStore.showModal();
});
