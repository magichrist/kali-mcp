/*
 * Agent Profiles API service.
 * Mirrors studio/api.py agent routes.
 */

import { api } from "@/api/client";
import type {
  Agent,
  AgentListResponse,
  CreateAgentRequest,
  AgentDetailResponse,
  GrantRevokeResponse,
} from "@/api/types";

export const agentApi = {
  /** GET /api/agents */
  list(): Promise<AgentListResponse> {
    return api<AgentListResponse>("/agents");
  },

  /** POST /api/agents */
  create(payload: CreateAgentRequest): Promise<AgentDetailResponse> {
    return api<AgentDetailResponse>("/agents", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** GET /api/agents/{id} */
  get(id: string): Promise<AgentDetailResponse> {
    return api<AgentDetailResponse>(`/agents/${encodeURIComponent(id)}`);
  },

  /** DELETE /api/agents/{id} */
  delete(id: string): Promise<{ status: string }> {
    return api<{ status: string }>(`/agents/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },

  /** PUT /api/agents/{id}/tools/{tool_id} */
  grantTool(profileId: string, toolId: string): Promise<GrantRevokeResponse> {
    return api<GrantRevokeResponse>(
      `/agents/${encodeURIComponent(profileId)}/tools/${encodeURIComponent(toolId)}`,
      { method: "PUT", body: JSON.stringify({}) },
    );
  },

  /** DELETE /api/agents/{id}/tools/{tool_id} */
  revokeTool(profileId: string, toolId: string): Promise<GrantRevokeResponse> {
    return api<GrantRevokeResponse>(
      `/agents/${encodeURIComponent(profileId)}/tools/${encodeURIComponent(toolId)}`,
      { method: "DELETE" },
    );
  },

  /** PUT /api/agents/{id}/playbooks/{playbook_id} */
  assignPlaybook(profileId: string, playbookId: string): Promise<GrantRevokeResponse> {
    return api<GrantRevokeResponse>(
      `/agents/${encodeURIComponent(profileId)}/playbooks/${encodeURIComponent(playbookId)}`,
      { method: "PUT", body: JSON.stringify({}) },
    );
  },

  /** DELETE /api/agents/{id}/playbooks/{playbook_id} */
  unassignPlaybook(profileId: string, playbookId: string): Promise<GrantRevokeResponse> {
    return api<GrantRevokeResponse>(
      `/agents/${encodeURIComponent(profileId)}/playbooks/${encodeURIComponent(playbookId)}`,
      { method: "DELETE" },
    );
  },
};
