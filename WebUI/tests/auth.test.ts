import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useAuthStore } from "@/stores/auth";

describe("auth store", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.clearTokenValue();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("starts with no token and not authenticated", () => {
    const store = useAuthStore();
    expect(store.token).toBe("");
    expect(store.isAuthenticated).toBe(false);
    expect(store.modalVisible).toBe(false);
  });

  it("persists token to localStorage under kmcp_token", () => {
    const store = useAuthStore();
    store.setTokenValue("abc-123");
    expect(store.token).toBe("abc-123");
    expect(store.isAuthenticated).toBe(true);
    expect(localStorage.getItem("kmcp_token")).toBe("abc-123");
  });

  it("clears token and localStorage", () => {
    const store = useAuthStore();
    store.setTokenValue("abc-123");
    store.clearTokenValue();
    expect(store.token).toBe("");
    expect(store.isAuthenticated).toBe(false);
    expect(localStorage.getItem("kmcp_token")).toBeNull();
  });

  it("controls token modal visibility", () => {
    const store = useAuthStore();
    store.showModal();
    expect(store.modalVisible).toBe(true);
    store.hideModal();
    expect(store.modalVisible).toBe(false);
  });

  it("rehydrates token from localStorage on store creation", () => {
    localStorage.setItem("kmcp_token", "stored-token");
    // Fresh Pinia so the store is created now and re-hydrates from localStorage.
    setActivePinia(createPinia());
    const store = useAuthStore();
    expect(store.token).toBe("stored-token");
    expect(store.isAuthenticated).toBe(true);
  });
});
