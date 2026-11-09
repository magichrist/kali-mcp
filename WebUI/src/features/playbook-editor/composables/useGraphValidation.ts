import type { GraphStep } from "@/features/playbook-editor/types/graph";
export interface ValidationFinding { stepId: string; message: string; severity: "error" | "warn"; }
export function wouldCreateCycle(steps: GraphStep[], sourceId: string, targetId: string): boolean {
  if (sourceId === targetId) return true;
  const byId = new Map(steps.map((s) => [s.id, s]));
  const seen = new Set<string>();
  const stack: string[] = [sourceId];
  while (stack.length) {
    const cur = stack.pop();
    if (!cur) continue;
    if (cur === targetId) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    const deps: string[] = byId.get(cur)?.depends_on ?? [];
    deps.forEach((d: string) => stack.push(d));
  }
  return false;
}
export function hasDuplicateEdge(steps: GraphStep[], sourceId: string, targetId: string): boolean {
  const step = steps.find((s) => s.id === targetId);
  return !!step && Array.isArray(step.depends_on) && step.depends_on.includes(sourceId);
}
export function validateDependencies(steps: GraphStep[]): ValidationFinding[] {
  const findings: ValidationFinding[] = [];
  const ids = new Set(steps.map((s) => s.id));
  for (const step of steps) {
    const deps = Array.isArray(step.depends_on) ? step.depends_on : [];
    const seenDeps = new Set<string>();
    for (const dep of deps) {
      if (dep === step.id) { findings.push({ stepId: step.id, message: `Step "${step.id}" cannot depend on itself (self-loop).`, severity: "error" }); continue; }
      if (!ids.has(dep)) { findings.push({ stepId: step.id, message: `Step "${step.id}" depends on missing step "${dep}".`, severity: "error" }); continue; }
      if (seenDeps.has(dep)) { findings.push({ stepId: step.id, message: `Duplicate dependency "${dep}" on step "${step.id}".`, severity: "error" }); continue; }
      seenDeps.add(dep);
    }
  }
  const color = new Map<string, "white" | "gray" | "black">();
  steps.forEach((s) => color.set(s.id, "white"));
  const dfs = (nodeId: string, path: string[]): void => {
    color.set(nodeId, "gray"); path.push(nodeId);
    const step = steps.find((s) => s.id === nodeId);
    for (const dep of Array.isArray(step?.depends_on) ? step.depends_on : []) {
      const c = color.get(dep);
      if (c === "gray") { const cs = path.indexOf(dep); for (const sid of path.slice(cs)) findings.push({ stepId: sid, message: `Dependency cycle detected involving step "${sid}".`, severity: "error" }); }
      else if (c === "white") dfs(dep, path);
    }
    color.set(nodeId, "black"); path.pop();
  };
  for (const step of steps) if (color.get(step.id) === "white") dfs(step.id, []);
  return findings;
}
export function edgesFromSteps(steps: GraphStep[]): Array<{ source: string; target: string }> {
  const edges: Array<{ source: string; target: string }> = [];
  for (const step of steps) for (const dep of Array.isArray(step.depends_on) ? step.depends_on : []) edges.push({ source: dep, target: step.id });
  return edges;
}
