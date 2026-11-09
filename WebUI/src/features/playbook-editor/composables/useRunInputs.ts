/*
 * useRunInputs — builds the input specs shown in the editor run modal.
 * Mirrors the vanilla app.js defInputs / collectRunInputs logic.
 */
import type { PlaybookDefinition } from "@/types/api";

export interface RunInputSpec {
  name: string;
  spec: { type: string; required?: boolean; default?: unknown };
  referenced: boolean;
}

function defInputs(def: PlaybookDefinition): Array<{ name: string; spec: any }> {
  const raw = def?.inputs;
  if (Array.isArray(raw)) {
    return raw.filter((x) => typeof x === "object" && x?.name).map((x) => ({ name: x.name, spec: x }));
  }
  if (raw && typeof raw === "object") {
    return Object.entries(raw).map(([name, spec]) => ({ name, spec: typeof spec === "object" && spec ? spec : {} }));
  }
  return [];
}

/* collect {{name}} references anywhere in the playbook DSL */
function collectRefNames(def: PlaybookDefinition): Set<string> {
  const names = new Set<string>();
  const add = (v: unknown) => {
    if (typeof v !== "string") return;
    for (const m of v.matchAll(/\{\{\s*([a-zA-Z_][\w]*)\s*\}\}/g)) names.add(m[1]);
  };
  for (const s of Array.isArray(def?.steps) ? def.steps : []) {
    if (s.inputs) for (const v of Object.values(s.inputs)) add(v);
    if (s.command) add(s.command);
    if (s.args) for (const v of Object.values(s.args)) add(v);
  }
  return names;
}

export function gatherRunSpecs(def: PlaybookDefinition): RunInputSpec[] {
  const declared = defInputs(def);
  const refs = collectRefNames(def);
  const byName = new Map<string, RunInputSpec>();
  for (const sp of declared) {
    byName.set(sp.name, { name: sp.name, spec: sp.spec, referenced: refs.has(sp.name) });
  }
  /* Add discovered {{name}} references that weren't declared as inputs */
  for (const name of refs) {
    if (!byName.has(name)) {
      byName.set(name, { name, spec: { type: "string", required: true }, referenced: true });
    }
  }
  return [...byName.values()];
}
