/*
 * Tool Registry API service.
 * Mirrors studio/api.py tool routes.
 */

import { api } from "@/api/client";
import type { Tool, ToolListResponse, VisibilityRequest, VisibilityResponse } from "@/api/types";

export const toolApi = {
  /** GET /api/tools */
  list(params?: { limit?: number; visibility?: string; enabled?: string }): Promise<ToolListResponse> {
    const qs = new URLSearchParams();
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    if (params?.visibility) qs.set("visibility", params.visibility);
    if (params?.enabled !== undefined) qs.set("enabled", params.enabled);
    const path = qs.toString() ? `/tools?${qs.toString()}` : "/tools";
    return api<ToolListResponse>(path);
  },

  /** PUT /api/tools/{id}/visibility */
  setVisibility(id: string, payload: VisibilityRequest): Promise<VisibilityResponse> {
    return api<VisibilityResponse>(`/tools/${encodeURIComponent(id)}/visibility`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
};
