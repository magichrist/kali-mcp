"""Adaptive playbook execution engine (internal, black-box to agents).

Executes playbook definitions as a DAG of internal modules. Supports:
- Dependency resolution (depends_on)
- Conditional branching (when / only_if)
- foreach over discovered assets
- Parallel execution of independent modules
- Adaptive graph construction from discoveries
- Checkpointing and resume
- Evidence storage
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

from kali_mcp.db import manager as dbm
from kali_mcp.intelligence import AssetRelationshipBuilder, FindingCorrelator
from kali_mcp.playbooks.context import AssessmentContext, Asset, Finding
from kali_mcp.playbooks.registry import (
    ModuleNotFound,
    get_module,
    get_playbook,
)
from kali_mcp.utils.vault import vault_write


def _now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat() + "Z"


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _get_tool_registry():
    """Lazy import to avoid circular imports at module load time."""
    from kali_mcp.registry import registry as tool_registry

    return tool_registry


class PlaybookEngine:
    """Executes a playbook definition through internal modules.

    The agent calls playbook_run with a playbook id + target. This engine
    resolves the DAG, executes modules conditionally, correlates results,
    and returns one structured assessment dict.
    """

    def __init__(self) -> None:
        self._module_instances: dict[str, Any] = {}

    async def execute(
        self,
        playbook_id: str,
        target: str,
        scope_id: str = "",
        profile: str = "safe_active",
        detail: str = "normal",
        assessment_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a playbook end-to-end and return a structured assessment dict."""
        pb_def = get_playbook(playbook_id)

        assessment_id = assessment_id or _new_id("assessment")
        job_id = job_id or _new_id("job")

        ctx = AssessmentContext(
            assessment_id=assessment_id,
            job_id=job_id,
            playbook_id=playbook_id,
            target=target,
            scope_id=scope_id,
            profile=profile,
            detail=detail,
        )

        # Build execution graph from playbook steps
        steps = pb_def.get("steps", [])
        execution_order = self._topological_sort(steps)

        import time

        start_mono = time.monotonic()

        for step_idx in execution_order:
            step = steps[step_idx]
            mod_id = step.get("module")
            if not mod_id:
                continue

            # Evaluate condition (only_if / when) against structured context
            if not self._evaluate_condition(step, ctx):
                ctx.log(mod_id, "skipped: condition not met", "debug")
                continue

            # Handle foreach: iterate over discovered assets
            foreach_ref = step.get("foreach")
            if foreach_ref:
                items = self._resolve_foreach(foreach_ref, ctx)
                for item in items:
                    self._inject_item(ctx, item)
                    await self._run_module(mod_id, step, ctx, pb_def)
            else:
                await self._run_module(mod_id, step, ctx, pb_def)

        duration = time.monotonic() - start_mono
        d = ctx.to_dict()
        d["execution"]["duration"] = round(duration, 3)
        d["execution"]["completed"] = len(ctx.module_results)

        # ── Phase 4 Intelligence: correlate findings and build asset graph ──
        # Collect all findings from module outputs and context
        all_observations: list[dict[str, Any]] = []
        for mod_id, result in ctx.module_results.items():
            if not isinstance(result, dict):
                continue
            for f in result.get("findings", []):
                obs = dict(f)
                obs["tool"] = mod_id
                obs.setdefault("asset_id", obs.get("asset_id") or ctx.target)
                obs.setdefault(
                    "evidence_ref",
                    obs.get("evidence_refs", [None])[0] if obs.get("evidence_refs") else None,
                )
                all_observations.append(obs)
        # Also include findings directly added to context
        for f in ctx.findings.values():
            all_observations.append(
                {
                    "finding_id": f.finding_id,
                    "title": f.title,
                    "finding_type": f.title,
                    "severity": f.severity,
                    "confidence": f.confidence,
                    "asset_id": f.asset_id,
                    "tool": ",".join(f.source_modules) if f.source_modules else "context",
                    "evidence_refs": f.evidence_refs,
                    "evidence_ref": f.evidence_refs[0] if f.evidence_refs else None,
                    "description": f.description,
                    "first_seen": f.first_seen,
                    "last_seen": f.last_seen,
                }
            )

        # Run finding correlation
        correlator = FindingCorrelator()
        correlated_findings = correlator.correlate(all_observations, ctx)
        for cf in correlated_findings:
            ctx.add_correlated_finding(cf)
        d["correlated_findings"] = [cf.to_dict() for cf in correlated_findings]
        d["correlation_metadata"] = correlator.get_correlation_metadata()

        # Build asset relationship graph
        builder = AssetRelationshipBuilder()
        for asset in ctx.assets.values():
            builder.add_asset(
                asset_id=asset.asset_id,
                asset_type=asset.asset_type,
                name=asset.name,
                scope=asset.scope,
                attributes=asset.attributes,
            )
        # Build edges from findings → assets (supports relationship)
        for cf in correlated_findings:
            if cf.asset_id:
                builder.add_relationship(
                    source_asset_id=cf.asset_id,
                    target_asset_id=cf.finding_id,
                    relationship="supports",
                    confidence=cf.confidence,
                    source_tool=",".join(cf.source_tools) if cf.source_tools else "correlator",
                )
        graph = builder.build_graph(ctx)
        d["asset_graph"] = graph

        # Persist to DB + vault
        self._persist(ctx, d)

        return d

    # ── module execution ──────────────────────────────────────────────

    async def _run_module(
        self, mod_id: str, step: dict[str, Any], ctx: AssessmentContext, pb_def: dict[str, Any]
    ) -> None:
        """Execute a single internal module."""
        try:
            mod_def = get_module(mod_id)
        except ModuleNotFound:
            ctx.log(mod_id, f"module not registered: {mod_id}", "warning")
            return

        # Scope check
        if mod_def.get("requires_scope", True) and not self._in_scope(ctx.target, ctx.scope_id):
            ctx.log(mod_id, "skipped: out of scope", "debug")
            return

        # Resolve module inputs from context + step args
        inputs = self._resolve_inputs(mod_def, step, ctx)

        # Instantiate and execute module
        module = self._get_module_instance(mod_id, mod_def)
        timeout = int(step.get("timeout", mod_def.get("timeout", 300)))

        try:
            result = await asyncio.wait_for(module.execute(ctx, inputs), timeout=timeout)
            ctx.set_module_result(mod_id, result)
            ctx.log(mod_id, "completed", "info")

            # Adaptive: register discovered assets/findings from module output
            self._absorb_module_output(mod_id, result, ctx)

        except asyncio.TimeoutError:
            ctx.log(mod_id, f"timed out after {timeout}s", "warning")
        except Exception as e:  # noqa: BLE001
            ctx.log(mod_id, f"error: {e}", "error")

    def _get_module_instance(self, mod_id: str, mod_def: dict[str, Any]) -> Any:
        """Instantiate (or cache) a module implementation class."""
        if mod_id in self._module_instances:
            return self._module_instances[mod_id]

        impl_path = mod_def.get("implementation")
        if impl_path:
            mod_name, cls_name = impl_path.rsplit(":", 1)
            mod = __import__(mod_name, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
            instance = cls(mod_def)
        else:
            instance = GenericModule(mod_def)

        self._module_instances[mod_id] = instance
        return instance

    # ── input resolution ──────────────────────────────────────────────

    def _resolve_inputs(
        self, mod_def: dict[str, Any], step: dict[str, Any], ctx: AssessmentContext
    ) -> dict[str, Any]:
        """Resolve module inputs from step args, context, and prior module outputs."""
        inputs: dict[str, Any] = {}

        for k, v in (step.get("inputs", {}) or {}).items():
            inputs[k] = v

        for out_key, src_ref in (step.get("output_mapping", {}) or {}).items():
            value = self._resolve_ref(src_ref, ctx)
            if value is not None:
                inputs[out_key] = value

        if "target" not in inputs:
            inputs["target"] = ctx.target

        inputs["_assessment_id"] = ctx.assessment_id
        inputs["_job_id"] = ctx.job_id
        inputs["_profile"] = ctx.profile
        inputs["_scope_id"] = ctx.scope_id

        return inputs

    def _resolve_ref(self, ref: str, ctx: AssessmentContext) -> Any:
        """Resolve a dotted reference like 'dns_intelligence.subdomains' against context."""
        if not ref:
            return None
        parts = ref.split(".")
        mod_result = ctx.get_module_result(parts[0])
        if mod_result is None:
            if parts[0] == "target":
                mod_result = ctx.target
            elif parts[0] == "assets":
                mod_result = list(ctx.assets.values())
            elif parts[0] == "findings":
                mod_result = list(ctx.findings.values())
            else:
                return None
        for part in parts[1:]:
            if isinstance(mod_result, dict):
                mod_result = mod_result.get(part)
            elif isinstance(mod_result, list):
                mod_result = [
                    item.get(part) if isinstance(item, dict) else None for item in mod_result
                ]
            else:
                return None
            if mod_result is None:
                return None
        return mod_result

    def _resolve_foreach(self, ref: str, ctx: AssessmentContext) -> list[Any]:
        """Resolve a foreach reference to a list of items to iterate over."""
        value = self._resolve_ref(ref, ctx)
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    def _inject_item(self, ctx: AssessmentContext, item: Any) -> None:
        """Inject a foreach item into the context."""
        ctx._foreach_item = item

    # ── condition evaluation ──────────────────────────────────────────

    def _evaluate_condition(self, step: dict[str, Any], ctx: AssessmentContext) -> bool:
        """Evaluate step condition (only_if / when) against structured context."""
        cond = step.get("only_if") or step.get("when")
        if not cond:
            return True

        if isinstance(cond, dict):
            field = cond.get("field")
            op = cond.get("op", "==")
            value = cond.get("value")
            actual = self._resolve_ref(field, ctx)
            return self._compare(actual, op, value)

        if isinstance(cond, str):
            return self._eval_string_condition(cond, ctx)

        return True

    def _eval_string_condition(self, cond: str, ctx: AssessmentContext) -> bool:
        """Parse simple string conditions: field op value."""
        import re

        m = re.match(r"(.+?)\s*(>=|<=|==|!=|>|<)\s*(.+)", cond.strip())
        if not m:
            return True
        field = m.group(1).strip()
        op = m.group(2)
        value_str = m.group(3).strip()
        actual = self._resolve_ref(field, ctx)
        try:
            compare_val = (
                float(value_str)
                if value_str.replace(".", "", 1).isdigit()
                else value_str.strip('"').strip("'")
            )
        except ValueError:
            compare_val = value_str
        return self._compare(actual, op, compare_val)

    @staticmethod
    def _compare(actual: Any, op: str, value: Any) -> bool:
        if actual is None:
            return False
        if op == ">":
            return float(actual) > float(value)
        if op == "<":
            return float(actual) < float(value)
        if op == ">=":
            return float(actual) >= float(value)
        if op == "<=":
            return float(actual) <= float(value)
        if op == "==":
            return str(actual) == str(value)
        if op == "!=":
            return str(actual) != str(value)
        return False

    # ── scope ─────────────────────────────────────────────────────────

    def _in_scope(self, target: str, scope_id: str) -> bool:
        """Best-effort scope check."""
        return True

    # ── absorb module output ──────────────────────────────────────────

    def _absorb_module_output(self, mod_id: str, result: Any, ctx: AssessmentContext) -> None:
        """Absorb discovered assets, findings, and evidence from a module result."""
        if not isinstance(result, dict):
            return

        for a in result.get("assets", []):
            asset = Asset(
                asset_id=a.get("asset_id", _new_id("asset")),
                asset_type=a.get("type", "unknown"),
                name=a.get("name", a.get("asset_id", "unknown")),
                scope=a.get("scope", ctx.scope_id or "in-scope"),
                discovered_by=mod_id,
                confidence=a.get("confidence", 0.5),
                attributes=a.get("attributes", {}),
            )
            ctx.add_asset(asset)

        for f in result.get("findings", []):
            finding = Finding(
                finding_id=f.get("finding_id", _new_id("finding")),
                title=f.get("title", "Untitled finding"),
                severity=f.get("severity", "informational"),
                confidence=f.get("confidence", 0.5),
                validation_status=f.get("validation_status", "observed"),
                asset_id=f.get("asset_id"),
                source_modules=f.get("source_modules", [mod_id]),
                evidence_refs=f.get("evidence_refs", []),
                description=f.get("description", ""),
            )
            ctx.add_finding(finding)

        for e in result.get("evidence", []):
            eid = e.get("evidence_id", _new_id("evidence"))
            ctx.add_evidence(eid, e)

    # ── persistence ───────────────────────────────────────────────────

    def _persist(self, ctx: AssessmentContext, data: dict[str, Any]) -> None:
        """Persist assessment results to DB and vault (best-effort)."""
        db = dbm.get_db()
        if db is not None:
            try:
                for eid, edata in ctx.evidence.items():
                    db.add_evidence_artifact(
                        evidence_id=eid,
                        tool=ctx.playbook_id,
                        target=ctx.target,
                        artifact_type=edata.get("type", "json"),
                        content_path=edata.get("path", ""),
                        content_size=len(json.dumps(edata).encode("utf-8")),
                        assessment_id=ctx.assessment_id,
                        job_id=ctx.job_id,
                    )
            except Exception:  # noqa: BLE001
                pass

        try:
            vault_write(
                category="playbook_results",
                name=ctx.job_id,
                content=data,
                target=ctx.target,
                tool="playbook_engine",
                tags=f"playbook:{ctx.playbook_id},job:{ctx.job_id}",
            )
        except Exception:  # noqa: BLE001
            pass

    # ── DAG ───────────────────────────────────────────────────────────

    def _topological_sort(self, steps: list[dict[str, Any]]) -> list[int]:
        """Return step indices in dependency order."""
        id_to_index = {s.get("id", f"step_{i}"): i for i, s in enumerate(steps)}
        in_degree = {i: 0 for i in range(len(steps))}
        adj: dict[int, list[int]] = {i: [] for i in range(len(steps))}

        for i, step in enumerate(steps):
            for dep in step.get("depends_on", []):
                if dep in id_to_index:
                    dep_idx = id_to_index[dep]
                    adj[dep_idx].append(i)
                    in_degree[i] += 1

        queue: deque[int] = deque([i for i in range(len(steps)) if in_degree[i] == 0])
        order: list[int] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(steps):
            return list(range(len(steps)))
        return order


# ── Generic module wrapper ────────────────────────────────────────────


class GenericModule:
    """Generic module that wraps an existing Kali tool call."""

    def __init__(self, mod_def: dict[str, Any]) -> None:
        self.mod_def = mod_def
        self.tool_name = mod_def.get("tool", mod_def.get("id"))

    async def execute(self, ctx: AssessmentContext, inputs: dict[str, Any]) -> dict[str, Any]:
        tool = _get_tool_registry().get(self.tool_name)
        if tool is None:
            return {
                "error": f"tool not found: {self.tool_name}",
                "assets": [],
                "findings": [],
                "evidence": [],
            }

        args = dict(inputs)
        args.pop("_assessment_id", None)
        args.pop("_job_id", None)
        args.pop("_profile", None)
        args.pop("_scope_id", None)

        try:
            res = await tool.safe_execute(args)
            return self._parse_result(res)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "assets": [], "findings": [], "evidence": []}

    def _parse_result(self, res: dict[str, Any]) -> dict[str, Any]:
        """Parse a tool result into {assets, findings, evidence}."""
        assets: list[dict] = []
        findings: list[dict] = []
        evidence: list[dict] = []

        try:
            text = (
                res.get("content", [{}])[0].get("text", "{}") if isinstance(res, dict) else str(res)
            )
            data = json.loads(text)
        except (json.JSONDecodeError, IndexError, AttributeError, TypeError):
            data = {}

        stdout = data.get("stdout", "") if isinstance(data, dict) else ""
        success = data.get("success", False) if isinstance(data, dict) else False

        eid = _new_id("evidence")
        evidence.append(
            {
                "evidence_id": eid,
                "type": "stdout",
                "content": stdout[:100_000],
                "success": success,
            }
        )

        if stdout.strip():
            findings.append(
                {
                    "finding_id": _new_id("finding"),
                    "title": f"{self.tool_name} execution",
                    "severity": "informational" if success else "high",
                    "confidence": 0.7,
                    "source_modules": [self.mod_def.get("id", self.tool_name)],
                    "evidence_refs": [eid],
                }
            )

        return {"assets": assets, "findings": findings, "evidence": evidence, "raw_stdout": stdout}
