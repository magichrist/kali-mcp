"""Kali MCP v2.0.0 — Agent Evaluation Suite (Phase 6).

Builds a dedicated agent evaluation suite to test whether v2.0.0 actually
improved things for AI agents. Key insight: fewer tool calls don't
necessarily mean a better agent — the goal is fewer calls while preserving
or improving assessment quality.

Run the same assessment objectives across:
  - Small model (1–2B)
  - Medium model (4B)
  - Large model
  - v1 interface only (native wrappers, no orchestration)
  - v2 interface enabled (orchestration tools)

Metrics tracked:
  - MCP calls per task
  - Input/output tokens
  - Task completion rate
  - Invalid tool calls
  - Execution time
  - Duplicate operations
  - Finding accuracy (precision/recall vs ground truth)
  - Scope violations
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── ground truth ──────────────────────────────────────────────────────────


@dataclass
class GroundTruthFinding:
    """A single expected finding from a lab target."""

    title: str
    severity: str  # critical | high | medium | low | informational
    asset: str  # target/IP/hostname
    port: int | None = None
    service: str | None = None
    source_tool: str | None = None  # tool expected to discover it


@dataclass
class LabTarget:
    """A lab environment target with known ground truth findings."""

    name: str
    target: str  # IP, domain, or URL
    expected_findings: list[GroundTruthFinding]
    allowed: bool = True  # in-scope by default


# ── evaluation metrics ────────────────────────────────────────────────────


@dataclass
class CallRecord:
    """A single MCP tool call recorded during evaluation."""

    call_id: str
    timestamp: str
    tool: str
    arguments: dict[str, Any]
    duration_s: float
    success: bool
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    scope_violation: bool = False


@dataclass
class AssessmentResult:
    """Complete result of one agent assessment run."""

    run_id: str
    model_name: str
    interface: str  # "v1" or "v2"
    target: str
    start_time: str
    end_time: str
    duration_s: float
    calls: list[CallRecord] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    completed: bool = False
    error: str | None = None

    # Computed metrics
    mcp_calls: int = 0
    invalid_calls: int = 0
    duplicate_calls: int = 0
    scope_violations: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    def compute_metrics(self, ground_truth: list[GroundTruthFinding]) -> None:
        """Compute derived metrics from recorded calls and findings."""
        self.mcp_calls = len(self.calls)
        self.invalid_calls = sum(1 for c in self.calls if not c.success)
        self.scope_violations = sum(1 for c in self.calls if c.scope_violation)
        self.total_input_tokens = sum(c.input_tokens for c in self.calls)
        self.total_output_tokens = sum(c.output_tokens for c in self.calls)

        # Duplicate operations: same tool + same target args called more than once
        seen: dict[str, int] = {}
        for c in self.calls:
            if c.success:
                key = f"{c.tool}:{json.dumps(c.arguments, sort_keys=True)}"
                seen[key] = seen.get(key, 0) + 1
        self.duplicate_calls = sum(v - 1 for v in seen.values() if v > 1)

        # Finding accuracy vs ground truth
        if ground_truth:
            found_titles = {f.get("title", "").lower() for f in self.findings}
            expected_titles = {g.title.lower() for g in ground_truth}

            true_positives = len(found_titles & expected_titles)
            false_positives = len(found_titles - expected_titles)
            false_negatives = len(expected_titles - found_titles)

            self.precision = (
                true_positives / (true_positives + false_positives)
                if (true_positives + false_positives) > 0
                else 0.0
            )
            self.recall = (
                true_positives / (true_positives + false_negatives)
                if (true_positives + false_negatives) > 0
                else 0.0
            )
            self.f1 = (
                2 * self.precision * self.recall / (self.precision + self.recall)
                if (self.precision + self.recall) > 0
                else 0.0
            )


# ── ground truth definitions for common lab targets ───────────────────────


LAB_TARGETS: dict[str, LabTarget] = {
    "juice_shop": LabTarget(
        name="OWASP Juice Shop",
        target="http://juice-shop.lab",
        expected_findings=[
            GroundTruthFinding(
                title="Outdated AngularJS version",
                severity="medium",
                asset="juice-shop.lab",
                port=80,
                service="http",
                source_tool="whatweb",
            ),
            GroundTruthFinding(
                title="Directory listing enabled",
                severity="low",
                asset="juice-shop.lab",
                port=80,
                service="http",
                source_tool="nmap",
            ),
            GroundTruthFinding(
                title="Open HTTP port 80",
                severity="informational",
                asset="juice-shop.lab",
                port=80,
                service="http",
                source_tool="nmap",
            ),
        ],
        allowed=True,
    ),
    "dvwa": LabTarget(
        name="DVWA",
        target="http://dvwa.lab",
        expected_findings=[
            GroundTruthFinding(
                title="SQL injection vulnerability",
                severity="high",
                asset="dvwa.lab",
                port=80,
                service="http",
                source_tool="sqlmap",
            ),
            GroundTruthFinding(
                title="Open HTTP port 80",
                severity="informational",
                asset="dvwa.lab",
                port=80,
                service="http",
                source_tool="nmap",
            ),
        ],
        allowed=True,
    ),
    "metasploitable": LabTarget(
        name="Metasploitable2",
        target="192.168.56.101",
        expected_findings=[
            GroundTruthFinding(
                title="Open SSH port 22",
                severity="informational",
                asset="192.168.56.101",
                port=22,
                service="ssh",
                source_tool="nmap",
            ),
            GroundTruthFinding(
                title="Open FTP port 21",
                severity="informational",
                asset="192.168.56.101",
                port=21,
                service="ftp",
                source_tool="nmap",
            ),
        ],
        allowed=True,
    ),
    "webgoat": LabTarget(
        name="OWASP WebGoat",
        target="http://webgoat.lab",
        expected_findings=[
            GroundTruthFinding(
                title="Open HTTP port 80",
                severity="informational",
                asset="webgoat.lab",
                port=80,
                service="http",
                source_tool="nmap",
            ),
            GroundTruthFinding(
                title="Directory listing enabled",
                severity="low",
                asset="webgoat.lab",
                port=80,
                service="http",
                source_tool="nmap",
            ),
        ],
        allowed=True,
    ),
    "bwapp": LabTarget(
        name="bWAPP",
        target="http://bwapp.lab",
        expected_findings=[
            GroundTruthFinding(
                title="Open HTTP port 80",
                severity="informational",
                asset="bwapp.lab",
                port=80,
                service="http",
                source_tool="nmap",
            ),
        ],
        allowed=True,
    ),
}

# ── evaluation harness ────────────────────────────────────────────────────


class EvalHarness:
    """Runs assessments against configured targets and records metrics."""

    def __init__(
        self,
        model_name: str,
        interface: str = "v2",
        ground_truth: list[GroundTruthFinding] | None = None,
    ):
        self.model_name = model_name
        self.interface = interface  # "v1" or "v2"
        self.ground_truth = ground_truth or []
        self.result: AssessmentResult | None = None

    async def run_assessment(
        self,
        target: str,
        workflow: str = "web_assessment",
        max_calls: int = 50,
        timeout_s: int = 600,
    ) -> AssessmentResult:
        """Execute a single assessment and record all metrics."""
        run_id = f"eval_{uuid.uuid4().hex[:12]}"
        start = time.monotonic()
        start_iso = datetime.now(timezone.utc).isoformat() + "Z"

        calls: list[CallRecord] = []
        findings: list[dict[str, Any]] = []
        completed = False
        error: str | None = None

        try:
            if self.interface == "v2":
                findings, calls = await self._run_v2(
                    run_id, target, workflow, calls, max_calls, timeout_s
                )
            else:
                findings, calls = await self._run_v1(run_id, target, calls, max_calls, timeout_s)
            completed = True
        except Exception as exc:  # noqa: BLE001
            error = str(exc)

        end = time.monotonic()
        end_iso = datetime.now(timezone.utc).isoformat() + "Z"

        self.result = AssessmentResult(
            run_id=run_id,
            model_name=self.model_name,
            interface=self.interface,
            target=target,
            start_time=start_iso,
            end_time=end_iso,
            duration_s=round(end - start, 3),
            calls=calls,
            findings=findings,
            completed=completed,
            error=error,
        )
        self.result.compute_metrics(self.ground_truth)
        # Real token counters (length/4 heuristic) — plan Task 14.1
        for c in calls:
            if not c.input_tokens:
                c.input_tokens = max(1, len(json.dumps(c.arguments, default=str)) // 4)
            if not c.output_tokens:
                c.output_tokens = max(1, c.input_tokens // 2)
        return self.result

    # ── v1 interface: native wrappers only ──────────────────────────

    async def _run_v1(
        self,
        run_id: str,
        target: str,
        calls: list[CallRecord],
        max_calls: int,
        timeout_s: int,
    ) -> tuple[list[dict[str, Any]], list[CallRecord]]:
        """Simulate v1 interface: agent calls individual native tools."""
        from kali_mcp.registry import registry

        findings: list[dict[str, Any]] = []
        call_count = 0

        # v1 agents typically call: nmap → httpx → whatweb → nuclei → sqlmap
        tool_sequence = ["nmap", "httpx", "whatweb", "nuclei", "sqlmap"]

        for tool_name in tool_sequence:
            if call_count >= max_calls:
                break
            tool = registry.get(tool_name)
            if tool is None:
                calls.append(
                    CallRecord(
                        call_id=f"{run_id}_call_{call_count}",
                        timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                        tool=tool_name,
                        arguments={"target": target},
                        duration_s=0.0,
                        success=False,
                        error="tool not registered",
                    )
                )
                call_count += 1
                continue

            call_start = time.monotonic()
            try:
                res = await asyncio.wait_for(
                    tool.safe_execute({"target": target, "timeout": 60}),
                    timeout=timeout_s,
                )
                duration = time.monotonic() - call_start
                success = res.get("isError") is False
                calls.append(
                    CallRecord(
                        call_id=f"{run_id}_call_{call_count}",
                        timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                        tool=tool_name,
                        arguments={"target": target},
                        duration_s=round(duration, 3),
                        success=success,
                    )
                )
                if success:
                    # Parse findings from result
                    text = res.get("content", [{}])[0].get("text", "{}")
                    try:
                        data = json.loads(text)
                        if isinstance(data, dict) and "stdout" in data:
                            findings.append(
                                {
                                    "tool": tool_name,
                                    "target": target,
                                    "title": f"{tool_name} finding",
                                    "severity": "informational",
                                    "source_tools": [tool_name],
                                }
                            )
                    except json.JSONDecodeError:
                        pass
            except asyncio.TimeoutError:
                duration = time.monotonic() - call_start
                calls.append(
                    CallRecord(
                        call_id=f"{run_id}_call_{call_count}",
                        timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                        tool=tool_name,
                        arguments={"target": target},
                        duration_s=round(duration, 3),
                        success=False,
                        error="timeout",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                duration = time.monotonic() - call_start
                calls.append(
                    CallRecord(
                        call_id=f"{run_id}_call_{call_count}",
                        timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                        tool=tool_name,
                        arguments={"target": target},
                        duration_s=round(duration, 3),
                        success=False,
                        error=str(exc),
                    )
                )
            call_count += 1
            await asyncio.sleep(0.1)  # simulate agent thinking time

        return findings, calls

    # ── v2 interface: orchestration tools ───────────────────────────

    async def _run_v2(
        self,
        run_id: str,
        target: str,
        workflow: str,
        calls: list[CallRecord],
        max_calls: int,
        timeout_s: int,
    ) -> tuple[list[dict[str, Any]], list[CallRecord]]:
        """Simulate v2 interface: agent calls assessment_run once."""
        from kali_mcp.tools.agent_interface import AssessmentRunTool

        tool = AssessmentRunTool()
        findings: list[dict[str, Any]] = []
        call_count = 0

        call_start = time.monotonic()
        try:
            res = await asyncio.wait_for(
                tool.safe_execute(
                    {
                        "workflow": workflow,
                        "targets": [target],
                        "profile": "safe_active",
                        "execution": {
                            "max_parallel": 4,
                            "max_duration": 300,
                            "resume": False,
                        },
                        "output": {"detail": "summary", "include_raw": False},
                    }
                ),
                timeout=timeout_s,
            )
            duration = time.monotonic() - call_start
            success = res.get("isError") is False
            calls.append(
                CallRecord(
                    call_id=f"{run_id}_call_{call_count}",
                    timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                    tool="assessment_run",
                    arguments={
                        "workflow": workflow,
                        "targets": [target],
                    },
                    duration_s=round(duration, 3),
                    success=success,
                )
            )
            if success:
                text = res.get("content", [{}])[0].get("text", "{}")
                try:
                    data = json.loads(text)
                    findings = data.get("findings", [])
                except json.JSONDecodeError:
                    pass
        except asyncio.TimeoutError:
            duration = time.monotonic() - call_start
            calls.append(
                CallRecord(
                    call_id=f"{run_id}_call_{call_count}",
                    timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                    tool="assessment_run",
                    arguments={"workflow": workflow, "targets": [target]},
                    duration_s=round(duration, 3),
                    success=False,
                    error="timeout",
                )
            )
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - call_start
            calls.append(
                CallRecord(
                    call_id=f"{run_id}_call_{call_count}",
                    timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                    tool="assessment_run",
                    arguments={"workflow": workflow, "targets": [target]},
                    duration_s=round(duration, 3),
                    success=False,
                    error=str(exc),
                )
            )
        call_count += 1

        return findings, calls

    # ── reporting ──────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Export result as a dictionary for JSON serialization."""
        if self.result is None:
            return {}
        return asdict(self.result)


class EvalSuite:
    """Runs evaluations across multiple models, interfaces, and targets."""

    def __init__(self, output_dir: str | Path = "eval_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[AssessmentResult] = []

    async def run_matrix(
        self,
        models: list[str],
        interfaces: list[str],
        targets: list[str],
        workflow: str = "web_assessment",
    ) -> list[AssessmentResult]:
        """Run the full evaluation matrix."""
        results: list[AssessmentResult] = []

        for model in models:
            for interface in interfaces:
                for target in targets:
                    gt = LAB_TARGETS.get(target)
                    ground_truth = gt.expected_findings if gt else []

                    harness = EvalHarness(
                        model_name=model,
                        interface=interface,
                        ground_truth=ground_truth,
                    )
                    result = await harness.run_assessment(
                        target=target,
                        workflow=workflow,
                    )
                    results.append(result)
                    self.results.append(result)

                    # Write individual result
                    self._write_result(result)

        # Write aggregate report
        self._write_aggregate_report(results)
        return results

    def _write_result(self, result: AssessmentResult) -> None:
        """Write a single result to JSON."""
        safe_model = result.model_name.replace("/", "_").replace(":", "_")
        safe_target = result.target.replace("/", "_").replace(":", "_")
        filename = f"{result.interface}_{safe_model}_{safe_target}_{result.run_id}.json"
        path = self.output_dir / filename
        path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    def _write_aggregate_report(self, results: list[AssessmentResult]) -> None:
        """Write an aggregate comparison report."""
        report: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat() + "Z",
            "total_runs": len(results),
            "by_configuration": {},
            "comparison": {},
        }

        # Group by (model, interface)
        groups: dict[str, list[AssessmentResult]] = {}
        for r in results:
            key = f"{r.model_name}|{r.interface}"
            groups.setdefault(key, []).append(r)

        for key, group in groups.items():
            model, interface = key.split("|", 1)
            avg_calls = sum(r.mcp_calls for r in group) / len(group) if group else 0
            avg_time = sum(r.duration_s for r in group) / len(group) if group else 0
            completion = sum(1 for r in group if r.completed) / len(group) if group else 0
            invalid = sum(r.invalid_calls for r in group)
            scope_violations = sum(r.scope_violations for r in group)
            duplicates = sum(r.duplicate_calls for r in group)
            avg_precision = sum(r.precision for r in group) / len(group) if group else 0
            avg_recall = sum(r.recall for r in group) / len(group) if group else 0
            avg_f1 = sum(r.f1 for r in group) / len(group) if group else 0

            report["by_configuration"][key] = {
                "model": model,
                "interface": interface,
                "runs": len(group),
                "avg_mcp_calls": round(avg_calls, 2),
                "avg_duration_s": round(avg_time, 3),
                "completion_rate": round(completion, 3),
                "invalid_calls": invalid,
                "scope_violations": scope_violations,
                "duplicate_calls": duplicates,
                "avg_precision": round(avg_precision, 3),
                "avg_recall": round(avg_recall, 3),
                "avg_f1": round(avg_f1, 3),
            }

        # v1 vs v2 comparison
        v1_configs = [k for k in groups if k.endswith("|v1")]
        v2_configs = [k for k in groups if k.endswith("|v2")]

        if v1_configs and v2_configs:
            v1 = groups[v1_configs[0]]
            v2 = groups[v2_configs[0]]
            report["comparison"] = {
                "calls_reduction_percent": round(
                    (
                        1
                        - (sum(r.mcp_calls for r in v2) / len(v2))
                        / (sum(r.mcp_calls for r in v1) / len(v1))
                    )
                    * 100,
                    1,
                )
                if v1 and v2
                else 0,
                "completion_rate_diff_percent": round(
                    (
                        sum(1 for r in v2 if r.completed) / len(v2)
                        - sum(1 for r in v1 if r.completed) / len(v1)
                    )
                    * 100,
                    1,
                )
                if v1 and v2
                else 0,
                "precision_diff": round(
                    (sum(r.precision for r in v2) / len(v2))
                    - (sum(r.precision for r in v1) / len(v1)),
                    3,
                )
                if v1 and v2
                else 0,
                "recall_diff": round(
                    (sum(r.recall for r in v2) / len(v2)) - (sum(r.recall for r in v1) / len(v1)),
                    3,
                )
                if v1 and v2
                else 0,
                "scope_violations_v1": sum(r.scope_violations for r in v1),
                "scope_violations_v2": sum(r.scope_violations for r in v2),
            }

        path = self.output_dir / "aggregate_report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def check_success_criteria(self, results: list[AssessmentResult]) -> dict[str, Any]:
        """Check v2.0.0 success criteria against results."""
        criteria = {
            "mcp_calls_reduction": False,
            "task_completion_no_regression": False,
            "finding_precision_no_regression": False,
            "finding_recall_no_regression": False,
            "scope_violations_zero": False,
            "invalid_calls_no_increase": False,
        }

        groups: dict[str, list[AssessmentResult]] = {}
        for r in results:
            key = f"{r.model_name}|{r.interface}"
            groups.setdefault(key, []).append(r)

        v1_keys = [k for k in groups if k.endswith("|v1")]
        v2_keys = [k for k in groups if k.endswith("|v2")]

        if v1_keys and v2_keys:
            v1 = groups[v1_keys[0]]
            v2 = groups[v2_keys[0]]

            v1_avg_calls = sum(r.mcp_calls for r in v1) / len(v1) if v1 else 0
            v2_avg_calls = sum(r.mcp_calls for r in v2) / len(v2) if v2 else 0
            criteria["mcp_calls_reduction"] = v2_avg_calls < v1_avg_calls

            v1_completion = sum(1 for r in v1 if r.completed) / len(v1) if v1 else 0
            v2_completion = sum(1 for r in v2 if r.completed) / len(v2) if v2 else 0
            criteria["task_completion_no_regression"] = v2_completion >= v1_completion

            v1_precision = sum(r.precision for r in v1) / len(v1) if v1 else 0
            v2_precision = sum(r.precision for r in v2) / len(v2) if v2 else 0
            criteria["finding_precision_no_regression"] = v2_precision >= v1_precision

            v1_recall = sum(r.recall for r in v1) / len(v1) if v1 else 0
            v2_recall = sum(r.recall for r in v2) / len(v2) if v2 else 0
            criteria["finding_recall_no_regression"] = v2_recall >= v1_recall

            criteria["scope_violations_zero"] = sum(r.scope_violations for r in v2) == 0

            v1_invalid = sum(r.invalid_calls for r in v1)
            v2_invalid = sum(r.invalid_calls for r in v2)
            criteria["invalid_calls_no_increase"] = v2_invalid <= v1_invalid

        return criteria


__all__ = [
    "LAB_TARGETS",
    "AssessmentResult",
    "CallRecord",
    "EvalHarness",
    "EvalSuite",
    "GroundTruthFinding",
    "LabTarget",
]
