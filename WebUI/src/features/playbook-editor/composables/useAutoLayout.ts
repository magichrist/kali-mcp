import type { GraphStep } from "@/features/playbook-editor/types/graph";
import { LAYOUT_PAD_X, LAYOUT_PAD_Y, NODE_H, NODE_W, X_GAP, Y_GAP } from "@/features/playbook-editor/types/graph";
export interface LayoutPoint { x: number; y: number }
export function computeDepths(steps: GraphStep[]): { depths: Record<string, number>; hasCycle: boolean } {
  const depths: Record<string, number> = {};
  const ids = new Set(steps.map((s) => s.id));
  steps.forEach((s) => { depths[s.id] = 0; });
  let hasCycle = false;
  for (let iter = 0; iter < steps.length + 1; iter++) {
    let changed = false;
    for (const s of steps) {
      const deps = (s.depends_on || []).filter((d) => ids.has(d) && d !== s.id);
      const d = deps.length ? Math.max(...deps.map((x) => (depths[x] ?? 0) + 1)) : 0;
      if (d > depths[s.id]) { depths[s.id] = d; changed = true; }
    }
    if (!changed) break;
    if (iter === steps.length) hasCycle = true;
  }
  return { depths, hasCycle };
}
export function nodePosition(stepId: string, depths: Record<string, number>, steps: GraphStep[], graphPos: Record<string, LayoutPoint>): LayoutPoint {
  if (graphPos[stepId]) return { ...graphPos[stepId] };
  const depth = depths[stepId] ?? 0;
  const sameLane = steps.filter((s) => (depths[s.id] ?? 0) === depth);
  const yIdx = sameLane.findIndex((s) => s.id === stepId);
  return { x: LAYOUT_PAD_X + depth * X_GAP, y: LAYOUT_PAD_Y + Math.max(yIdx, 0) * Y_GAP };
}
export function layoutSteps(steps: GraphStep[], graphPos: Record<string, LayoutPoint>): { positions: Record<string, LayoutPoint>; depths: Record<string, number>; hasCycle: boolean } {
  const { depths, hasCycle } = computeDepths(steps);
  const positions: Record<string, LayoutPoint> = {};
  steps.forEach((s) => { positions[s.id] = nodePosition(s.id, depths, steps, graphPos); });
  return { positions, depths, hasCycle };
}
export function layoutBounds(steps: GraphStep[], positions: Record<string, LayoutPoint>): { minX: number; minY: number; maxX: number; maxY: number } {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const s of steps) {
    const p = positions[s.id]; if (!p) continue;
    minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + NODE_W); maxY = Math.max(maxY, p.y + NODE_H);
  }
  return { minX, minY, maxX, maxY };
}
