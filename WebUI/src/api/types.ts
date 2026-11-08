/*
 * TypeScript interfaces for the Kali-MCP Studio API.
 * These mirror the contracts exposed by src/kali_mcp/studio/api.py.
 * Do not invent endpoints or reshape responses without verifying api.py.
 */

// ═════════════════════════════════════════════════════════════════════
// Shared
// ═════════════════════════════════════════════════════════════════════

export type Visibility = "agent_callable" | "playbook_selectable" | "internal" | "hidden";

export interface ApiErrorBody {
  error?: string | { message: string };
  details?: unknown;
}

// ═════════════════════════════════════════════════════════════════════
// Playbooks
// GET/POST /api/playbooks ; GET/DELETE /api/playbooks/{id}
// PUT+GET /api/playbooks/{id}/definition
// POST /api/playbooks/{id}/publish (body {definition, version})
// POST /api/playbooks/{id}/validate-definition (body {definition})
// GET /api/playbooks/{id}/versions
// POST /api/playbooks/{id}/rollback (body {version_id})
// GET /api/playbooks/{id}/export
// POST /api/playbooks/import (body {package})
// ═════════════════════════════════════════════════════════════════════

export type StepType = "tool" | "shell" | "scope_check" | "finding_correlation" | "assessment_report" | "custom";

export interface PlaybookStep {
  id: string;
  type: StepType;
  tool?: string;
  command?: string;
  depends_on?: string[];
  inputs?: Record<string, string>;
  args?: Record<string, unknown>;
  filter?: {
    type: "grep" | "regex" | "none";
    pattern?: string;
    first_only?: boolean;
  };
  when?: string;
  checkpoint?: boolean;
  output_filter?: unknown;
  // Preserve any additional DSL fields the backend may emit.
  [key: string]: unknown;
}

export interface PlaybookDefinition {
  name: string;
  version: string;
  inputs?: Record<string, unknown>;
  steps: PlaybookStep[];
  execution?: { timeout: number; max_parallel: number };
  [key: string]: unknown;
}

export interface Playbook {
  playbook_id: string;
  name: string;
  description?: string;
  category?: string;
  status?: "draft" | "published";
  current_version_id?: string;
  created_at?: string;
  is_builtin?: number;
  draft_definition?: unknown;
  [key: string]: unknown;
}

export interface PlaybookListResponse {
  playbooks: Playbook[];
  limit: number;
  offset: number;
}

export interface PlaybookDetail {
  playbook_id: string;
  name: string;
  status?: "draft" | "published";
  current_version_id?: string;
  [key: string]: unknown;
}

export interface DefinitionResponse {
  definition: PlaybookDefinition | null;
  draft: boolean;
}

export interface PublishRequest {
  definition: PlaybookDefinition;
  version: string;
}

export interface PublishResponse {
  playbook_id: string;
  version_id: string;
  status: string;
}

export interface Version {
  version_id: string | number;
  version: string;
  created_at?: string;
  definition?: unknown;
}

export interface VersionsResponse {
  versions: Version[];
}

export interface RollbackRequest {
  version_id: string | number;
}

export interface RollbackResponse {
  status: string;
  version_id: string;
}

export interface ExportPackage {
  playbook_id: string;
  name: string;
  version: string;
  definition: PlaybookDefinition;
  exported_at?: string;
  [key: string]: unknown;
}

export interface ImportRequest {
  package: ExportPackage;
}

export interface ImportResponse {
  status: string;
  playbook_id?: string;
}

export interface ValidationResponse {
  valid: boolean;
  details?: unknown[];
}

export interface CreatePlaybookRequest {
  playbook_id: string;
  name: string;
  category?: string;
  description?: string;
}

// ═════════════════════════════════════════════════════════════════════
// Executions
// GET/POST /api/executions ; GET /api/executions/{id}
// POST /api/executions/{id}/cancel ; POST /api/executions/{id}/resume
// ═════════════════════════════════════════════════════════════════════

export interface ExecutionStep {
  step_id: string;
  tool_id?: string;
  status: string;
  outputs?: unknown;
  error?: string;
  started_at?: string;
  completed_at?: string;
  [key: string]: unknown;
}

export interface ExecutionArtifact {
  name?: string;
  artifact_id?: string;
  evidence_id?: string;
  category?: string;
  [key: string]: unknown;
}

export interface Execution {
  execution_id: string;
  playbook_id?: string;
  status: string;
  trigger?: string;
  debug?: boolean;
  started_at?: string;
  completed_at?: string;
  steps: ExecutionStep[];
  artifacts: ExecutionArtifact[];
  [key: string]: unknown;
}

export interface ExecutionListResponse {
  executions: Execution[];
  limit: number;
  offset: number;
}

export interface ExecutionDetailResponse {
  execution: Execution;
}

export interface StartExecutionRequest {
  playbook_id: string;
  inputs?: Record<string, unknown>;
  debug?: boolean;
  trigger?: string;
}

export interface StartExecutionResponse {
  execution?: { execution_id: string };
  execution_id?: string;
}

// ═════════════════════════════════════════════════════════════════════
// Tools
// GET /api/tools ; PUT /api/tools/{id}/visibility (body {visibility})
// ═════════════════════════════════════════════════════════════════════

export interface Tool {
  tool_id: string;
  name: string;
  description?: string;
  provider: string;
  visibility: Visibility;
  enabled: boolean;
  default_timeout?: number;
  input_schema?: unknown;
  [key: string]: unknown;
}

export interface ToolListResponse {
  tools: Tool[];
  count: number;
}

export interface VisibilityRequest {
  visibility: Visibility;
}

export interface VisibilityResponse {
  tool_id: string;
  visibility: Visibility;
}

// ═════════════════════════════════════════════════════════════════════
// Connections
// GET/POST /api/connections ; GET/DELETE /api/connections/{id}
// POST /api/connections/{id}/test ; POST /api/connections/{id}/discover
// ═════════════════════════════════════════════════════════════════════

export type Transport = "sse" | "streamable-http" | "stdio";

export interface Connection {
  connection_id: string;
  name?: string;
  transport: Transport;
  endpoint_url?: string;
  command?: string;
  health_status?: string;
  enabled?: boolean;
  imported_tool_count?: number;
  imported_tools?: Array<{ tool_id: string; visibility: Visibility }>;
  [key: string]: unknown;
}

export interface ConnectionListResponse {
  connections: Connection[];
  count: number;
}

export interface ConnectionDetailResponse {
  connection: Connection;
}

export interface CreateConnectionRequest {
  connection_id: string;
  name: string;
  transport: Transport;
  endpoint_url?: string;
  command?: string;
  description?: string;
  args?: unknown;
  auth_type?: string;
  auth_config?: unknown;
  enabled?: boolean;
}

export interface TestConnectionResponse {
  ok: boolean;
  healthy: boolean;
}

export interface DiscoverConnectionResponse {
  imported_tools: Array<{ tool_id: string; visibility: Visibility }>;
  count: number;
}

// ═════════════════════════════════════════════════════════════════════
// Agents
// GET/POST /api/agents ; GET/DELETE /api/agents/{id}
// PUT/DELETE /api/agents/{id}/tools/{tool_id}
// PUT/DELETE /api/agents/{id}/playbooks/{playbook_id}
// ═════════════════════════════════════════════════════════════════════

export interface Agent {
  profile_id: string;
  name?: string;
  description?: string;
  default_visibility?: Visibility;
  max_parallel_operations?: number;
  max_execution_seconds?: number;
  [key: string]: unknown;
}

export interface AgentListResponse {
  agents: Agent[];
}

export interface CreateAgentRequest {
  profile_id: string;
  name: string;
  description?: string;
}

export interface AgentDetailResponse {
  agent: Agent;
  effective_catalog: { tools: unknown[]; playbooks: unknown[] };
  permissions: Array<{ profile_id: string; tool_id: string; granted: boolean; granted_at?: string }>;
  assignments: Array<{ profile_id: string; playbook_id: string; granted: boolean; granted_at?: string }>;
}

export interface GrantRevokeResponse {
  profile_id: string;
  tool_id?: string;
  playbook_id?: string;
  granted?: boolean;
  revoked?: boolean;
  assigned?: boolean;
  unassigned?: boolean;
}

// ═════════════════════════════════════════════════════════════════════
// Server / Overview
// GET /api/server ; GET /api/overview
// ═════════════════════════════════════════════════════════════════════

export interface ServerInfo {
  db_path: string;
  db_exists: boolean;
  server_name: string;
  server_version: string;
  host: string;
  port: number;
  transport: string;
  auth_enabled: boolean;
  default_timeout: number;
  max_timeout: number;
  max_concurrent: number;
  debug: boolean;
}

export interface OverviewResponse {
  playbooks: { total: number; by_status: Record<string, number> };
  executions: { total: number; by_status: Record<string, number> };
  tools: { total: number; by_visibility: Record<string, number> };
  findings: { total: number; by_severity: Record<string, number> };
  connections: { total: number; healthy: number };
  agents: { total: number };
  recent_executions: Array<{
    execution_id: string;
    playbook_id?: string;
    status: string;
    started_at?: string;
  }>;
  recent_findings: Array<{
    port_state?: string;
    tool?: string;
    severity: string;
    test_name?: string;
  }>;
}
