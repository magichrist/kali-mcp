/*
 * Playbook API service.
 * Mirrors studio/api.py playbook routes.
 */

import { api } from "@/api/client";
import type {
  Playbook,
  PlaybookListResponse,
  PlaybookDetail,
  PlaybookDefinition,
  DefinitionResponse,
  PublishRequest,
  PublishResponse,
  Version,
  VersionsResponse,
  RollbackRequest,
  RollbackResponse,
  ExportPackage,
  ImportRequest,
  ImportResponse,
  ValidationResponse,
  CreatePlaybookRequest,
} from "@/api/types";

export const playbookApi = {
  /** GET /api/playbooks */
  list(params?: { status?: string; limit?: number; offset?: string }): Promise<PlaybookListResponse> {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    if (params?.offset !== undefined) qs.set("offset", params.offset);
    const path = qs.toString() ? `/playbooks?${qs.toString()}` : "/playbooks";
    return api<PlaybookListResponse>(path);
  },

  /** GET /api/playbooks/{id} */
  get(id: string): Promise<PlaybookDetail> {
    return api<PlaybookDetail>(`/playbooks/${encodeURIComponent(id)}`);
  },

  /** POST /api/playbooks */
  create(payload: CreatePlaybookRequest): Promise<Playbook> {
    return api<Playbook>("/playbooks", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** DELETE /api/playbooks/{id} */
  delete(id: string): Promise<{ status: string }> {
    return api<{ status: string }>(`/playbooks/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },

  /** PUT /api/playbooks/{id}/definition — save draft */
  putDefinition(id: string, definition: PlaybookDefinition): Promise<{ playbook_id: string; valid: boolean }> {
    return api(`/playbooks/${encodeURIComponent(id)}/definition`, {
      method: "PUT",
      body: JSON.stringify({ definition }),
    });
  },

  /** GET /api/playbooks/{id}/definition */
  getDefinition(id: string): Promise<DefinitionResponse> {
    return api<DefinitionResponse>(`/playbooks/${encodeURIComponent(id)}/definition`);
  },

  /** POST /api/playbooks/{id}/publish */
  publish(id: string, payload: PublishRequest): Promise<PublishResponse> {
    return api<PublishResponse>(`/playbooks/${encodeURIComponent(id)}/publish`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** POST /api/playbooks/{id}/validate-definition */
  validateDefinition(id: string, definition: PlaybookDefinition): Promise<ValidationResponse> {
    return api<ValidationResponse>(`/playbooks/${encodeURIComponent(id)}/validate-definition`, {
      method: "POST",
      body: JSON.stringify({ definition }),
    });
  },

  /** GET /api/playbooks/{id}/versions */
  listVersions(id: string): Promise<VersionsResponse> {
    return api<VersionsResponse>(`/playbooks/${encodeURIComponent(id)}/versions`);
  },

  /** POST /api/playbooks/{id}/rollback */
  rollback(id: string, payload: RollbackRequest): Promise<RollbackResponse> {
    return api<RollbackResponse>(`/playbooks/${encodeURIComponent(id)}/rollback`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** GET /api/playbooks/{id}/export */
  export(id: string): Promise<ExportPackage> {
    return api<ExportPackage>(`/playbooks/${encodeURIComponent(id)}/export`);
  },

  /** POST /api/playbooks/import */
  import(payload: ImportRequest): Promise<ImportResponse> {
    return api<ImportResponse>("/playbooks/import", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};
