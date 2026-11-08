import type { PlaybookDefinition } from "@/types/api";
import type { GraphStep } from "@/features/playbook-editor/types/graph";
import { edgesFromSteps } from "@/features/playbook-editor/composables/useGraphValidation";
export interface VueFlowNodeLike { id: string; data: { step: GraphStep }; }
export interface VueFlowEdgeLike { id: string; source: string; target: string; }
export function cloneStep(step: GraphStep): GraphStep { return JSON.parse(JSON.stringify(step)); }
export function graphToDefinition(nodes: VueFlowNodeLike[], edges: VueFlowEdgeLike[], definition: PlaybookDefinition): PlaybookDefinition {
  const stepsById = new Map<string, GraphStep>();
  for (const node of nodes) stepsById.set(node.id, cloneStep(node.data.step));
  const depsByTarget = new Map<string, Set<string>>();
  for (const edge of edges) {
    let set = depsByTarget.get(edge.target);
    if (!set) { set = new Set(); depsByTarget.set(edge.target, set); }
    if (edge.source !== edge.target) set.add(edge.source);
  }
  const steps: GraphStep[] = [];
  for (const node of nodes) {
    const step = stepsById.get(node.id)!;
    const deps = depsByTarget.get(node.id);
    step.depends_on = (deps && deps.size) ? [...deps] : [];
    steps.push(step);
  }
  return { ...definition, steps } as PlaybookDefinition;
}
export function definitionToGraph(definition: PlaybookDefinition, graphPos: Record<string, { x: number; y: number }>): { nodes: VueFlowNodeLike[]; edges: VueFlowEdgeLike[] } {
  const steps: GraphStep[] = Array.isArray(definition.steps) ? definition.steps : [];
  const nodes: VueFlowNodeLike[] = steps.map((step) => ({ id: step.id, type: step.type, position: graphPos[step.id] ?? { x: 0, y: 0 }, data: { step: cloneStep(step) } }));
  const edges: VueFlowEdgeLike[] = []; const seen = new Set<string>();
  for (const { source, target } of edgesFromSteps(steps)) {
    const key = `${source}->${target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({ id: `e:${key}`, source, target });
  }
  return { nodes, edges };
}
export function collectRunInputNames(definition: PlaybookDefinition): string[] {
  const names = new Set<string>();
  const add = (v: unknown) => { if (typeof v !== "string") return; for (const m of v.matchAll(/\{\{\s*([a-zA-Z_][\w]*)\s*\}\}/g)) names.add(m[1]); };
  for (const s of Array.isArray(definition.steps) ? definition.steps : []) {
    if (s.inputs) for (const v of Object.values(s.inputs)) add(v);
    if (s.command) add(s.command);
    if (s.args) for (const v of Object.values(s.args)) add(v);
  }
  return [...names];
}
