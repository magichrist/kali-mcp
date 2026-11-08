/* API types for the Playbook Studio client.
 * Mirrors the contracts exposed by src/kali_mcp/studio/api.py.
 * Types also declared in @/api/types (Plan 1) are intentionally NOT
 * re-declared here — this file adds only the types unique to the
 * client convenience functions.
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
// Overview
// ═════════════════════════════════════════════════════════════════════

export interface RecentExecutionSummary {
  execution_id: string;
  playbook_id?: string;
  status: string;
  started_at?: string;
  completed_at?: string;
  trigger?: string;
  debug?: boolean;
}

export interface RecentFindingSummary {
  port_state?: string;
  tool?: string;
  severity?: string;
  test_name?: string;
  status?: string;
  checkname?: string;
  validation_status?: string;
  created_at?: string;
}

export interface OverviewResponse {
  playbooks: { total: number; by_status: Record<string, number> };
  executions: { total: number; by_status: Record<string, number> };
  tools: { total: number; by_visibility: Record<string, number> };
  findings: { total: number; by_severity: Record<string, number> };
  connections: { total: number; healthy: number };
  agents: { total: number };
  recent_executions: RecentExecutionSummary[];
  recent_findings: RecentFindingSummary[];
}

// ═════════════════════════════════════════════════════════════════════
// Playbooks
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
  filter?: { type: "grep" | "regex" | "none"; pattern?: string; first_only?: boolean };
  when?: string;
  checkpoint?: boolean;
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

export interface ValidateDefinitionResult {
  valid: boolean;
  details?: unknown[];
  findings?: unknown[];
}

export interface CreatePlaybookPayload {
  playbook_id: string;
  name: string;
  category?: string;
  description?: string;
}

// ═════════════════════════════════════════════════════════════════════
// Executions
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

export interface StartExecutionPayload {
  playbook_id: string;
  inputs?: Record<string, unknown>;
  debug?: boolean;
  trigger?: string;
}

export interface StartExecutionResponse {
  execution?: { execution_id: string };
  execution_id?: string;
}

export interface CancelResumeResponse {
  status: string;
}

// ═════════════════════════════════════════════════════════════════════
// Tools
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

export interface ToolVisibilityPayload {
  visibility: Visibility;
}

// ═════════════════════════════════════════════════════════════════════
// Connections
// ═════════════════════════════════════════════════════════════════════

export type Transport = "sse" | "streamable-http" | "stdio";

export interface ConnectionImportedTool {
  tool_id: string;
  visibility: Visibility;
}

export interface Connection {
  connection_id: string;
  name?: string;
  transport: Transport;
  endpoint_url?: string;
  command?: string;
  health_status?: string;
  enabled?: boolean;
  imported_tool_count?: number;
  imported_tools?: ConnectionImportedTool[];
  [key: string]: unknown;
}

export interface ConnectionListResponse {
  connections: Connection[];
  count: number;
}

export interface ConnectionDetailResponse {
  connection: Connection;
}

export interface CreateConnectionPayload {
  connection_id: string;
  name: string;
  transport: Transport;
  description?: string;
  endpoint_url?: string;
  command?: string;
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
  imported_tools: ConnectionImportedTool[];
  count: number;
}

// ═════════════════════════════════════════════════════════════════════
// Agents
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

export interface CreateAgentPayload {
  profile_id: string;
  name: string;
  description?: string;
}

export interface AgentPermissionRow {
  profile_id?: string;
  tool_id: string;
  granted?: boolean;
  granted_at?: string;
}

export interface AgentAssignmentRow {
  profile_id?: string;
  playbook_id: string;
  granted?: boolean;
  granted_at?: string;
}

export interface AgentEffectiveCatalog {
  tools?: unknown[];
  playbooks?: unknown[];
}

export interface AgentDetailResponse {
  agent: Agent;
  effective_catalog: AgentEffectiveCatalog;
  permissions: AgentPermissionRow[];
  assignments: AgentAssignmentRow[];
}

// ═════════════════════════════════════════════════════════════════════
// Server
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

// ═════════════════════════════════════════════════════════════════════
// Findings
// ═════════════════════════════════════════════════════════════════════

export interface Finding {
  test_name?: string;
  checkname?: string;
  name?: string;
  severity?: string;
  tool?: string;
  status?: string;
  validation_status?: string;
  target?: string;
  created_at?: string;
  port_state?: string;
  command?: string;
  findings_count?: number;
  [key: string]: unknown;
}

export interface FindingsResponse {
  findings: Finding[];
  count: number;
  limit: number;
  offset: number;
}
