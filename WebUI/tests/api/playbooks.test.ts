import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { playbookApi } from "@/api/playbooks";
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

describe("playbookApi", () => {
  beforeEach(() => {
    localStorage.removeItem("kmcp_token");
    const store = useAuthStore();
    store.hideModal();
  });

  afterEach(() => {
    localStorage.removeItem("kmcp_token");
    vi.restoreAllMocks();
  });

  it("lists playbooks GET /api/playbooks", async () => {
    const fetchMock = mockJson(200, { playbooks: [], limit: 10, offset: 0 });
    const res = await playbookApi.list();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks`);
    expect(res).toEqual({ playbooks: [], limit: 10, offset: 0 });
  });

  it("lists playbooks with query params", async () => {
    const fetchMock = mockJson(200, { playbooks: [], limit: 5, offset: 0 });
    await playbookApi.list({ status: "draft", limit: 5, offset: "0" });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks?status=draft&limit=5&offset=0`);
  });

  it("creates a playbook POST /api/playbooks", async () => {
    const fetchMock = mockJson(201, { playbook_id: "pb_1", name: "New" });
    const payload = { playbook_id: "pb_1", name: "New", category: "recon" };
    const res = await playbookApi.create(payload);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify(payload));
    expect(res).toEqual({ playbook_id: "pb_1", name: "New" });
  });

  it("gets playbook definition GET .../definition", async () => {
    const fetchMock = mockJson(200, { definition: { name: "p", version: "1", steps: [] }, draft: false });
    const res = await playbookApi.getDefinition("pb_1");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/pb_1/definition`);
    expect(res.draft).toBe(false);
    expect(res.definition.steps).toEqual([]);
  });

  it("updates definition PUT .../definition", async () => {
    const fetchMock = mockJson(200, { playbook_id: "pb_1", valid: true });
    const def = { name: "p", version: "1", steps: [] };
    const res = await playbookApi.putDefinition("pb_1", def);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/pb_1/definition`);
    expect(init?.method).toBe("PUT");
    expect(init?.body).toBe(JSON.stringify({ definition: def }));
    expect(res.valid).toBe(true);
  });

  it("validates definition POST .../validate-definition", async () => {
    const fetchMock = mockJson(200, { valid: true, details: [] });
    const def = { name: "p", version: "1", steps: [] };
    const res = await playbookApi.validateDefinition("pb_1", def);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/pb_1/validate-definition`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ definition: def }));
    expect(res.valid).toBe(true);
  });

  it("publishes POST .../publish", async () => {
    const fetchMock = mockJson(200, { playbook_id: "pb_1", version_id: "v_1", status: "published" });
    const payload = { definition: { name: "p", version: "1", steps: [] }, version: "1.0.0" };
    const res = await playbookApi.publish("pb_1", payload);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/pb_1/publish`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify(payload));
    expect(res.status).toBe("published");
  });

  it("deletes DELETE /api/playbooks/:id", async () => {
    const fetchMock = mockJson(200, { status: "deleted" });
    const res = await playbookApi.delete("pb_1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/pb_1`);
    expect(init?.method).toBe("DELETE");
    expect(res.status).toBe("deleted");
  });

  it("imports POST /api/playbooks/import", async () => {
    const fetchMock = mockJson(200, { status: "imported", playbook_id: "pb_2" });
    const pkg = { playbook_id: "pb_2", name: "p", version: "1", definition: { name: "p", version: "1", steps: [] } };
    const res = await playbookApi.import({ package: pkg });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/import`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ package: pkg }));
    expect(res.playbook_id).toBe("pb_2");
  });

  it("exports GET /api/playbooks/:id/export", async () => {
    const fetchMock = mockJson(200, { playbook_id: "pb_1", name: "p", version: "1", definition: { name: "p", version: "1", steps: [] } });
    const res = await playbookApi.export("pb_1");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/pb_1/export`);
    expect(res.name).toBe("p");
  });

  it("lists versions GET .../versions", async () => {
    const fetchMock = mockJson(200, { versions: [{ version_id: "v_1", version: "1.0" }] });
    const res = await playbookApi.listVersions("pb_1");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/pb_1/versions`);
    expect(res.versions).toHaveLength(1);
  });

  it("rolls back POST .../rollback", async () => {
    const fetchMock = mockJson(200, { status: "rolled_back", version_id: "v_1" });
    const res = await playbookApi.rollback("pb_1", { version_id: "v_1" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE}/playbooks/pb_1/rollback`);
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ version_id: "v_1" }));
    expect(res.status).toBe("rolled_back");
  });

  it("401 shows the token modal", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { message: "unauthorized" } }), { status: 401 }));
    globalThis.fetch = fetchMock as any;
    const store = useAuthStore();
    await expect(playbookApi.list()).rejects.toThrow(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(store.modalVisible).toBe(true);
  });

  it("sends Bearer header when token exists", async () => {
    localStorage.setItem("kmcp_token", "tk-abc-123");
    const fetchMock = mockJson(200, { playbooks: [] });
    await playbookApi.list();
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.headers).toMatchObject({ Authorization: "Bearer tk-abc-123" });
  });

  it("never puts token in URL or query string", async () => {
    localStorage.setItem("kmcp_token", "secret-token");
    const fetchMock = mockJson(200, { playbooks: [] });
    await playbookApi.list({ status: "draft" });
    const [url] = fetchMock.mock.calls[0];
    expect(url).not.toContain("secret-token");
    expect(url).not.toContain("token");
    expect(url).toContain("status=draft");
  });
});
