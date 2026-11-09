import { describe, it, expect } from "vitest";
import { wouldCreateCycle, hasDuplicateEdge, validateDependencies, edgesFromSteps } from "@/features/playbook-editor/composables/useGraphValidation";
import type { GraphStep } from "@/features/playbook-editor/types/graph";

const step = (id: string, depends_on: string[] = []): GraphStep => ({ id, type: "tool", depends_on });

describe("graph validation", () => {
  describe("wouldCreateCycle", () => {
    it("returns false when no dependency path exists", () => {
      const steps = [step("a", []), step("b", [])];
      expect(wouldCreateCycle(steps, "a", "b")).toBe(false);
    });

    it("returns true when target is already a (transitive) dependency of source", () => {
      const steps = [step("a", ["b"]), step("b", [])];
      // a already depends on b; adding edge a -> b would close a -> b -> a
      expect(wouldCreateCycle(steps, "a", "b")).toBe(true);
    });

    it("returns true for a self-loop source === target", () => {
      const steps = [step("a", [])];
      expect(wouldCreateCycle(steps, "a", "a")).toBe(true);
    });

    it("follows multi-hop dependency chains", () => {
      const steps = [step("a", ["b"]), step("b", ["c"]), step("c", [])];
      // c is a transitive dependency of a; adding edge a -> c would cycle
      expect(wouldCreateCycle(steps, "a", "c")).toBe(true);
      // a is not reachable upstream from c
      expect(wouldCreateCycle(steps, "c", "a")).toBe(false);
    });
  });

  describe("hasDuplicateEdge", () => {
    it("returns true when target already depends on source", () => {
      const steps = [step("a", []), step("b", ["a"])];
      expect(hasDuplicateEdge(steps, "a", "b")).toBe(true);
    });

    it("returns false when no such dependency exists", () => {
      const steps = [step("a", []), step("b", [])];
      expect(hasDuplicateEdge(steps, "a", "b")).toBe(false);
    });

    it("returns false when target step is missing", () => {
      const steps = [step("a", [])];
      expect(hasDuplicateEdge(steps, "a", "ghost")).toBe(false);
    });
  });

  describe("validateDependencies", () => {
    it("returns no findings for a valid DAG", () => {
      const steps = [step("a", []), step("b", ["a"]), step("c", ["a", "b"])];
      expect(validateDependencies(steps)).toEqual([]);
    });

    it("reports self-loops as errors", () => {
      const steps = [step("a", ["a"])];
      const findings = validateDependencies(steps);
      expect(findings.length).toBeGreaterThanOrEqual(1);
      expect(findings.some((f) => f.message.includes("cannot depend on itself"))).toBe(true);
      expect(findings.every((f) => f.severity === "error")).toBe(true);
    });

    it("reports missing dependencies as errors", () => {
      const steps = [step("a", ["ghost"])];
      const findings = validateDependencies(steps);
      expect(findings).toHaveLength(1);
      expect(findings[0].severity).toBe("error");
      expect(findings[0].message).toContain('depends on missing step "ghost"');
    });

    it("reports duplicate dependencies as errors", () => {
      const steps = [step("a", ["b", "b"]), step("b", [])];
      const findings = validateDependencies(steps);
      expect(findings).toHaveLength(1);
      expect(findings[0].severity).toBe("error");
      expect(findings[0].message).toContain('Duplicate dependency "b"');
    });

    it("reports cycles as errors", () => {
      const steps = [step("a", ["b"]), step("b", ["c"]), step("c", ["a"])];
      const findings = validateDependencies(steps);
      expect(findings.length).toBeGreaterThan(0);
      expect(findings.every((f) => f.severity === "error")).toBe(true);
      expect(findings.some((f) => f.message.includes("cycle"))).toBe(true);
    });

    it("reports multiple independent issues", () => {
      const steps = [step("a", ["a", "missing"]), step("b", ["b"])];
      const findings = validateDependencies(steps);
      expect(findings.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe("edgesFromSteps", () => {
    it("builds { source, target } edges from depends_on", () => {
      const steps = [step("a", []), step("b", ["a"]), step("c", ["a", "b"])];
      const edges = edgesFromSteps(steps);
      expect(edges).toEqual([
        { source: "a", target: "b" },
        { source: "a", target: "c" },
        { source: "b", target: "c" },
      ]);
    });

    it("returns empty array for steps without dependencies", () => {
      const steps = [step("a", []), step("b", [])];
      expect(edgesFromSteps(steps)).toEqual([]);
    });
  });
});
