import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { agentApi } from "@/api/agents";
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

describe("agentApi", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("lists agents GET /api/agents", async () => {
    const fetchMock = mockJson(200, { agents: [] });
    const res = await agentApi.list();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/agents`);
    expect(res.agents).toEqual([]);
  });

  it("creates agent POST /api/agents", async () => {
    const fetchMock = mockJson(201, { agent: { profile_id: "a_1", name: "Analyst" } });
    const payload = { profile_id: "a_1", name: "Analyst", description: "SOC agent" };
    const res = await agentApi.create(payload);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/agents`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify(payload));
    expect(res.agent.profile_id).toBe("a_1");
  });

  it("gets agent detail GET /api/agents/:id", async () => {
    const fetchMock = mockJson(200, { agent: { profile_id: "a_1", name: "Analyst" }, effective_catalog: { tools: [], playbooks: [] }, permissions: [], assignments: [] });
    const res = await agentApi.get("a_1");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/agents/a_1`);
    expect(res.agent.name).toBe("Analyst");
  });

  it("grants tool PUT /api/agents/:id/tools/:tool_id", async () => {
    const fetchMock = mockJson(200, { profile_id: "a_1", tool_id: "t_1", granted: true });
    const res = await agentApi.grantTool("a_1", "t_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/agents/a_1/tools/t_1`);
    expect(init?.method).toBe("PUT");
    expect(init?.body).toBe(JSON.stringify({}));
    expect(res.granted).toBe(true);
  });

  it("revokes tool DELETE /api/agents/:id/tools/:tool_id", async () => {
    const fetchMock = mockJson(200, { profile_id: "a_1", tool_id: "t_1", revoked: true });
    const res = await agentApi.revokeTool("a_1", "t_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/agents/a_1/tools/t_1`);
    expect(init?.method).toBe("DELETE");
    expect(res.revoked).toBe(true);
  });

  it("assigns playbook PUT /api/agents/:id/playbooks/:playbook_id", async () => {
    const fetchMock = mockJson(200, { profile_id: "a_1", playbook_id: "pb_1", assigned: true });
    const res = await agentApi.assignPlaybook("a_1", "pb_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/agents/a_1/playbooks/pb_1`);
    expect(init?.method).toBe("PUT");
    expect(init?.body).toBe(JSON.stringify({}));
    expect(res.assigned).toBe(true);
  });

  it("unassigns playbook DELETE /api/agents/:id/playbooks/:playbook_id", async () => {
    const fetchMock = mockJson(200, { profile_id: "a_1", playbook_id: "pb_1", unassigned: true });
    const res = await agentApi.unassignPlaybook("a_1", "pb_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/agents/a_1/playbooks/pb_1`);
    expect(init?.method).toBe("DELETE");
    expect(res.unassigned).toBe(true);
  });

  it("deletes agent DELETE /api/agents/:id", async () => {
    const fetchMock = mockJson(200, { status: "deleted" });
    const res = await agentApi.delete("a_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/agents/a_1`);
    expect(init?.method).toBe("DELETE");
    expect(res.status).toBe("deleted");
  });

  it("401 shows the token modal", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { message: "unauthorized" } }), { status: 401 }));
    globalThis.fetch = fetchMock as any;
    const store = useAuthStore();
    await expect(agentApi.get("a_1")).rejects.toThrow(ApiError);
    expect(store.modalVisible).toBe(true);
  });

  it("sends Bearer header when token exists", async () => {
    localStorage.setItem("kmcp_token", "tk-agent-123");
    const fetchMock = mockJson(200, { agents: [] });
    await agentApi.list();
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({ Authorization: "Bearer tk-agent-123" });
  });

  it("never puts token in URL or query string", async () => {
    localStorage.setItem("kmcp_token", "secret-token");
    const fetchMock = mockJson(200, { agents: [] });
    await agentApi.list();
    const [url] = fetchMock.mock.calls[0];
    expect(url).not.toContain("secret-token");
    expect(url).not.toContain("token");
  });
});
