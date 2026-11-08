/*
 * Execution API service.
 * Mirrors studio/api.py execution routes.
 */

import { api } from "@/api/client";
import type {
  Execution,
  ExecutionListResponse,
  ExecutionDetailResponse,
  ExecutionStep,
  ExecutionArtifact,
  StartExecutionRequest,
  StartExecutionResponse,
} from "@/api/types";

export const executionApi = {
  /** GET /api/executions */
  list(params?: { status?: string; playbook_id?: string; limit?: number; offset?: number }): Promise<ExecutionListResponse> {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.playbook_id) qs.set("playbook_id", params.playbook_id);
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    if (params?.offset !== undefined) qs.set("offset", String(params.offset));
    const path = qs.toString() ? `/executions?${qs.toString()}` : "/executions";
    return api<ExecutionListResponse>(path);
  },

  /** POST /api/executions */
  start(payload: StartExecutionRequest): Promise<StartExecutionResponse> {
    return api<StartExecutionResponse>("/executions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** GET /api/executions/{id} */
  get(id: string): Promise<ExecutionDetailResponse> {
    return api<ExecutionDetailResponse>(`/executions/${encodeURIComponent(id)}`);
  },

  /** POST /api/executions/{id}/cancel */
  cancel(id: string): Promise<{ status: string }> {
    return api<{ status: string }>(`/executions/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    });
  },

  /** POST /api/executions/{id}/resume */
  resume(id: string): Promise<{ status: string }> {
    return api<{ status: string }>(`/executions/${encodeURIComponent(id)}/resume`, {
      method: "POST",
    });
  },
};
