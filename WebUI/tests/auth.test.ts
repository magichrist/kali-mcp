import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { useAuthStore } from "@/stores/auth";

describe("auth store", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.$reset();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("starts with no token and not authenticated", () => {
    const store = useAuthStore();
    expect(store.token).toBe("");
    expect(store.hasToken).toBe(false);
    expect(store.authenticated).toBe(false);
    expect(store.showTokenModal).toBe(false);
  });

  it("persists token to localStorage under kmcp_token", () => {
    const store = useAuthStore();
    store.setToken("abc-123");
    expect(store.token).toBe("abc-123");
    expect(store.hasToken).toBe(true);
    expect(store.authenticated).toBe(true);
    expect(localStorage.getItem("kmcp_token")).toBe("abc-123");
  });

  it("clears token and localStorage", () => {
    const store = useAuthStore();
    store.setToken("abc-123");
    store.clearToken();
    expect(store.token).toBe("");
    expect(store.hasToken).toBe(false);
    expect(store.authenticated).toBe(false);
    expect(localStorage.getItem("kmcp_token")).toBeNull();
  });

  it("controls token modal visibility", () => {
    const store = useAuthStore();
    store.showModal();
    expect(store.showTokenModal).toBe(true);
    store.hideModal();
    expect(store.showTokenModal).toBe(false);
  });

  it("rehydrates token from localStorage on store creation", () => {
    localStorage.setItem("kmcp_token", "stored-token");
    const store = useAuthStore();
    expect(store.token).toBe("stored-token");
    expect(store.hasToken).toBe(true);
    expect(store.authenticated).toBe(true);
  });
});
