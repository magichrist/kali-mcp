import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { connectionApi } from "@/api/connections";
import { API_BASE, ApiError } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

const BASE = API_BASE;

function mockJson(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  }));
  globalThis.fetch = fetchMock as any;
  return fetchMock;
}

describe("connectionApi", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("lists connections GET /api/connections", async () => {
    const fetchMock = mockJson(200, { connections: [], count: 0 });
    const res = await connectionApi.list();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/connections`);
    expect(res.connections).toEqual([]);
  });

  it("tests connection POST /api/connections/:id/test", async () => {
    const fetchMock = mockJson(200, { ok: true, healthy: true });
    const res = await connectionApi.test("c_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/connections/c_1/test`);
    expect(init?.method).toBe("POST");
    expect(res.ok).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it("discovers tools POST /api/connections/:id/discover", async () => {
    const fetchMock = mockJson(200, { imported_tools: [{ tool_id: "nmap", visibility: "agent_callable" }], count: 1 });
    const res = await connectionApi.discover("c_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/connections/c_1/discover`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({}));
    expect(res.count).toBe(1);
  });

  it("deletes connection DELETE /api/connections/:id", async () => {
    const fetchMock = mockJson(200, { status: "deleted" });
    const res = await connectionApi.delete("c_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/connections/c_1`);
    expect(init?.method).toBe("DELETE");
    expect(res.status).toBe("deleted");
  });

  it("401 shows the token modal", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { message: "unauthorized" } }), { status: 401 }));
    globalThis.fetch = fetchMock as any;
    const store = useAuthStore();
    await expect(connectionApi.test("c_1")).rejects.toThrow(ApiError);
    expect(store.modalVisible).toBe(true);
  });

  it("sends Bearer header when token exists", async () => {
    localStorage.setItem("kmcp_token", "tk-conn-123");
    const fetchMock = mockJson(200, { connections: [] });
    await connectionApi.list();
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({ Authorization: "Bearer tk-conn-123" });
  });

  it("never puts token in URL or query string", async () => {
    localStorage.setItem("kmcp_token", "secret-token");
    const fetchMock = mockJson(200, { connections: [] });
    await connectionApi.list();
    const [url] = fetchMock.mock.calls[0];
    expect(url).not.toContain("secret-token");
    expect(url).not.toContain("token");
  });
});
