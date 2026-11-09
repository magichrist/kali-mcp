/*
 * API barrel — single import point for all studio API service modules.
 * Page components import from here rather than from individual modules.
 */

export { playbookApi } from "@/api/playbooks";
export { executionApi } from "@/api/executions";
export { toolApi } from "@/api/tools";
export { connectionApi } from "@/api/connections";
export { agentApi } from "@/api/agents";

export type {
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
  Execution,
  ExecutionListResponse,
  ExecutionDetailResponse,
  ExecutionStep,
  ExecutionArtifact,
  StartExecutionRequest,
  StartExecutionResponse,
  Tool,
  ToolListResponse,
  VisibilityRequest,
  VisibilityResponse,
  Connection,
  ConnectionListResponse,
  ConnectionDetailResponse,
  CreateConnectionRequest,
  TestConnectionResponse,
  DiscoverConnectionResponse,
  Agent,
  AgentListResponse,
  CreateAgentRequest,
  AgentDetailResponse,
  GrantRevokeResponse,
  ServerInfo,
  OverviewResponse,
  Visibility,
  Transport,
  StepType,
  ApiErrorBody,
} from "@/api/types";

export { api, ApiError, API_BASE } from "@/api/client";
