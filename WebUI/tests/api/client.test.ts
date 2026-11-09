import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api, ApiError, API_BASE } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

const BASE = import.meta.env.VITE_API_BASE || "/api";

describe("API base", () => {
  it("defaults to /api when VITE_API_BASE is unset", () => {
    expect(API_BASE).toBe("/api");
  });
});

describe("api client auth header", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    // clear any pending retries
    // (pendingRetries is module-private; reset via store)
    const store = useAuthStore();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("injects Bearer token when token present in localStorage", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ data: { ok: true } }), { status: 200 }));
    globalThis.fetch = fetchMock as any;

    localStorage.setItem("kmcp_token", "test-token-123");
    await api("/playbooks");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks`);
    expect(init?.headers).toMatchObject({ Authorization: "Bearer test-token-123" });
  });

  it("does not send Authorization header when no token", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ data: [] }), { status: 200 }));
    globalThis.fetch = fetchMock as any;

    await api("/playbooks");

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).not.toHaveProperty("Authorization");
  });

  it("never puts token in URL or query string", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ data: [] }), { status: 200 }));
    globalThis.fetch = fetchMock as any;

    localStorage.setItem("kmcp_token", "secret-token");
    await api("/playbooks?status=draft");

    const [url] = fetchMock.mock.calls[0];
    expect(url).not.toContain("secret-token");
    expect(url).not.toContain("token");
    expect(url).toContain("status=draft");
  });
});

describe("api client error normalization", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("normalizes non-JSON error bodies", async () => {
    const fetchMock = vi.fn(async () => new Response("boom", { status: 500, statusText: "Internal Server Error" }));
    globalThis.fetch = fetchMock as any;

    await expect(api("/playbooks")).rejects.toThrow(ApiError);
    try {
      await api("/playbooks");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(500);
    }
  });

  it("normalizes JSON error message", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: { message: "playbook not found" } }), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
    );
    globalThis.fetch = fetchMock as any;

    try {
      await api("/playbooks/missing");
    } catch (e) {
      expect((e as ApiError).status).toBe(404);
      expect((e as ApiError).message).toContain("playbook not found");
    }
  });

  it("401 does not leak token into error message", async () => {
    localStorage.setItem("kmcp_token", "secret-token");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { message: "token invalid" } }), { status: 401 }));
    globalThis.fetch = fetchMock as any;

    try {
      await api("/playbooks");
    } catch (e) {
      expect((e as ApiError).message).not.toContain("secret-token");
      expect((e as ApiError).status).toBe(401);
    }
  });

  it("network failure throws ApiError with status 0", async () => {
    const fetchMock = vi.fn(async () => { throw new TypeError("Failed to fetch"); });
    globalThis.fetch = fetchMock as any;

    try {
      await api("/playbooks");
    } catch (e) {
      expect(e).toBeInstanceOf(TypeError);
    }
  });
});

describe("api client 401 token modal + retry", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("shows token modal on 401", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { message: "unauthorized" } }), { status: 401 }));
    globalThis.fetch = fetchMock as any;

    const store = useAuthStore();
    await expect(api("/playbooks")).rejects.toThrow(ApiError);
    expect(store.modalVisible).toBe(true);
  });
});
