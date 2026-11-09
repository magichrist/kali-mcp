import { describe, it, expect } from "vitest";
import { graphToDefinition, definitionToGraph, collectRunInputNames } from "@/features/playbook-editor/composables/useGraphSerialization";
import type { PlaybookDefinition } from "@/types/api";

const baseStep = (overrides: Record<string, unknown> = {}) => ({
  id: "s1",
  type: "tool",
  tool: "nmap",
  depends_on: [],
  args: { target: "{{target}}" },
  ...overrides,
});

describe("graph/DSL serialization", () => {
  it("graph -> DSL preserves all step fields except layout; depends_on comes from edges", () => {
    const stepA = baseStep({ id: "a", tool: "nmap", depends_on: [], args: { target: "{{t}}" }, command: "", checkpoint: true });
    const stepB = baseStep({ id: "b", type: "shell", depends_on: [], command: "echo {{t}}", inputs: {}, filter: { type: "grep", pattern: "ok" } });
    const nodes = [
      { id: "a", type: "tool", position: { x: 1, y: 2 }, data: { step: stepA } },
      { id: "b", type: "shell", position: { x: 5, y: 5 }, data: { step: stepB } },
    ];
    const edges = [{ id: "e:a->b", source: "a", target: "b" }];
    const def: PlaybookDefinition = { name: "pb", version: "2.0", inputs: {}, execution: { timeout: 900, max_parallel: 4 }, steps: [] };
    const result = graphToDefinition(nodes as any[], edges, def);
    expect(result.name).toBe("pb");
    expect(result.version).toBe("2.0");
    expect(result.steps).toHaveLength(2);
    const a = result.steps.find((s) => s.id === "a")!;
    expect(a.tool).toBe("nmap");
    expect(a.depends_on).toEqual([]); // no incoming edges
    expect(a.args).toEqual({ target: "{{t}}" });
    expect(a.checkpoint).toBe(true);
    // Layout coordinates must NOT be serialized.
    expect((a as any).position).toBeUndefined();
    expect((a as any).x).toBeUndefined();
    expect((a as any).y).toBeUndefined();
    const b = result.steps.find((s) => s.id === "b")!;
    expect(b.depends_on).toEqual(["a"]); // derived from edges, not node data
    expect(b.command).toBe("echo {{t}}");
    expect(b.filter).toEqual({ type: "grep", pattern: "ok" });
  });

  it("DSL -> graph restores all fields (incl. unknown/optional)", () => {
    const def: any = {
      name: "pb", version: "1.0", inputs: {}, execution: { timeout: 900, max_parallel: 4 },
      steps: [
        { id: "a", type: "custom", module: "mymod", depends_on: [], when: "x > 0", parallel: true, foreach: "items", output_mapping: { out: "x" }, retry: 3, budget: { seconds: 60 }, args: { a: 1 }, command: "c", inputs: { i: 1 }, filter: { f: 1 }, position: { x: 9, y: 9 } },
      ],
    };
    const graph = definitionToGraph(def, {});
    expect(graph.nodes).toHaveLength(1);
    const n = graph.nodes[0];
    expect(n.type).toBe("custom");
    expect((n.data as any).step.module).toBe("mymod");
    expect((n.data as any).step.when).toBe("x > 0");
    expect((n.data as any).step.parallel).toBe(true);
    expect((n.data as any).step.foreach).toBe("items");
    expect((n.data as any).step.output_mapping).toEqual({ out: "x" });
    expect((n.data as any).step.retry).toBe(3);
    expect((n.data as any).step.budget).toEqual({ seconds: 60 });
    expect((n.data as any).step.args).toEqual({ a: 1 });
    // Position is provided by graphPos, not the DSL step.
    expect(n.position).toEqual({ x: 0, y: 0 });
  });

  it("round-trip graph -> DSL -> graph is lossless for semantics", () => {
    const stepA = baseStep({ id: "a", tool: "nmap", depends_on: [], args: { target: "{{t}}" } });
    const stepB = baseStep({ id: "b", type: "scope_check", depends_on: [], args: {}, checkpoint: true });
    const nodes = [
      { id: "a", type: "tool", position: { x: 1, y: 2 }, data: { step: stepA } },
      { id: "b", type: "scope_check", position: { x: 5, y: 5 }, data: { step: stepB } },
    ];
    const edges = [{ id: "e:a->b", source: "a", target: "b" }];
    const def: PlaybookDefinition = { name: "pb", version: "1.0", inputs: {}, execution: { timeout: 900, max_parallel: 4 }, steps: [] };
    const dsl = graphToDefinition(nodes as any[], edges, def);
    const restored = definitionToGraph(dsl, {});
    expect(restored.nodes).toHaveLength(2);
    const ra = restored.nodes.find((n) => n.id === "a")!;
    expect(ra.type).toBe("tool");
    expect((ra.data as any).step.tool).toBe("nmap");
    expect((ra.data as any).step.depends_on).toEqual([]);
    expect((ra.data as any).step.args).toEqual({ target: "{{t}}" });
    const rb = restored.nodes.find((n) => n.id === "b")!;
    expect((rb.data as any).step.depends_on).toEqual(["a"]);
    expect((rb.data as any).step.checkpoint).toBe(true);
    // positions are recomputed (origin) — layout is separate from semantics.
    expect(rb.position.x).toBe(0);
    expect(restored.edges).toHaveLength(1);
    expect(restored.edges[0]).toEqual({ id: "e:a->b", source: "a", target: "b" });
  });

  it("graph -> DSL derives depends_on from edges; self-loops excluded, dangling deps preserved", () => {
    const stepA = baseStep({ id: "a", depends_on: [] });
    const stepB = baseStep({ id: "b", depends_on: [] });
    const nodes = [
      { id: "a", type: "tool", position: { x: 0, y: 0 }, data: { step: stepA } },
      { id: "b", type: "tool", position: { x: 1, y: 1 }, data: { step: stepB } },
    ];
    const edges = [
      { id: "e:a->b", source: "a", target: "b" },
      { id: "e:ghost->b", source: "ghost", target: "b" },
      { id: "e:b->b", source: "b", target: "b" }, // self-loop must be filtered out
    ];
    const def: PlaybookDefinition = { name: "p", version: "1", inputs: {}, execution: { timeout: 900, max_parallel: 4 }, steps: [] };
    const result = graphToDefinition(nodes as any[], edges, def);
    const b = result.steps.find((s) => s.id === "b")!;
    expect(b.depends_on).toEqual(["a", "ghost"]); // self-loop "b" excluded, dangling "ghost" preserved at DSL layer
  });

  it("definitionToGraph deduplicates edges and assigns stable ids", () => {
    const def: any = {
      name: "p", version: "1", inputs: {}, steps: [
        { id: "a", type: "tool", depends_on: [] },
        { id: "b", type: "tool", depends_on: ["a", "a"] },
      ],
    };
    const graph = definitionToGraph(def, {});
    expect(graph.edges).toHaveLength(1);
    expect(graph.edges[0]).toEqual({ id: "e:a->b", source: "a", target: "b" });
  });

  it("collectRunInputNames extracts {{name}} references from steps", () => {
    const def: PlaybookDefinition = {
      name: "p", version: "1", inputs: {}, steps: [
        { id: "a", type: "shell", command: "echo {{target}}", inputs: { file: "{{out}}" }, args: { opt: "{{target}}" } },
        { id: "b", type: "tool", depends_on: ["a"] },
      ],
    };
    expect(collectRunInputNames(def)).toEqual(expect.arrayContaining(["target", "out"]));
    expect(collectRunInputNames(def).length).toBeGreaterThanOrEqual(2);
  });

  it("collectRunInputNames returns empty for definition without references", () => {
    const def: PlaybookDefinition = { name: "p", version: "1", inputs: {}, steps: [{ id: "a", type: "tool", command: "nmap" }] };
    expect(collectRunInputNames(def)).toEqual([]);
  });
});
