/*
 * MCP Connections API service.
 * Mirrors studio/api.py connection routes.
 */

import { api } from "@/api/client";
import type {
  Connection,
  ConnectionListResponse,
  ConnectionDetailResponse,
  CreateConnectionRequest,
  TestConnectionResponse,
  DiscoverConnectionResponse,
} from "@/api/types";

export const connectionApi = {
  /** GET /api/connections */
  list(): Promise<ConnectionListResponse> {
    return api<ConnectionListResponse>("/connections");
  },

  /** POST /api/connections */
  create(payload: CreateConnectionRequest): Promise<Connection> {
    return api<Connection>("/connections", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** GET /api/connections/{id} */
  get(id: string): Promise<ConnectionDetailResponse> {
    return api<ConnectionDetailResponse>(`/connections/${encodeURIComponent(id)}`);
  },

  /** DELETE /api/connections/{id} */
  delete(id: string): Promise<{ status: string }> {
    return api<{ status: string }>(`/connections/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },

  /** POST /api/connections/{id}/test */
  test(id: string): Promise<TestConnectionResponse> {
    return api<TestConnectionResponse>(`/connections/${encodeURIComponent(id)}/test`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  /** POST /api/connections/{id}/discover */
  discover(id: string): Promise<DiscoverConnectionResponse> {
    return api<DiscoverConnectionResponse>(`/connections/${encodeURIComponent(id)}/discover`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },
};
