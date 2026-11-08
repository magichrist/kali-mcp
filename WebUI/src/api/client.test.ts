import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiRequest, get, post, put, del, getToken, setToken, clearToken, onUnauthorized, ApiError } from "@/api/client";

const base = import.meta.env.VITE_API_BASE ?? "/api";

function mockFetch(response: unknown, status = 200, opts: { headers?: Record<string, string> } = {}) {
  const headers = new Headers({ "content-type": "application/json", ...opts.headers });
  return vi.fn(() => Promise.resolve(new Response(JSON.stringify(response), { status, headers }))) as unknown as typeof fetch;
}

describe("API client", () => {
  let origFetch: typeof fetch;

  beforeEach(() => {
    origFetch = globalThis.fetch;
    clearToken();
  });

  afterEach(() => {
    globalThis.fetch = origFetch;
    vi.restoreAllMocks();
  });

  it("sends Bearer token from localStorage", async () => {
    setToken("abc123");
    const fn = mockFetch({ ok: true });
    globalThis.fetch = fn;
    await get("/playbooks");
    expect(fn).toHaveBeenCalledTimes(1);
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe(`${base}/playbooks`);
    expect(init?.headers?.Authorization).toBe("Bearer abc123");
  });

  it("parses ok responses and throws on non-ok with normalized message", async () => {
    const fn = mockFetch({ error: { message: "playbook not found" } }, 404);
    globalThis.fetch = fn;
    await expect(get("/playbooks/nope")).rejects.toMatchObject(new ApiError("playbook not found", 404));
  });

  it("emits unauthorized on 401", async () => {
    const fn = mockFetch({ error: { message: "unauthorized" } }, 401);
    globalThis.fetch = fn;
    const handler = vi.fn();
    const off = onUnauthorized(handler);
    await expect(get("/playbooks")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalled();
    off();
  });

  it("getToken/setToken/clearToken round-trip", () => {
    expect(getToken()).toBe("");
    setToken("tok");
    expect(getToken()).toBe("tok");
    clearToken();
    expect(getToken()).toBe("");
  });
});
