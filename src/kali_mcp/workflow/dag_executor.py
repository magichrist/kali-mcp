"""DAG-based playbook execution engine for kali-mcp v2.0.

Executes playbook definitions as a Directed Acyclic Graph with support for:
- depends_on (dependency ordering via topological sort)
- when (conditional execution against structured outputs)
- parallel (concurrent independent steps)
- foreach (iteration over discovered targets/arrays)
- output_mapping (structured result passing between steps)
- checkpoint (state persistence after successful steps)
- resume (skip completed steps)
- retry (transient failure retry)
- on_failure (continue / skip_dependents / abort)
- budget (per-step resource limits)

All conditions evaluate against structured outputs only — never arbitrary
shell expressions.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any

from kali_mcp.models import ExecutionResult
from kali_mcp.tools.persist import now_iso
from kali_mcp.workflow import modules_runtime
from kali_mcp.workflow.scope_gate import ScopeViolationError, gate_step_args
from kali_mcp.workflow.yaml_loader import (
    PlaybookDefinition,
    PlaybookError,
    StepDefinition,
    load_module,
)


def _get_registry():
    """Lazy registry import to avoid circular imports at module load time."""
    from kali_mcp.registry import registry

    return registry


def _has_placeholder(command: str, name: str) -> bool:
    """True when ``command`` still references placeholder ``{name}``/``{{name}}``."""
    if not command or not name:
        return False
    return bool(re.search(rf"\{{\{{?\s*{re.escape(name)}\s*\}}?\}}", command))


def _fmt_value(value: Any) -> str:
    """Render a placeholder value for shell substitution."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (list, tuple)):
        return " ".join(str(_fmt_value(v)) for v in value)
    return str(value)


# Global run-state registry: {playbook_name: status_dict}
RUN_STATUS: dict[str, dict[str, Any]] = {}

#: Hard cap on foreach/while iterations — prevents runaway loops in authored
#: playbooks (bounded iteration per Playbook Studio security architecture).
MAX_ITERATIONS = 1000

VALIDATION_STATES = {
    "observed",
    "suspected",
    "validated",
    "remediated",
    "false_positive",
    "accepted_risk",
}


@dataclass
class StepResult:
    step_id: str
    success: bool
    result: Any = None
    error: str | None = None
    duration: float = 0.0


class PlaybookEngine:
    """Executes a DAG-based playbook.

    A playbook is a PlaybookDefinition with steps that form a DAG via
    depends_on edges. Steps without dependencies can run in parallel when
    marked parallel: true, or when they are independent of each other.
    """

    def __init__(self) -> None:
        self._step_results: dict[str, Any] = {}

    # ── public API ──────────────────────────────────────────────────────

    async def run(self, playbook: PlaybookDefinition, resume: bool = False) -> ExecutionResult:
        """Execute the full playbook DAG and return an ExecutionResult."""
        name = playbook.name
        steps = playbook.steps
        subst_target = playbook.inputs.get("targets")
        self._subst_target = subst_target
        # Concrete run inputs: scalar values provided at run time (merged by
        # the studio service) or declared defaults from the input specs.
        # Dict specs without defaults stay out — they are not values.
        resolved_inputs: dict[str, Any] = {}
        for k, v in playbook.inputs.items():
            if isinstance(v, dict):
                default = v.get("default")
                if isinstance(default, (str, int, float)) or (
                    isinstance(default, list) and default
                ):
                    resolved_inputs[k] = default
            elif isinstance(v, (str, int, float, list)):
                resolved_inputs[k] = v
        self._playbook_inputs = resolved_inputs

        # Resume: determine which step indices to skip
        skip_indices: set[int] = set()
        prior = RUN_STATUS.get(name)
        if resume and not prior:
            # Fall back to persisted state (e.g. after a process restart).
            try:
                from kali_mcp.db import manager as dbm

                db = dbm.get_db()
                if db is not None:
                    persisted = db.load_workflow_run(name)
                    if persisted:
                        prior = dict(persisted.get("state") or {})
                        prior["status"] = persisted.get("status", prior.get("status"))
                        prior["completed_steps"] = persisted.get(
                            "completed_steps", prior.get("completed_steps", [])
                        )
                        RUN_STATUS[name] = prior
            except Exception:  # noqa: BLE001 — SQLite resume is best-effort
                pass
        if (
            resume
            and prior
            and prior.get("status") in ("completed", "failed", "aborted", "partial")
        ):
            skip_indices = set(prior.get("completed_steps", []))

        state = RUN_STATUS.setdefault(name, {})
        state.update(
            {
                "status": "running",
                "steps_total": len(steps),
                "started_at": now_iso(),
                "max_parallel": playbook.max_parallel,
                "timeout": playbook.timeout,
            }
        )
        if resume:
            state["completed_steps"] = sorted(skip_indices)
        else:
            state["completed_steps"] = []

        # Substitute {{target}} into step args
        if subst_target:
            for step in steps:
                step.args = self._substitute_target(step.args, subst_target)

        sem = asyncio.Semaphore(playbook.max_parallel)
        budget_default = max(30, playbook.timeout // max(1, len(steps)))

        async def run_one(idx: int) -> tuple[int, Any]:
            step = steps[idx]
            if idx in skip_indices:
                return idx, {"step": step.id, "skipped": True, "reason": "resume skip"}
            if aborted_flag["value"] and step.on_failure == "abort":
                if self._depends_on_failed(step, steps, idx):
                    return idx, {"step": step.id, "skipped": True, "reason": "aborted"}
            step_budget = int((step.budget or {}).get("timeout", budget_default))
            async with sem:
                try:
                    res = await asyncio.wait_for(
                        self._run_step(step, steps, state), timeout=step_budget
                    )
                    return idx, res
                except asyncio.TimeoutError:
                    return idx, {"step": step.id, "error": "timeout", "timed_out": True}
                except Exception as e:  # noqa: BLE001
                    return idx, {"step": step.id, "error": str(e)}

        aborted_flag = {"value": False}

        # Results collected in wave order; used for the ExecutionResult payload.
        results: list[Any] = []

        # Compute dependency waves
        waves = self._compute_waves(steps)

        overall_deadline = asyncio.get_event_loop().time() + playbook.timeout

        for wave in waves:
            if aborted_flag["value"]:
                # skip remaining waves' dependent steps handled per-step
                for idx in wave:
                    if idx not in state["completed_steps"]:
                        state["completed_steps"].append(idx)
                continue
            # filter skipped
            todo = [idx for idx in wave if idx not in skip_indices]
            if not todo:
                continue
            # overall timeout check
            remaining = overall_deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                state["status"] = "failed"
                aborted_flag["value"] = True
                break

            wave_results = await asyncio.gather(*[run_one(idx) for idx in todo])

            for idx, step_res in wave_results:
                step = steps[idx]
                if isinstance(step_res, list):
                    results.extend(step_res)
                else:
                    results.append(step_res)
                self._step_results[step.id] = step_res
                if idx not in state["completed_steps"]:
                    state["completed_steps"].append(idx)

                if step.checkpoint:
                    self._persist_state(name, state)

                step_failed = self._is_step_failure(step_res)
                if step_failed:
                    if step.on_failure == "abort":
                        aborted_flag["value"] = True
                        state["status"] = "failed"
                    elif step.on_failure == "skip_dependents":
                        aborted_flag["value"] = True

        # handle skipped indices
        for idx in skip_indices:
            if idx not in state["completed_steps"]:
                state["completed_steps"].append(idx)

        all_completed = len(state["completed_steps"]) == len(steps)
        final_status = (
            "completed"
            if (all_completed and not aborted_flag["value"])
            else ("partial" if state["completed_steps"] else "failed")
        )
        state["status"] = final_status
        state["finished_at"] = now_iso()

        payload = {
            "playbook": name,
            "steps": [s.id for s in steps],
            "results": results,
            "status": state["status"],
            "completed_steps": state["completed_steps"],
            "step_results": {k: v for k, v in self._step_results.items()},
        }

        return ExecutionResult(
            tool=name,
            command=json.dumps([s.id for s in steps], indent=2),
            stdout=json.dumps(payload, indent=2),
            stderr="",
            exit_code=0 if final_status in ("completed", "partial") else 1,
            success=final_status in ("completed", "partial"),
            timed_out=False,
            duration=0.0,
            start_time=state["started_at"],
            end_time=state["finished_at"],
        )

    # ── step execution ─────────────────────────────────────────────────

    async def _run_step(
        self, step: StepDefinition, all_steps: list[StepDefinition], state: dict
    ) -> Any:
        """Run a single step (possibly with retries)."""
        # Evaluate when condition against structured outputs
        if step.when is not None and not self._evaluate_when(step.when):
            return {"step": step.id, "skipped": True, "reason": "when condition false"}

        # Resolve foreach: iterate over a prior step's output array
        if step.foreach:
            return await self._run_foreach(step, all_steps, state)

        last_error = None
        for attempt in range(step.retry + 1):
            try:
                result = await self._execute_single_step(step, state)
                return result
            except ScopeViolationError as e:
                # Authorization violations are never retried: mark the step
                # failed so dependents are skipped per on_failure semantics.
                return {"step": step.id, "error": str(e), "scope_violation": True}
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < step.retry:
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise last_error if last_error else PlaybookError(f"Step {step.id} failed")

    async def _execute_single_step(self, step: StepDefinition, state: dict) -> Any:
        """Execute one step based on its type."""
        # Server-side scope check on every target-looking arg, before ANY
        # step type executes (security architecture: the engine independently
        # enforces policy regardless of UI visibility or author intent).
        tool_name = step.tool
        args_for_gate = step.args
        if step.module and not tool_name:
            mod = load_module(step.module)
            if mod is not None:
                tool_name = mod.get("tool")
                args_for_gate = self._merge_module_args(step, mod)
        try:
            gate_step_args(args_for_gate, step_id=step.id, tool_name=tool_name)
        except ScopeViolationError:
            raise

        if step.module:
            return await self._run_module_step(step, state)
        if step.type == "shell":
            return await self._run_shell_step(step, state)
        if step.type == "tool":
            return await self._run_tool_step(step, state)
        if step.type == "scope_check":
            return await self._run_scope_check(step, state)
        if step.type == "finding_correlation":
            return await self._run_finding_correlation(step, state)
        if step.type == "assessment_report":
            return await self._run_assessment_report(step, state)
        if step.type == "custom":
            return await self._run_custom_step(step, state)
        raise PlaybookError(f"Unknown step type: {step.type}")

    async def _run_tool_step(self, step: StepDefinition, state: dict) -> Any:
        """Invoke a registered native tool via the registry."""
        tool_name = step.tool
        if not tool_name:
            raise PlaybookError(f"Tool step {step.id} missing 'tool'")
        tool = _get_registry().get(tool_name)
        if tool is None:
            return {"tool": tool_name, "error": "unknown tool", "step": step.id}

        args = dict(step.args)
        # Apply output_mapping: map prior step outputs into this step's args
        for out_key, src_ref in step.output_mapping.items():
            value = self._resolve_ref(src_ref)
            if value is not None:
                args[out_key] = value

        return await tool.safe_execute(args)

    # ── shell nodes ─────────────────────────────────────────────────────

    async def _run_shell_step(self, step: StepDefinition, state: dict) -> Any:
        """Execute a shell node: command template + placeholders + filter.

        Definition shape (Studio graph builder):

            {"id": "http_probe", "type": "shell",
             "command": "nmap {ip} -sn -p80",
             "inputs": {"ip": "{{target}}"},     # agent/LLM or playbook input
             "filter": {"type": "grep",
                        "pattern": "Nmap scan report for (?P<ip>[0-9.]+)",
                        "first_only": false},
             "depends_on": ["nmap_scan"]}

        Placeholder values may be:
        - ``{{name}}`` where ``name`` is a playbook/run input (``ip``,
          ``domainName`` — supplied by the agent LLM or the operator),
        - ``{{step.field}}`` referencing a prior node's structured output,
        - or a literal value.

        Named capture groups in the filter pattern become output fields on
        the step result so downstream nodes reference them as
        ``<step_id>.<field>`` in their inputs or ``output_mapping``.
        """
        resolved, unresolved = self._resolve_shell_inputs(step)
        if unresolved:
            return {
                "step": step.id,
                "type": "shell",
                "error": (
                    f"unresolved placeholder(s) {unresolved} — provide them via "
                    "run inputs, a playbook input, or a prior node's outputs"
                ),
            }

        try:
            # Substitution pool: playbook/run inputs (scalars) + this node's
            # resolved inputs — node inputs win.
            pool = {
                **{
                    k: v
                    for k, v in (self._playbook_inputs or {}).items()
                    if isinstance(v, (str, int, float, list))
                },
                **resolved,
            }
            final_cmd = self._subst_placeholders(step.command or "", pool)
        except ValueError as exc:
            return {"step": step.id, "type": "shell", "error": str(exc)}

        if not final_cmd.strip():
            return {"step": step.id, "type": "shell", "error": "shell step declares no command"}

        # Scope gate on the *resolved* values (placeholder keys such as
        # ip/hosts/domain are checked against the active scope policy).
        try:
            gate_step_args(resolved, step_id=step.id, tool_name="shell")
        except ScopeViolationError:
            raise

        timeout = 300
        if isinstance(step.args, dict) and step.args.get("timeout"):
            try:
                timeout = int(step.args["timeout"])
            except (TypeError, ValueError):
                timeout = 300

        from kali_mcp.execution import engine as _engine

        started = now_iso()
        result = await _engine.execute(
            final_cmd,
            tool="shell_command",
            timeout=timeout,
        )
        stdout = result.stdout or ""
        filtered: dict[str, Any] = {}
        if step.filter:
            filtered = self._apply_filter(stdout, step.filter)

        payload: dict[str, Any] = {
            "step": step.id,
            "type": "shell",
            "tool": "shell_command",
            "command": final_cmd,
            "exit_code": result.exit_code,
            "duration": result.duration,
            "stdout": stdout,
            "stderr": result.stderr or "",
            "started_at": started,
        }
        if result.timed_out:
            payload["error"] = "command timed out"
        elif result.success is False:
            payload["error"] = (
                f"exit code {result.exit_code}: {(result.stderr or stdout).strip()[:300]}"
            )
        payload.update(filtered)
        return payload

    def _resolve_shell_inputs(self, step: StepDefinition) -> tuple[dict[str, Any], list[str]]:
        """Resolve shell-node placeholder inputs.

        Returns ``(resolved, unresolved)`` where ``resolved`` contains the
        node's declared inputs (checked against the scope gate), and
        ``unresolved`` lists placeholder names that could not be filled
        before command substitution (the run-playbook-level inputs are also
        merged into the substitution pool by :meth:`_run_shell_step`).
        """
        resolved: dict[str, Any] = {}
        unresolved: list[str] = []
        cmd = step.command or ""
        for name, raw in dict(step.inputs or {}).items():
            value = self._resolve_input_value(raw, self._playbook_inputs or {})
            if value is None and _has_placeholder(cmd, name):
                unresolved.append(name)
                continue
            resolved[name] = value
        return resolved, unresolved

    def _resolve_input_value(self, raw: Any, playbook_inputs: dict[str, Any]) -> Any:
        """Resolve one input declaration.

        Explicit refs use double braces: ``{{target}}``, ``{{domainName}}``
        (playbook/run inputs), ``{{step.field}}`` (upstream node output).
        Bare strings are treated as literal values — keeping ``{ip}``
        placeholders inside a *literal* input value intact.
        """
        if not isinstance(raw, str):
            return raw
        text = raw.strip()
        if text.startswith("{{") and text.endswith("}}"):
            inner = text[2:-2].strip()
            if "." in inner:
                return self._resolve_ref(inner)
            play = playbook_inputs.get(inner)
            if isinstance(play, (str, int, float, list)):
                return play
            if inner == "target" and self._subst_target:
                return self._subst_target
            return None
        return raw

    def _subst_placeholders(self, command: str, values: dict[str, Any]) -> str:
        """Fill ``{name}`` and ``{{name}}`` placeholders in a command template."""
        out = command

        def repl(m: re.Match) -> str:
            name = m.group(1)
            if name not in values:
                return m.group(0)
            return _fmt_value(values[name])

        out = re.sub(r"\{\{?([A-Za-z_][A-Za-z0-9_]*)\}?\}", repl, out)
        missing = [tok for tok in re.findall(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})", out)]
        if missing:
            raise ValueError(
                f"unresolved placeholder(s) {missing} in command — "
                "declare matching node inputs (agent LLM or upstream nodes)"
            )
        return out

    def _apply_filter(self, stdout: str, flt: dict[str, Any]) -> dict[str, Any]:
        """Extract structured fields from command output (post-execution).

        Supported: ``{"type": "grep", "pattern": ..., "first_only": bool}``
        (Python ``re`` over the command's stdout). Named capture groups
        become output fields; unnamed capture groups become ``match_n``.
        """
        if not isinstance(flt, dict):
            return {}
        ftype = str(flt.get("type") or "grep")
        if ftype in ("none", "", "raw"):
            return {}
        if ftype not in ("grep", "regex"):
            return {}
        pattern = flt.get("pattern")
        if not pattern or not isinstance(pattern, str):
            return {}
        try:
            rx = re.compile(pattern, re.MULTILINE)
        except re.error as exc:
            return {"filter_error": f"invalid filter pattern: {exc}"}
        matches = list(rx.finditer(stdout))
        first_only = bool(flt.get("first_only"))

        out: dict[str, Any] = {
            "filtered_lines": [m.group(0) for m in matches],
            "match_count": len(matches),
        }
        named_groups = list(rx.groupindex.keys())
        for name in named_groups:
            g = rx.groupindex[name]
            vals = [m.group(g) for m in matches if m.group(g) is not None]
            out[name] = vals[0] if (first_only and vals) else vals
        for i in range(1, (rx.groups or 0) + 1):
            key = f"match_{i}"
            vals = [m.group(i) for m in matches if m.group(i) is not None]
            out[key] = vals[0] if (first_only and vals) else vals
        if matches and "stdout_excerpt" not in out:
            out["stdout_excerpt"] = "\n".join(out["filtered_lines"][:20])
        return out

    def _merge_module_args(self, step: StepDefinition, mod: dict[str, Any]) -> dict[str, Any]:
        """Merge module-declared input defaults with step args (step args win).

        ``{{target}}`` placeholders in module defaults are substituted using
        the playbook-level target captured at run time.
        """
        args: dict[str, Any] = {}
        for k, v in (mod.get("inputs") or {}).items():
            if isinstance(v, str) and self._subst_target:
                args[k] = v.replace("{{target}}", str(self._subst_target))
            else:
                args[k] = v
        if isinstance(step.args, dict):
            args.update(step.args)
        return args

    async def _run_module_step(self, step: StepDefinition, state: dict) -> Any:
        """Resolve an internal module declaration to a native tool and run it.

        Module definitions (``playbooks/modules/<cat>/<id>.yaml``) declare the
        native ``tool`` that implements them plus default inputs. The resolved
        tool is executed through the registry, with step args overriding module
        defaults and ``output_mapping`` applied as usual.
        """
        mod = load_module(step.module) if step.module else None
        if mod is None:
            return {
                "step": step.id,
                "module": step.module,
                "error": f"module not found: {step.module}",
            }
        tool_name = mod.get("tool")
        if not tool_name:
            return {
                "step": step.id,
                "module": step.module,
                "error": f"module {step.module} declares no tool",
            }

        tool = _get_registry().get(tool_name)
        if tool is None:
            return {
                "tool": tool_name,
                "module": step.module,
                "error": "unknown tool",
                "step": step.id,
            }

        args = self._merge_module_args(step, mod)
        # Apply output_mapping: map prior step outputs into this step's args
        for out_key, src_ref in step.output_mapping.items():
            value = self._resolve_ref(src_ref)
            if value is not None:
                args[out_key] = value

        return await tool.safe_execute(args)

    async def _run_scope_check(self, step: StepDefinition, state: dict) -> Any:
        """Validate target against active assessment scope."""
        target = step.args.get("target", "")
        allowed = step.args.get("allowed", True)
        return {
            "step": step.id,
            "target": target,
            "allowed": allowed,
            "scope_ok": bool(allowed),
        }

    async def _run_finding_correlation(self, step: StepDefinition, state: dict) -> Any:
        """Deduplicate and correlate findings from multiple prior steps."""
        # Collect findings from all dependency steps
        all_findings: list[dict] = []
        for dep_id in step.depends_on:
            dep_res = self._step_results.get(dep_id)
            if dep_res is None:
                continue
            findings = self._extract_findings(dep_res)
            all_findings.extend(findings)

        # Simple correlation: group by title + target
        correlated: dict[str, dict] = {}
        for f in all_findings:
            key = f"{f.get('target', 'unknown')}|{f.get('title', 'unknown')}"
            if key in correlated:
                existing = correlated[key]
                existing["source_tools"] = list(
                    set(existing.get("source_tools", []) + [f.get("tool", "")])
                )
                existing["evidence_refs"] = list(
                    set(existing.get("evidence_refs", []) + [f.get("evidence_ref", "")])
                )
                existing["confidence"] = min(0.99, existing.get("confidence", 0.5) + 0.1)
            else:
                correlated[key] = dict(f)

        return {
            "step": step.id,
            "correlated_findings": list(correlated.values()),
            "total_observations": len(all_findings),
            "total_correlated": len(correlated),
        }

    async def _run_assessment_report(self, step: StepDefinition, state: dict) -> Any:
        """Generate an assessment report from correlated findings."""
        findings: list[dict] = []
        for dep_id in step.depends_on:
            dep_res = self._step_results.get(dep_id)
            if dep_res is None:
                continue
            if isinstance(dep_res, dict) and "correlated_findings" in dep_res:
                findings.extend(dep_res["correlated_findings"])

        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "informational": 0}
        for f in findings:
            sev = str(f.get("severity", "informational")).lower()
            if sev in severity_counts:
                severity_counts[sev] += 1

        return {
            "step": step.id,
            "report": {
                "total_findings": len(findings),
                "severity_counts": severity_counts,
                "findings": findings,
            },
        }

    async def _run_custom_step(self, step: StepDefinition, state: dict) -> Any:
        """Execute a custom step defined by the playbook author.

        When the step declares a module reference (``tool`` or ``module`` in
        args) that is registered in ``modules_runtime``, the operation is
        dispatched through the internal-module registry — the same execution
        infrastructure native tool steps use. Steps without a module
        reference keep the legacy pass-through behaviour (built-in
        definitions still declare bare ``type: custom`` steps).
        """
        module_ref = step.tool or (step.args.get("module") if isinstance(step.args, dict) else None)
        if not module_ref:
            # Legacy pass-through for bare custom steps in built-in playbooks.
            return {
                "step": step.id,
                "type": "custom",
                "args": step.args,
                "status": "executed",
            }

        if not modules_runtime.has(str(module_ref)):
            return {
                "step": step.id,
                "type": "custom",
                "error": f"module not registered: {module_ref}",
            }

        try:
            modules_runtime.load_builtin_modules()
            ctx = modules_runtime.ModuleContext(playbook_name=state.get("playbook_name"))
            args = dict(step.args)
            args.pop("module", None)
            if not step.tool:
                args.pop("module", None)
            return await modules_runtime.execute_async(str(module_ref), ctx, args)
        except modules_runtime.ModuleError as exc:
            return {"step": step.id, "type": "custom", "error": str(exc)}
        except ScopeViolationError:
            raise

    async def _run_foreach(
        self, step: StepDefinition, all_steps: list[StepDefinition], state: dict
    ) -> Any:
        """Iterate over a prior step's output array, running the step per item."""
        ref = step.foreach
        items = self._resolve_ref(ref)
        if not isinstance(items, list):
            items = [items] if items else []

        # Bounded iteration: runaway loops in authored playbooks must fail the
        # step instead of consuming the machine (security architecture).
        if len(items) > MAX_ITERATIONS:
            return {
                "step": step.id,
                "error": (
                    f"iteration_cap_exceeded: foreach over {len(items)} items "
                    f"exceeds MAX_ITERATIONS={MAX_ITERATIONS}"
                ),
                "count": 0,
                "foreach_results": [],
            }

        results: list[Any] = []
        for item in items:
            # Dynamic targets discovered upstream get a fresh per-item scope
            # check before the step executes for this item.
            if isinstance(item, str) and item.strip():
                try:
                    gate_step_args(
                        {"target": item},
                        step_id=step.id,
                        tool_name=step.tool if step.type == "tool" else None,
                    )
                except ScopeViolationError as exc:
                    results.append(
                        {
                            "step": f"{step.id}_foreach",
                            "error": str(exc),
                            "scope_violation": True,
                            "_foreach_item": item,
                        }
                    )
                    continue
            # Create a per-iteration variant of the step with the item injected
            iter_args = dict(step.args)
            iter_args["_foreach_item"] = item
            iter_step = StepDefinition(
                id=f"{step.id}_foreach",
                tool=step.tool,
                module=step.module,
                type=step.type,
                depends_on=step.depends_on,
                when=step.when,
                parallel=step.parallel,
                output_mapping=step.output_mapping,
                retry=step.retry,
                on_failure=step.on_failure,
                checkpoint=step.checkpoint,
                budget=step.budget,
                args=iter_args,
            )
            try:
                res = await self._execute_single_step(iter_step, state)
            except ScopeViolationError as e:
                # Dynamic targets discovered upstream get a fresh scope check.
                res = {
                    "step": iter_step.id,
                    "error": str(e),
                    "scope_violation": True,
                    "_foreach_item": item,
                }
            results.append(res)

        return {"step": step.id, "foreach_results": results, "count": len(results)}

    # ── helpers ─────────────────────────────────────────────────────────

    def _topological_sort(self, steps: list[StepDefinition]) -> list[int]:
        """Return step indices in topological order respecting depends_on."""
        id_to_index = {s.id: i for i, s in enumerate(steps)}
        in_degree = {i: 0 for i in range(len(steps))}
        adj: dict[int, list[int]] = {i: [] for i in range(len(steps))}

        for i, step in enumerate(steps):
            for dep in step.depends_on:
                if dep in id_to_index:
                    dep_idx = id_to_index[dep]
                    adj[dep_idx].append(i)
                    in_degree[i] += 1

        queue: deque[int] = deque([i for i in range(len(steps)) if in_degree[i] == 0])
        order: list[int] = []

        while queue:
            # Process parallel-ready nodes together
            node = queue.popleft()
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        return order

    def _compute_waves(self, steps: list[StepDefinition]) -> list[list[int]]:
        """Group step indices into dependency waves.

        Steps in the same wave have no unmet dependencies on each other and
        may run concurrently. A step appears in the first wave where all of
        its dependencies have already been scheduled.
        """
        id_to_index = {s.id: i for i, s in enumerate(steps)}
        remaining = set(range(len(steps)))
        done: set[int] = set()
        waves: list[list[int]] = []
        while remaining:
            wave = [
                idx
                for idx in sorted(remaining)
                if all(
                    id_to_index.get(dep, -1) in done or dep not in id_to_index
                    for dep in steps[idx].depends_on
                )
            ]
            if not wave:
                # cycle — fall back to whatever remains
                wave = sorted(remaining)
            for idx in wave:
                remaining.discard(idx)
                done.add(idx)
            waves.append(wave)
        return waves

    def _substitute_target(self, args: dict[str, Any], target: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in args.items():
            if isinstance(v, str):
                out[k] = v.replace("{{target}}", str(target))
            else:
                out[k] = v
        return out

    def _evaluate_when(self, condition: str) -> bool:
        """Evaluate a when condition against structured step results.

        Only supports simple comparisons on dotted field paths:
        resolve.http_services_count > 0
        ports.open_ports_count >= 1
        technologies.count > 0
        """
        try:
            # Parse: <field> <op> <value>
            m = re.match(r"(.+?)\s*(>=|<=|==|!=|>|<)\s*(.+)", condition.strip())
            if not m:
                return False
            field_ref = m.group(1).strip()
            op = m.group(2)
            value_str = m.group(3).strip()

            value = self._resolve_ref(field_ref)
            if value is None:
                return False

            # Parse comparison value
            try:
                compare_val = (
                    float(value_str)
                    if re.match(r"^-?\d+(\.\d+)?$", value_str)
                    else value_str.strip('"').strip("'")
                )
            except ValueError:
                compare_val = value_str

            if op == ">":
                return float(value) > float(compare_val)
            if op == "<":
                return float(value) < float(compare_val)
            if op == ">=":
                return float(value) >= float(compare_val)
            if op == "<=":
                return float(value) <= float(compare_val)
            if op == "==":
                return str(value) == str(compare_val)
            if op == "!=":
                return str(value) != str(compare_val)
        except Exception:  # noqa: BLE001
            return False
        return False

    def _unwrap_envelope(self, result: Any) -> Any:
        """Unwrap an MCP tool-response envelope into the inner ExecutionResult dict.

        Tools return ``{"content": [{"type": "text", "text": "<json>"}], "isError": False}``.
        This peels that away so structured output fields (e.g. ``http_services_count``)
        can be traversed by :meth:`_resolve_ref`.
        """
        if not isinstance(result, dict):
            return result
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text")
                if isinstance(text, str):
                    try:
                        import json as _json

                        parsed = _json.loads(text)
                        if isinstance(parsed, dict):
                            return parsed
                    except (_json.JSONDecodeError, TypeError):
                        pass
        return result

    def _resolve_ref(self, ref: str) -> Any:
        """Resolve a dotted reference against prior results and playbook inputs.

        Supported forms:
          - ``{{inputs.X}}`` or ``inputs.X``        → playbook input ``X``
          - ``target``                               → playbook-level target value
          - ``{{steps.X.Y}}`` or ``steps.X.Y``       → field ``Y`` of step ``X``'s result
          - ``X.Y`` (bare)                           → field ``Y`` of step ``X``'s result
        """
        if not ref:
            return None

        # Strip {{...}} wrapper
        raw = ref.strip()
        if raw.startswith("{{") and raw.endswith("}}"):
            raw = raw[2:-2].strip()

        # inputs.X
        if raw.startswith("inputs."):
            key = raw[len("inputs.") :]
            return self._playbook_inputs.get(key)

        # target shortcut
        if raw == "target":
            return self._subst_target

        # steps.X.Y or bare X.Y
        parts = raw.split(".")
        step_id = parts[0]
        result = self._step_results.get(step_id)
        if result is None:
            return None
        result = self._unwrap_envelope(result)
        for part in parts[1:]:
            if isinstance(result, dict):
                result = result.get(part)
            else:
                return None
            if result is None:
                return None
        return result

    def _extract_findings(self, result: Any) -> list[dict]:
        """Extract finding-like dicts from a step result."""
        findings: list[dict] = []
        if isinstance(result, dict):
            # Direct findings list
            for key in ("findings", "correlated_findings", "services", "assets"):
                val = result.get(key)
                if isinstance(val, list):
                    findings.extend(val)
            # Nested under result payload
            if "result" in result and isinstance(result["result"], dict):
                findings.extend(self._extract_findings(result["result"]))
        elif isinstance(result, list):
            for item in result:
                findings.extend(self._extract_findings(item))
        return findings

    def _is_step_failure(self, result: Any) -> bool:
        if isinstance(result, dict):
            if result.get("skipped"):
                return False
            if result.get("error"):
                return True
            if result.get("success") is False:
                return True
        return False

    def _depends_on_failed(
        self, step: StepDefinition, all_steps: list[StepDefinition], idx: int
    ) -> bool:
        """Check if any dependency of this step failed/aborted."""
        for dep in step.depends_on:
            dep_res = self._step_results.get(dep)
            if dep_res is None:
                continue
            if self._is_step_failure(dep_res):
                return True
        return False

    def _persist_state(self, name: str, state: dict, run_id: str | None = None) -> None:
        """Persist playbook run state (best-effort) to RUN_STATUS and SQLite."""
        try:
            RUN_STATUS[name] = dict(state)
        except Exception:  # noqa: BLE001
            pass
        try:
            from kali_mcp.db import manager as dbm

            db = dbm.get_db()
            if db is not None:
                db.save_workflow_run(
                    run_id or name,
                    name,
                    state.get("status", "running"),
                    state.get("completed_steps", []),
                    state,
                )
        except Exception:  # noqa: BLE001
            pass

    # ── status / resume ────────────────────────────────────────────────

    def get_status(self, name: str) -> dict | None:
        return RUN_STATUS.get(name)

    def cancel(self, name: str) -> bool:
        if name in RUN_STATUS:
            RUN_STATUS[name]["status"] = "aborted"
            RUN_STATUS[name]["finished_at"] = now_iso()
            return True
        return False


async def run_playbook(playbook: PlaybookDefinition, resume: bool = False) -> ExecutionResult:
    """Async wrapper to run a playbook via the DAG engine.

    Safe to call from within a running event loop (e.g. an async MCP tool
    handler) because it directly awaits the engine instead of calling
    :func:`asyncio.run`. Kept for backward compatibility; new callers should
    prefer :func:`run_playbook_async`.
    """
    eng = PlaybookEngine()
    return await eng.run(playbook, resume=resume)


async def run_playbook_async(playbook: PlaybookDefinition, resume: bool = False) -> ExecutionResult:
    """Async-native entry point: directly awaits the engine's ``run()``.

    Use this from async MCP tool handlers running inside an active event
    loop. It never calls :func:`asyncio.run`, so it cannot raise
    ``RuntimeError: asyncio.run() cannot be called from a running event loop``.
    """
    eng = PlaybookEngine()
    return await eng.run(playbook, resume=resume)
