/* Centralized API client for the Playbook Studio.
 * Single source of truth for all /api/* requests. No raw fetch() elsewhere.
 * Mirrors the existing vanilla app.js auth behavior:
 *   - Bearer token from localStorage key "kmcp_token"
 *   - 401 -> onUnauthorized handlers (App shows the token modal)
 *   - JSON serialization / consistent error normalization
 */

import type {
  AgentDetailResponse,
  AgentListResponse,
  ApiErrorBody,
  CancelResumeResponse,
  ConnectionDetailResponse,
  ConnectionListResponse,
  CreateAgentPayload,
  CreateConnectionPayload,
  CreatePlaybookPayload,
  DiscoverConnectionResponse,
  ExecutionDetailResponse,
  ExecutionListResponse,
  FindingsResponse,
  OverviewResponse,
  PlaybookDefinition,
  PlaybookDetail,
  PlaybookListResponse,
  ServerInfo,
  StartExecutionPayload,
  StartExecutionResponse,
  TestConnectionResponse,
  ToolListResponse,
} from "@/types/api";

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";
const TOKEN_KEY = "kmcp_token";

export class ApiError extends Error {
  status?: number;
  body?: unknown;
  constructor(message: string, status?: number, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/* 401 channel: pages/stores register a handler to show the token modal. */
type UnauthHandler = () => void | Promise<void>;
const unauthHandlers = new Set<UnauthHandler>();

export function onUnauthorized(handler: UnauthHandler) {
  unauthHandlers.add(handler);
  return () => unauthHandlers.delete(handler);
}

export function getToken(): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(value: string) {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(TOKEN_KEY, value);
  }
}

export function clearToken() {
  if (typeof localStorage !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
  }
}

async function parseBody(res: Response): Promise<unknown> {
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    try {
      return await res.json();
    } catch {
      return {};
    }
  }
  return await res.text().catch(() => null);
}

export async function apiRequest(
  path: string,
  opts: RequestInit = {},
): Promise<unknown> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string> | undefined),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });

  if (res.status === 401) {
    for (const h of unauthHandlers) {
      try { await h(); } catch { /* no-op */ }
    }
    throw new ApiError("401 Unauthorized — API token required", 401);
  }

  const body = await parseBody(res);
  if (!res.ok) {
    const rawErr = (body as ApiErrorBody)?.error;
    const msg =
      rawErr && typeof rawErr === "object" && "message" in rawErr
        ? (rawErr as { message: string }).message
        : String(rawErr ?? `${res.status} ${res.statusText}`);
    throw new ApiError(msg, res.status, body);
  }
  return body;
}

/* Typed request wrapper used by the api service modules. */
export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  return apiRequest(path, opts) as Promise<T>;
}

/* Low-level wrappers used by the api service modules. */
export function get(path: string, opts?: RequestInit) {
  return apiRequest(path, { ...opts, method: "GET" });
}

export function post(path: string, body?: unknown, opts?: RequestInit) {
  return apiRequest(path, {
    ...opts,
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function put(path: string, body?: unknown, opts?: RequestInit) {
  return apiRequest(path, {
    ...opts,
    method: "PUT",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function del(path: string, opts?: RequestInit) {
  return apiRequest(path, { ...opts, method: "DELETE" });
}

/* ── Convenience service functions used by page components ── */

/* Overview */
export async function fetchOverview(): Promise<OverviewResponse> {
  return apiRequest("/overview") as Promise<OverviewResponse>;
}

/* Playbooks */
export async function fetchPlaybooks(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<PlaybookListResponse> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  if (params?.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString() ? `?${qs}` : "";
  return apiRequest(`/playbooks${q}`) as Promise<PlaybookListResponse>;
}

export async function fetchPlaybook(id: string): Promise<PlaybookDetail> {
  return apiRequest(`/playbooks/${encodeURIComponent(id)}`) as Promise<PlaybookDetail>;
}

export async function fetchPlaybookDefinition(id: string): Promise<PlaybookDefinition> {
  return apiRequest(`/playbooks/${encodeURIComponent(id)}/definition`) as Promise<PlaybookDefinition>;
}

export async function createPlaybook(payload: CreatePlaybookPayload): Promise<unknown> {
  return apiRequest("/playbooks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importPlaybook(package_: unknown): Promise<unknown> {
  return apiRequest("/playbooks/import", {
    method: "POST",
    body: JSON.stringify({ package: package_ }),
  });
}

export async function deletePlaybook(id: string): Promise<unknown> {
  return apiRequest(`/playbooks/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/* Executions */
export async function fetchExecutions(params?: {
  status?: string;
  playbook_id?: string;
  limit?: number;
  offset?: number;
}): Promise<ExecutionListResponse> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.playbook_id) qs.set("playbook_id", params.playbook_id);
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  if (params?.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString() ? `?${qs}` : "";
  return apiRequest(`/executions${q}`) as Promise<ExecutionListResponse>;
}

export async function fetchExecution(id: string): Promise<ExecutionDetailResponse> {
  return apiRequest(`/executions/${encodeURIComponent(id)}`) as Promise<ExecutionDetailResponse>;
}

export async function startExecution(payload: StartExecutionPayload): Promise<StartExecutionResponse> {
  return apiRequest("/executions", {
    method: "POST",
    body: JSON.stringify(payload),
  }) as Promise<StartExecutionResponse>;
}

export async function cancelExecution(id: string): Promise<CancelResumeResponse> {
  return apiRequest(`/executions/${encodeURIComponent(id)}/cancel`, {
    method: "POST",
  }) as Promise<CancelResumeResponse>;
}

export async function resumeExecution(id: string): Promise<CancelResumeResponse> {
  return apiRequest(`/executions/${encodeURIComponent(id)}/resume`, {
    method: "POST",
  }) as Promise<CancelResumeResponse>;
}

/* Tools */
export async function fetchTools(params?: {
  visibility?: string;
  enabled?: boolean;
  limit?: number;
}): Promise<ToolListResponse> {
  const qs = new URLSearchParams();
  if (params?.visibility) qs.set("visibility", params.visibility);
  if (params?.enabled !== undefined) qs.set("enabled", String(params.enabled));
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  const q = qs.toString() ? `?${qs}` : "";
  return apiRequest(`/tools${q}`) as Promise<ToolListResponse>;
}

export async function setToolVisibility(id: string, visibility: string): Promise<unknown> {
  return apiRequest(`/tools/${encodeURIComponent(id)}/visibility`, {
    method: "PUT",
    body: JSON.stringify({ visibility }),
  });
}

/* Connections */
export async function fetchConnections(): Promise<ConnectionListResponse> {
  return apiRequest("/connections") as Promise<ConnectionListResponse>;
}

export async function fetchConnection(id: string): Promise<ConnectionDetailResponse> {
  return apiRequest(`/connections/${encodeURIComponent(id)}`) as Promise<ConnectionDetailResponse>;
}

export async function createConnection(payload: CreateConnectionPayload): Promise<unknown> {
  return apiRequest("/connections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function testConnection(id: string): Promise<TestConnectionResponse> {
  return apiRequest(`/connections/${encodeURIComponent(id)}/test`, {
    method: "POST",
  }) as Promise<TestConnectionResponse>;
}

export async function discoverConnection(id: string): Promise<DiscoverConnectionResponse> {
  return apiRequest(`/connections/${encodeURIComponent(id)}/discover`, {
    method: "POST",
    body: JSON.stringify({}),
  }) as Promise<DiscoverConnectionResponse>;
}

export async function deleteConnection(id: string): Promise<unknown> {
  return apiRequest(`/connections/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/* Agents */
export async function fetchAgents(): Promise<AgentListResponse> {
  return apiRequest("/agents") as Promise<AgentListResponse>;
}

export async function createAgent(payload: CreateAgentPayload): Promise<unknown> {
  return apiRequest("/agents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function fetchAgent(id: string): Promise<AgentDetailResponse> {
  return apiRequest(`/agents/${encodeURIComponent(id)}`) as Promise<AgentDetailResponse>;
}

export async function deleteAgent(id: string): Promise<unknown> {
  return apiRequest(`/agents/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function grantAgentTool(id: string, tool_id: string): Promise<unknown> {
  return apiRequest(`/agents/${encodeURIComponent(id)}/tools/${encodeURIComponent(tool_id)}`, {
    method: "PUT",
    body: JSON.stringify({}),
  });
}

export async function revokeAgentTool(id: string, tool_id: string): Promise<unknown> {
  return apiRequest(`/agents/${encodeURIComponent(id)}/tools/${encodeURIComponent(tool_id)}`, {
    method: "DELETE",
  });
}

export async function assignAgentPlaybook(id: string, playbook_id: string): Promise<unknown> {
  return apiRequest(`/agents/${encodeURIComponent(id)}/playbooks/${encodeURIComponent(playbook_id)}`, {
    method: "PUT",
    body: JSON.stringify({}),
  });
}

export async function unassignAgentPlaybook(id: string, playbook_id: string): Promise<unknown> {
  return apiRequest(`/agents/${encodeURIComponent(id)}/playbooks/${encodeURIComponent(playbook_id)}`, {
    method: "DELETE",
  });
}

/* Findings */
export async function fetchFindings(params?: {
  severity?: string;
  target?: string;
  tool?: string;
  limit?: number;
  offset?: number;
}): Promise<FindingsResponse> {
  const qs = new URLSearchParams();
  if (params?.severity && params.severity !== "all") qs.set("severity", params.severity);
  if (params?.target) qs.set("target", params.target);
  if (params?.tool) qs.set("tool", params.tool);
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  if (params?.offset !== undefined) qs.set("offset", String(params.offset));
  const q = qs.toString() ? `?${qs}` : "";
  return apiRequest(`/findings${q}`) as Promise<FindingsResponse>;
}

/* Server */
export async function fetchServerInfo(): Promise<ServerInfo> {
  return apiRequest("/server") as Promise<ServerInfo>;
}
