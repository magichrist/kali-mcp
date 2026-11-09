import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { toolApi } from "@/api/tools";
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

describe("toolApi", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("lists tools GET /api/tools", async () => {
    const fetchMock = mockJson(200, { tools: [], count: 0 });
    const res = await toolApi.list();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/tools`);
    expect(res.tools).toEqual([]);
  });

  it("lists tools with query params", async () => {
    const fetchMock = mockJson(200, { tools: [], count: 0 });
    await toolApi.list({ limit: 20, visibility: "agent_callable", enabled: "true" });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/tools?limit=20&visibility=agent_callable&enabled=true`);
  });

  it("sets tool visibility PUT /api/tools/:id/visibility", async () => {
    const fetchMock = mockJson(200, { tool_id: "t_1", visibility: "hidden" });
    const res = await toolApi.setVisibility("t_1", { visibility: "hidden" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/tools/t_1/visibility`);
    expect(init?.method).toBe("PUT");
    expect(init?.body).toBe(JSON.stringify({ visibility: "hidden" }));
    expect(res.visibility).toBe("hidden");
  });

  it("401 shows the token modal", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { message: "unauthorized" } }), { status: 401 }));
    globalThis.fetch = fetchMock as any;
    const store = useAuthStore();
    await expect(toolApi.list()).rejects.toThrow(ApiError);
    expect(store.modalVisible).toBe(true);
  });

  it("sends Bearer header when token exists", async () => {
    localStorage.setItem("kmcp_token", "tk-tools-123");
    const fetchMock = mockJson(200, { tools: [] });
    await toolApi.list();
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({ Authorization: "Bearer tk-tools-123" });
  });

  it("never puts token in URL or query string", async () => {
    localStorage.setItem("kmcp_token", "secret-token");
    const fetchMock = mockJson(200, { tools: [] });
    await toolApi.list({ visibility: "agent_callable" });
    const [url] = fetchMock.mock.calls[0];
    expect(url).not.toContain("secret-token");
    expect(url).not.toContain("token");
    expect(url).toContain("visibility=agent_callable");
  });
});
