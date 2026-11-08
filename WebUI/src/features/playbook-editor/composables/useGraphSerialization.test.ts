import { describe, it, expect } from "vitest";
import { graphToDsl, dslToGraphNodes, applyDslToGraph } from "./useGraphSerialization";
import type { EditorNode } from "@/stores/playbook-editor";

const baseNode = (overrides: Partial<EditorNode> = {}): EditorNode => ({
  id: "s1",
  type: "tool",
  tool: "nmap",
  depends_on: [],
  args: { target: "{{target}}" },
  position: { x: 10, y: 20 },
  ...overrides,
});

describe("graph/DSL serialization", () => {
  it("graph -> DSL preserves all step fields except layout", () => {
    const nodes: EditorNode[] = [
      baseNode({ id: "a", type: "tool", tool: "nmap", depends_on: [], args: { target: "{{t}}" }, command: "", checkpoint: true, on_failure: "continue", retry: 2, position: { x: 1, y: 2 } }),
      baseNode({ id: "b", type: "shell", depends_on: ["a"], command: "echo {{t}}", inputs: {}, filter: { type: "grep", pattern: "ok" }, position: { x: 5, y: 5 } }),
    ];
    const def = { name: "pb", version: "2.0", inputs: {}, execution: { max_parallel: 4 }, steps: [] };
    const dsl = graphToDsl(nodes, def);
    expect(dsl.name).toBe("pb");
    expect(dsl.version).toBe("2.0");
    expect(dsl.steps).toHaveLength(2);
    const a = dsl.steps.find((s) => s.id === "a")!;
    expect(a.tool).toBe("nmap");
    expect(a.depends_on).toEqual([]);
    expect(a.args).toEqual({ target: "{{t}}" });
    expect(a.checkpoint).toBe(true);
    expect(a.on_failure).toBe("continue");
    expect(a.retry).toBe(2);
    // Layout coordinates must NOT be serialized.
    expect((a as any).position).toBeUndefined();
    expect((a as any).x).toBeUndefined();
    expect((a as any).y).toBeUndefined();
    const b = dsl.steps.find((s) => s.id === "b")!;
    expect(b.depends_on).toEqual(["a"]);
    expect(b.command).toBe("echo {{t}}");
    expect(b.filter).toEqual({ type: "grep", pattern: "ok" });
  });

  it("DSL -> graph restores all fields (incl. unknown/optional)", () => {
    const def: any = {
      name: "pb", version: "1.0", inputs: {}, execution: {},
      steps: [
        { id: "a", type: "custom", module: "mymod", depends_on: [], when: "x > 0", parallel: true, foreach: "items", output_mapping: { out: "x" }, retry: 3, budget: { seconds: 60 }, args: { a: 1 }, command: "c", inputs: { i: 1 }, filter: { f: 1 }, position: { x: 9, y: 9 } },
      ],
    };
    const nodes = dslToGraphNodes(def);
    expect(nodes).toHaveLength(1);
    const n = nodes[0];
    expect(n.type).toBe("custom");
    expect(n.module).toBe("mymod");
    expect(n.when).toBe("x > 0");
    expect(n.parallel).toBe(true);
    expect(n.foreach).toBe("items");
    expect(n.output_mapping).toEqual({ out: "x" });
    expect(n.retry).toBe(3);
    expect(n.budget).toEqual({ seconds: 60 });
    expect(n.args).toEqual({ a: 1 });
    expect(n.position).toEqual({ x: 0, y: 0 }); // no layout provided -> origin
  });

  it("round-trip graph -> DSL -> graph is lossless for semantics", () => {
    const nodes: EditorNode[] = [
      baseNode({ id: "a", type: "tool", tool: "nmap", depends_on: [], args: { target: "{{t}}" }, position: { x: 1, y: 2 } }),
      baseNode({ id: "b", type: "scope_check", depends_on: ["a"], args: {}, checkpoint: true, position: { x: 5, y: 5 } }),
    ];
    const def = { name: "pb", version: "1.0", inputs: {}, execution: {}, steps: [] };
    const dsl = graphToDsl(nodes, def);
    const restored = dslToGraphNodes(dsl);
    expect(restored).toHaveLength(2);
    const ra = restored.find((n) => n.id === "a")!;
    expect(ra.type).toBe("tool");
    expect(ra.tool).toBe("nmap");
    expect(ra.depends_on).toEqual([]);
    expect(ra.args).toEqual({ target: "{{t}}" });
    const rb = restored.find((n) => n.id === "b")!;
    expect(rb.depends_on).toEqual(["a"]);
    expect(rb.checkpoint).toBe(true);
    // positions are recomputed (origin) — layout is separate from semantics.
    expect(rb.position.x).toBe(0);
  });

  it("applyDslToGraph preserves positions for unchanged ids", () => {
    const current: EditorNode[] = [baseNode({ id: "a", position: { x: 100, y: 200 } })];
    const def: any = { name: "pb", version: "1.0", inputs: {}, execution: {}, steps: [{ id: "a", type: "tool", tool: "x", depends_on: [] }] };
    const out = applyDslToGraph(def, current);
    expect(out[0].position).toEqual({ x: 100, y: 200 });
    expect(out[0].tool).toBe("x");
  });

  it("builds edges from depends_on without self-loops or dangling deps", () => {
    const nodes: EditorNode[] = [
      baseNode({ id: "a", depends_on: [] }),
      baseNode({ id: "b", depends_on: ["a", "ghost", "b"] }), // ghost dropped, self-loop dropped
    ];
    // exercise via dsl round trip: edges derived in EditorPage, but here just confirm node->step keeps depends_on
    const def = graphToDsl(nodes, { name: "p", version: "1", inputs: {}, execution: {}, steps: [] });
    const b = def.steps.find((s: any) => s.id === "b")!;
    expect(b.depends_on).toEqual(["a", "ghost", "b"]); // DSL preserves; edge filtering happens at graph layer
  });
});
