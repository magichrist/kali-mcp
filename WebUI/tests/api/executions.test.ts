import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { executionApi } from "@/api/executions";
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

describe("executionApi", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("lists executions GET /api/executions", async () => {
    const fetchMock = mockJson(200, { executions: [], limit: 10, offset: 0 });
    const res = await executionApi.list();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/executions`);
    expect(res.executions).toEqual([]);
  });

  it("lists executions with query params", async () => {
    const fetchMock = mockJson(200, { executions: [], limit: 5, offset: 0 });
    await executionApi.list({ status: "running", playbook_id: "pb_1", limit: 5, offset: 0 });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/executions?status=running&playbook_id=pb_1&limit=5&offset=0`);
  });

  it("starts execution POST /api/executions", async () => {
    const fetchMock = mockJson(201, { execution_id: "ex_1" });
    const payload = { playbook_id: "pb_1", inputs: { target: "127.0.0.1" }, debug: false };
    const res = await executionApi.start(payload);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/executions`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify(payload));
    expect(res.execution_id).toBe("ex_1");
  });

  it("gets execution detail GET /api/executions/:id", async () => {
    const fetchMock = mockJson(200, { execution: { execution_id: "ex_1", playbook_id: "pb_1", status: "completed", steps: [], artifacts: [] } });
    const res = await executionApi.get("ex_1");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/executions/ex_1`);
    expect(res.execution.status).toBe("completed");
  });

  it("cancels execution POST .../cancel", async () => {
    const fetchMock = mockJson(200, { status: "cancelling" });
    const res = await executionApi.cancel("ex_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/executions/ex_1/cancel`);
    expect(init?.method).toBe("POST");
    expect(res.status).toBe("cancelling");
  });

  it("resumes execution POST .../resume", async () => {
    const fetchMock = mockJson(200, { status: "resuming" });
    const res = await executionApi.resume("ex_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/executions/ex_1/resume`);
    expect(init?.method).toBe("POST");
    expect(res.status).toBe("resuming");
  });

  it("401 shows the token modal", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { message: "unauthorized" } }), { status: 401 }));
    globalThis.fetch = fetchMock as any;
    const store = useAuthStore();
    await expect(executionApi.get("ex_1")).rejects.toThrow(ApiError);
    expect(store.modalVisible).toBe(true);
  });

  it("sends Bearer header when token exists", async () => {
    localStorage.setItem("kmcp_token", "tk-exec-123");
    const fetchMock = mockJson(200, { executions: [] });
    await executionApi.list();
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({ Authorization: "Bearer tk-exec-123" });
  });

  it("never puts token in URL or query string", async () => {
    localStorage.setItem("kmcp_token", "secret-token");
    const fetchMock = mockJson(200, { executions: [] });
    await executionApi.list({ status: "running" });
    const [url] = fetchMock.mock.calls[0];
    expect(url).not.toContain("secret-token");
    expect(url).not.toContain("token");
    expect(url).toContain("status=running");
  });
});
