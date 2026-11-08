export type StepType =
  | "tool" | "shell" | "scope_check" | "finding_correlation" | "assessment_report" | "custom";
export const STEP_TYPES: StepType[] = ["tool","shell","scope_check","finding_correlation","assessment_report","custom"];
export type ViewMode = "graph" | "dsl";
export type InspectTab = "general" | "inputs" | "outputs" | "advanced";
export interface GraphPos { [stepId: string]: { x: number; y: number }; }
export interface RunState { [stepId: string]: "pending" | "running" | "completed" | "failed" | "cancelled"; }
export interface StepResult { outputs?: unknown; error?: string; tool_id?: string; }
export interface StepResults { [stepId: string]: StepResult; }
export const NODE_W = 280; export const NODE_H = 140; export const X_GAP = 360; export const Y_GAP = 200;
export const LAYOUT_PAD_X = 40; export const LAYOUT_PAD_Y = 40;
export const TYPE_ICONS: Record<StepType, { cls: string; glyph: string; color: string }> = {
  tool: { cls: "scan", glyph: "◎", color: "#f4c779" },
  shell: { cls: "cmd", glyph: "❯", color: "#f18e8e" },
  scope_check: { cls: "dns", glyph: "✓", color: "#8bd6a8" },
  finding_correlation: { cls: "web", glyph: "⇄", color: "#8db9ff" },
  assessment_report: { cls: "out", glyph: "▤", color: "#8bd8dc" },
  custom: { cls: "mod", glyph: "▣", color: "#c4a5ff" },
};
export const RUN_STATUS_COLOR: Record<string, string> = {
  completed: "#35b37a", ok: "#35b37a", running: "#f4c779", pending: "#f4c779",
  failed: "#f18e8e", cancelled: "#f18e8e",
};
export const HISTORY_MAX = 40;
