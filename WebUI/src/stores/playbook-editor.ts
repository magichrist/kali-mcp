/*
 * Playbook editor store — single source of truth for the graph/DSL editor.
 *
 * Holds the canonical Playbook DSL (definition), the raw DSL text, layout
 * coordinates (graphPos, strictly separate from DSL semantics), selection,
 * view mode, execution state, and the undo/redo history.
 *
 * Graph ↔ DSL synchronization:
 *   * Every graph mutation updates `definition.steps` (the DSL) and re-serializes
 *     `rawDsl`, so graph and DSL are always in sync while the graph view is active.
 *   * Switching to DSL view captures graph → rawDsl.
 *   * Switching to graph view parses rawDsl → definition.
 *   * Dragging updates graphPos only; it never touches depends_on.
 */

import { defineStore, acceptHMRUpdate } from "pinia";
import { computed, ref } from "vue";
import type { Execution, ExecutionStep, PlaybookDefinition, PlaybookStep, Tool } from "@/types/api";
import { useGraphHistory } from "@/features/playbook-editor/composables/useGraphHistory";
import { useAutoLayout, type LayoutPoint } from "@/features/playbook-editor/composables/useAutoLayout";
import {
  validateDependencies,
  wouldCreateCycle,
  hasDuplicateEdge,
  type ValidationFinding,
} from "@/features/playbook-editor/composables/useGraphValidation";
import {
  definitionToGraph,
  graphToDefinition,
  collectRunInputNames,
  type VueFlowNodeLike,
  type VueFlowEdgeLike,
} from "@/features/playbook-editor/composables/useGraphSerialization";
import type { StepType } from "@/features/playbook-editor/types/graph";
import {
  fetchExecution,
  fetchPlaybook,
  fetchPlaybookDefinition,
  fetchTools,
  updatePlaybookDefinition,
  publishPlaybook,
  validateDefinition as apiValidateDefinition,
  startExecution,
} from "@/api/client";

export const EMPTY_DEFINITION: PlaybookDefinition = {
  name: "draft",
  version: "1.0.0",
  inputs: {},
  steps: [],
  execution: { timeout: 900, max_parallel: 4 },
};

function nextId(prefix: string, steps: PlaybookStep[]): string {
  let n = 1;
  let id: string;
  do { id = `${prefix}_${n++}`; } while (steps.some((s) => s.id === id));
  return id;
}

export const usePlaybookEditorStore = defineStore("playbookEditor", () => {
  /* ──────────────────── state ──────────────────── */
  const playbookId = ref<string | null>(null);
  const playbook = ref<any>(null);
  const definition = ref<PlaybookDefinition>({ ...EMPTY_DEFINITION });
  const rawDsl = ref("");
  const graphPos = ref<Record<string, LayoutPoint>>({});
  const view = ref<"graph" | "dsl">("graph");
  const selectedNodeId = ref<string | null>(null);
  const selectedEdgeId = ref<string | null>(null);
  const inspectorOpen = ref(true);
  const inspectTab = ref<"general" | "inputs" | "outputs" | "advanced">("general");
  const dslError = ref<{ message: string; line?: number; col?: number } | null>(null);
  const runStatus = ref<Record<string, string>>({});
  const stepResults = ref<Record<string, { outputs?: unknown; error?: string; tool_id?: string }>>({});
  /* Live execution polling state. */
  const pollingActive = ref(false);
  const pollingExecutionId = ref<string | null>(null);
  const executionStatus = ref<string | null>(null);
  const pollingInFlight = ref(false);
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  const dirty = ref(false);
  const tools = ref<Tool[]>([]);
  const loading = ref(false);

  const history = useGraphHistory({ maxDepth: 40 });

  /* ──────────────────── getters ──────────────────── */
  const nodes = computed<VueFlowNodeLike[]>(() => {
    const base = definitionToGraph(definition.value, graphPos.value);
    return base.nodes.map((n) => ({
      ...n,
      data: { step: n.data.step, __status: runStatus.value[n.id] },
    }));
  });
  const edges = computed<VueFlowEdgeLike[]>(() =>
    definitionToGraph(definition.value, graphPos.value).edges,
  );

  const selectedStep = computed<PlaybookStep | null>(() =>
    (definition.value.steps || []).find((s) => s.id === selectedNodeId.value) ?? null,
  );

  const validationFindings = computed<ValidationFinding[]>(() =>
    validateDependencies(definition.value.steps || []),
  );
  const isValid = computed(() => validationFindings.value.length === 0);

  /* ──────────────────── history snapshot ──────────────────── */
  function snapshot() {
    return {
      definition: JSON.parse(JSON.stringify(definition.value)),
      graphPos: JSON.parse(JSON.stringify(graphPos.value)),
      selectedNodeId: selectedNodeId.value,
      inspectTab: inspectTab.value,
      view: view.value,
      runStatus: JSON.parse(JSON.stringify(runStatus.value)),
      stepResults: JSON.parse(JSON.stringify(stepResults.value)),
    };
  }

  function restore(snap: any): void {
    definition.value = JSON.parse(JSON.stringify(snap.definition)) as PlaybookDefinition;
    graphPos.value = JSON.parse(JSON.stringify(snap.graphPos)) as Record<string, LayoutPoint>;
    selectedNodeId.value = snap.selectedNodeId ?? null;
    inspectTab.value = (snap.inspectTab as "general") ?? "general";
    view.value = (snap.view as "graph") ?? "graph";
    runStatus.value = JSON.parse(JSON.stringify(snap.runStatus)) as Record<string, string>;
    stepResults.value = JSON.parse(JSON.stringify(snap.stepResults)) as Record<
      string,
      { outputs?: unknown; error?: string; tool_id?: string }
    >;
    dirty.value = true;
  }

  function pushHistory(): void {
    history.push(snapshot());
  }

  /* ──────────────────── lifecycle ──────────────────── */
  async function loadPlaybook(id: string): Promise<void> {
    loading.value = true;
    try {
      const [pb, defRes] = await Promise.all([
        fetchPlaybook(id),
        fetchPlaybookDefinition(id).catch(() => ({ definition: null })),
      ]);
      playbookId.value = id;
      playbook.value = pb;
      const def = (defRes as any)?.definition ?? null;
      if (def && typeof def === "object" && Array.isArray(def.steps)) {
        setDefinition(def as PlaybookDefinition);
        rawDsl.value = JSON.stringify(def, null, 2);
      } else {
        setDefinition({ ...EMPTY_DEFINITION, name: id });
        rawDsl.value = JSON.stringify(EMPTY_DEFINITION, null, 2);
      }
      dslError.value = null;
      history.clear();
      dirty.value = false;
      selectedNodeId.value = null;
    } finally {
      loading.value = false;
    }
  }

  async function refreshTools(): Promise<void> {
    try {
      const res = await fetchTools({ limit: 500 });
      tools.value = (res as any)?.tools || [];
    } catch {
      /* tools optional for graph editing */
    }
  }

  /* ──────────────────── definition / DSL sync ──────────────────── */
  function setDefinition(def: PlaybookDefinition): void {
    definition.value = {
      ...EMPTY_DEFINITION,
      ...def,
      steps: Array.isArray(def.steps) ? def.steps.map(cloneStep) : [],
      execution: def.execution || EMPTY_DEFINITION.execution,
    };
    const nextPos: Record<string, LayoutPoint> = { ...graphPos.value };
    for (const s of definition.value.steps || []) {
      if (!nextPos[s.id]) nextPos[s.id] = { x: 0, y: 0 };
    }
    graphPos.value = nextPos;
    dirty.value = true;
    if (view.value === "graph") rawDsl.value = serializeDsl();
  }

  function cloneStep(step: PlaybookStep): PlaybookStep {
    return JSON.parse(JSON.stringify(step));
  }

  function serializeDsl(): string {
    try { return JSON.stringify(definition.value, null, 2); } catch { return rawDsl.value; }
  }

  /** Parse the raw DSL text into the definition. Returns false if invalid. */
  function parseRawDsl(): boolean {
    const text = rawDsl.value.trim();
    if (!text) {
      setDefinition({ ...EMPTY_DEFINITION, name: playbookId.value ?? "draft" });
      dslError.value = null;
      return true;
    }
    try {
      const parsed = JSON.parse(text);
      setDefinition(parsed as PlaybookDefinition);
      dslError.value = null;
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Invalid JSON";
      const lineMatch = (err as any)?.message?.match(/line (\d+)/);
      const colMatch = (err as any)?.message?.match(/column (\d+)/);
      dslError.value = { message, line: lineMatch ? Number(lineMatch[1]) : undefined, col: colMatch ? Number(colMatch[1]) : undefined };
      return false;
    }
  }

  /** Capture graph → rawDsl (never overwrites user-edited DSL text). */
  function captureToDsl(): void {
    if (view.value !== "graph") return;
    rawDsl.value = serializeDsl();
  }

  /* ──────────────────── view ──────────────────── */
  function setView(next: "graph" | "dsl"): void {
    if (next === view.value) return;
    if (view.value === "graph") captureToDsl();
    else if (!parseRawDsl()) return;
    view.value = next;
  }

  function toggleInspector(): void { inspectorOpen.value = !inspectorOpen.value; }

  /* ──────────────────── selection ──────────────────── */
  function setSelection(nodeId: string | null): void { selectedNodeId.value = nodeId; }
  function setInspectTab(tab: "general" | "inputs" | "outputs" | "advanced"): void { inspectTab.value = tab; }
  function removeSelectedNode(): void {
    if (selectedNodeId.value) removeStep(selectedNodeId.value);
  }

  /* ──────────────────── step mutations ──────────────────── */
  function addStep(step: PlaybookStep, focusTab: "general" | "inputs" = "general", pos?: LayoutPoint): void {
    pushHistory();
    definition.value.steps = [...(definition.value.steps || []), cloneStep(step)];
    graphPos.value[step.id] = pos ?? { x: 0, y: 0 };
    rawDsl.value = serializeDsl();
    selectedNodeId.value = step.id;
    inspectTab.value = focusTab;
    dirty.value = true;
  }

  function removeStep(id: string): void {
    pushHistory();
    definition.value.steps = (definition.value.steps || []).filter((s) => s.id !== id);
    for (const s of definition.value.steps || []) {
      if (Array.isArray(s.depends_on)) s.depends_on = s.depends_on.filter((d) => d !== id);
    }
    delete graphPos.value[id];
    rawDsl.value = serializeDsl();
    if (selectedNodeId.value === id) selectedNodeId.value = null;
    dirty.value = true;
  }

  function updateStep(id: string, patch: Partial<PlaybookStep>): void {
    pushHistory();
    const step = (definition.value.steps || []).find((s) => s.id === id);
    if (!step) return;
    Object.assign(step, patch);
    if (patch.id && patch.id !== id) {
      for (const s of definition.value.steps || []) {
        if (Array.isArray(s.depends_on)) {
        s.depends_on = s.depends_on.map((d) => (d === id ? patch.id : d)).filter((d): d is string => d !== undefined);
      }
      }
      if (graphPos.value[id]) { graphPos.value[patch.id] = graphPos.value[id]; delete graphPos.value[id]; }
    }
    rawDsl.value = serializeDsl();
    selectedNodeId.value = patch.id ?? id;
    dirty.value = true;
  }

  function setNodePosition(id: string, pos: LayoutPoint): void { graphPos.value[id] = { ...pos }; }

  function addToolStep(toolName?: string, pos?: LayoutPoint): void {
    const base = (toolName || "tool").replace(/[^a-zA-Z0-9_]/g, "_").slice(0, 24) || "tool";
    const step: PlaybookStep = { id: nextId(base, definition.value.steps || []), type: "tool", depends_on: [] };
    if (toolName) step.tool = toolName;
    addStep(step, "inputs", pos);
  }

  function addShellStep(pos?: LayoutPoint): void {
    addStep({ id: nextId("shell", definition.value.steps || []), type: "shell", command: "", inputs: {}, filter: { type: "grep", pattern: "" }, depends_on: [] }, "inputs", pos);
  }

  function addScopeStep(pos?: LayoutPoint): void {
    addStep({ id: nextId("scope", definition.value.steps || []), type: "scope_check", depends_on: [] }, "general", pos);
  }

  function addFindingStep(pos?: LayoutPoint): void {
    addStep({ id: nextId("corr", definition.value.steps || []), type: "finding_correlation", depends_on: [] }, "general", pos);
  }

  function addReportStep(pos?: LayoutPoint): void {
    addStep({ id: nextId("report", definition.value.steps || []), type: "assessment_report", depends_on: [] }, "general", pos);
  }

  function addCustomStep(pos?: LayoutPoint): void {
    addStep({ id: nextId("custom", definition.value.steps || []), type: "custom", depends_on: [] }, "general", pos);
  }

  /* ──────────────────── edges / dependencies ──────────────────── */
  function addEdge(sourceId: string, targetId: string): { ok: boolean; message?: string } {
    if (targetId === sourceId) return { ok: false, message: "A step cannot depend on itself." };
    if (wouldCreateCycle(definition.value.steps || [], sourceId, targetId)) {
      return { ok: false, message: `Connecting ${sourceId} → ${targetId} would create a cycle.` };
    }
    if (hasDuplicateEdge(definition.value.steps || [], sourceId, targetId)) {
      return { ok: false, message: `${targetId} already depends on ${sourceId}.` };
    }
    const step = (definition.value.steps || []).find((s) => s.id === targetId);
    if (!step) return { ok: false, message: "Target step not found." };
    pushHistory();
    step.depends_on = Array.isArray(step.depends_on) ? step.depends_on : [];
    if (!step.depends_on.includes(sourceId)) step.depends_on.push(sourceId);
    rawDsl.value = serializeDsl();
    dirty.value = true;
    return { ok: true };
  }

  function removeEdge(sourceId: string, targetId: string): void {
    pushHistory();
    const step = (definition.value.steps || []).find((s) => s.id === targetId);
    if (step && Array.isArray(step.depends_on)) step.depends_on = step.depends_on.filter((d) => d !== sourceId);
    rawDsl.value = serializeDsl();
    dirty.value = true;
  }

  /* ──────────────────── auto-layout ──────────────────── */
  function relayout(): void {
    pushHistory();
    graphPos.value = {};
    const { positions } = useAutoLayout().layoutSteps(definition.value.steps || [], {});
    graphPos.value = positions;
    rawDsl.value = serializeDsl();
    dirty.value = true;
  }

  /* ──────────────────── undo / redo ──────────────────── */
  function undo(): boolean {
    const result = history.undo(snapshot());
    if (!result) return false;
    restore(result.previous);
    return true;
  }

  function redo(): boolean {
    const result = history.redo(snapshot());
    if (!result) return false;
    restore(result.next);
    return true;
  }

  /* ──────────────────── execution state ──────────────────── */
  function setExecutionState(status: Record<string, string>, results: Record<string, { outputs?: unknown; error?: string; tool_id?: string }>): void {
    runStatus.value = status;
    stepResults.value = results;
  }
  function clearExecutionState(): void { runStatus.value = {}; stepResults.value = {}; }

  /* ──────────────────── live execution polling ──────────────────── */

  const TERMINAL_STATES = new Set(["completed", "failed", "cancelled"]);
  function isTerminalStatus(status: string): boolean { return TERMINAL_STATES.has(status); }

  /** Single poll of the execution detail. Returns true when polling should stop (terminal state). */
  async function pollExecutionOnce(executionId: string): Promise<boolean> {
    if (pollingInFlight.value) return false; /* only one poll in flight at a time */
    pollingInFlight.value = true;
    try {
      const data = await fetchExecution(executionId);
      const exec = (data as { execution?: Execution })?.execution;
      if (exec) {
        const nextStatus: Record<string, string> = { ...runStatus.value };
        const nextResults: Record<string, { outputs?: unknown; error?: string; tool_id?: string }> = { ...stepResults.value };
        for (const step of exec.steps || []) {
          const sid = String(step.step_id);
          nextStatus[sid] = step.status;
          nextResults[sid] = { outputs: step.outputs, error: step.error ?? undefined, tool_id: step.tool_id ?? undefined };
        }
        runStatus.value = nextStatus;
        stepResults.value = nextResults;
        executionStatus.value = exec.status ?? null;
        if (isTerminalStatus(exec.status)) return true;
      }
      return false;
    } catch {
      /* API / network failure: keep last known state and keep polling. */
      return false;
    } finally {
      pollingInFlight.value = false;
    }
  }

  /** Begin 1s interval polling for an execution. Stops on terminal state. */
  async function startPolling(executionId: string): Promise<void> {
    stopPolling();
    pollingExecutionId.value = executionId;
    executionStatus.value = null;
    pollingActive.value = true;
    /* Immediate first poll so status appears without waiting a full tick. */
    if (await pollExecutionOnce(executionId)) { stopPolling(); return; }
    pollTimer = setInterval(async () => {
      if (!pollingActive.value || pollingExecutionId.value !== executionId) return;
      if (await pollExecutionOnce(executionId)) stopPolling();
    }, 1000);
  }

  /** Clear the poll timer and deactivate polling. Safe to call when idle. */
  function stopPolling(): void {
    if (pollTimer !== null) { clearInterval(pollTimer); pollTimer = null; }
    pollingActive.value = false;
    pollingExecutionId.value = null;
    executionStatus.value = null;
  }

  /* ──────────────────── API actions ──────────────────── */
  async function validateDefinition(): Promise<{ valid: boolean; message: string }> {
    captureToDsl();
    try {
      const res = await apiValidateDefinition(playbookId.value!, JSON.parse(rawDsl.value));
      const valid = !!(res as any)?.valid;
      return { valid, message: valid ? "Definition valid" : "Validation failed" };
    } catch (err) { return { valid: false, message: err instanceof Error ? err.message : "Validation failed" }; }
  }

  async function saveDraft(): Promise<{ ok: boolean; message: string }> {
    captureToDsl();
    try {
      await updatePlaybookDefinition(playbookId.value!, JSON.parse(rawDsl.value));
      dirty.value = false;
      return { ok: true, message: "Draft saved" };
    } catch (err) { return { ok: false, message: err instanceof Error ? err.message : "Save failed" }; }
  }

  async function publish(): Promise<{ ok: boolean; message: string }> {
    captureToDsl();
    const def = JSON.parse(rawDsl.value);
    const version = def.version || "1.0.0";
    try {
      await publishPlaybook(playbookId.value!, def, version);
      dirty.value = false;
      return { ok: true, message: `Published ${version}` };
    } catch (err) { return { ok: false, message: err instanceof Error ? err.message : "Publish failed" }; }
  }

  async function runTest(inputs: Record<string, unknown>, debug = true): Promise<{ ok: boolean; executionId?: string; message: string }> {
    captureToDsl();
    try {
      const res = await startExecution({ playbook_id: playbookId.value!, inputs, debug, trigger: "studio" });
      const executionId = (res as any)?.execution?.execution_id || (res as any)?.execution_id;
      return { ok: true, executionId, message: `Run started${executionId ? `: ${executionId}` : ""}` };
    } catch (err) { return { ok: false, message: err instanceof Error ? err.message : "Run failed" }; }
  }

  function toolForName(name: string): Tool | undefined {
    return tools.value.find((t) => String(t.name || "").toLowerCase() === String(name).toLowerCase());
  }
  function runInputNames(): string[] { return collectRunInputNames(definition.value); }

  return {
    /* state */
    playbookId, playbook, definition, rawDsl, graphPos, view, selectedNodeId, selectedEdgeId,
    inspectorOpen, inspectTab, dslError, runStatus, stepResults, pollingActive, pollingExecutionId, executionStatus, dirty, tools, loading,
    /* getters */
    nodes, edges, selectedStep, validationFindings, isValid,
    /* history */
    canUndo: history.canUndo, canRedo: history.canRedo, depth: history.depth,
    /* actions */
    loadPlaybook, refreshTools, setDefinition, parseRawDsl, captureToDsl, setView,
    setSelection, setInspectTab, addStep, removeStep, updateStep, setNodePosition,
    addEdge, removeEdge, relayout, undo, redo, pushHistory, toggleInspector,
    removeSelectedNode, setExecutionState, clearExecutionState, startPolling, stopPolling,
    validateDefinition, saveDraft, publish, runTest, toolForName, runInputNames,
  };
});

export type PlaybookEditorStore = ReturnType<typeof usePlaybookEditorStore> & {
  addToolStep: (toolName?: string, pos?: LayoutPoint) => void;
  addShellStep: (pos?: LayoutPoint) => void;
  addScopeStep: (pos?: LayoutPoint) => void;
  addFindingStep: (pos?: LayoutPoint) => void;
  addReportStep: (pos?: LayoutPoint) => void;
  addCustomStep: (pos?: LayoutPoint) => void;
};

if (import.meta.hot) {
  import.meta.hot.accept(acceptHMRUpdate(usePlaybookEditorStore, import.meta.hot));
}
