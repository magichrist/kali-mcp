"""Agent Interface Layer — Kali MCP v2.0.0.

Eight orchestration tools designed around AI agent security tasks, not
individual Kali commands. These sit above the 56 native wrappers and provide:

  assessment_run   — execute a complete assessment workflow (one call → assessment)
  batch_run        — run multiple independent operations concurrently
  job_control      — check, wait for, or cancel execution jobs
  findings_query   — search and filter normalized findings
  evidence_get     — retrieve detailed evidence for selected findings
  asset_graph      — retrieve discovered assets and their relationships
  tool_catalog     — search available tools and their capabilities
  report_generate  — produce an assessment report

Each tool follows the prompt-engineered description pattern:

  Purpose statement
  Use when: ...
  Inputs: ...
  Returns: ...
  Does not: ...

Output levels: summary | normal | full (raw stdout/stderr stored as artifacts,
retrieved only on demand via evidence_get).

Agent mode (default) exposes a compact subset; Expert mode exposes everything.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import uuid
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kali_mcp.config import config
from kali_mcp.db import manager as dbm
from kali_mcp.execution import engine
from kali_mcp.intelligence import (
    FindingCorrelator,
    AssetRelationshipBuilder,
    VerificationStates,
    CoverageTracker,
    AssessmentDiffer,
    DiffResult,
)
from kali_mcp.models import ExecutionResult, ToolError, utc_now_iso
from kali_mcp.responses import error_response, success_response
from kali_mcp.tools.base import BaseTool
from kali_mcp.utils.vault import vault_write, vault_query, vault_read, vault_stats

# Tool layer classification (used by tool_catalog and Agent vs Expert mode)
TOOL_LAYERS: dict[str, str] = {
    # Discovery layer
    "subfinder": "discovery",
    "amass": "discovery",
    "theharvester": "discovery",
    "spiderfoot": "discovery",
    "farsight": "discovery",
    "dnsx": "discovery",
    # Operations layer (native Kali wrappers)
    "nmap": "operations",
    "masscan": "operations",
    "naabu": "operations",
    "nuclei": "operations",
    "httpx": "operations",
    "whatweb": "operations",
    "ffuf": "operations",
    "gobuster": "operations",
    "dirb": "operations",
    "wfuzz": "operations",
    "katana": "operations",
    "arjun": "operations",
    "sqlmap": "operations",
    "commix": "operations",
    "wpscan": "operations",
    "zap": "operations",
    "searchsploit": "operations",
    "zizmor": "operations",
    # Workflows layer (playbooks)
    "playbook_recon": "workflows",
    "playbook_webapp": "workflows",
    "playbook_ad": "workflows",
    "playbook_engine": "workflows",
    "playbook_list": "workflows",
    "playbook_status": "workflows",
    # Intelligence layer
    "findings_query": "intelligence",
    "evidence_get": "intelligence",
    "asset_graph": "intelligence",
    "finding_transition": "intelligence",
    "assessment_diff": "intelligence",
    "coverage_summary": "intelligence",
    "report_generate": "intelligence",
    "tool_catalog": "intelligence",
    "assessment_run": "intelligence",
    "batch_run": "intelligence",
    "job_control": "intelligence",
    # Escape hatches (Expert mode only)
    "generic_command": "escape_hatch",
    "python_command": "escape_hatch",
    "file_read": "escape_hatch",
    "file_write": "escape_hatch",
    "file_download": "escape_hatch",
    # Vault tools
    "vault_write": "intelligence",
    "vault_read": "intelligence",
    "vault_query": "intelligence",
    "vault_list": "intelligence",
    "vault_delete": "intelligence",
    "vault_stats": "intelligence",
}

# Agent mode: compact tool set (layers discovery + workflows + intelligence,
# excluding escape hatches and most operations)
AGENT_MODE_TOOLS = {
    "assessment_run", "batch_run", "job_control", "findings_query",
    "evidence_get", "asset_graph", "report_generate", "tool_catalog",
    "finding_transition", "assessment_diff", "coverage_summary",
    "subfinder", "amass", "theharvester", "spiderfoot", "farsight",
    "nmap", "nuclei", "httpx", "whatweb", "ffuf", "katana",
    "playbook_recon", "playbook_webapp", "playbook_ad", "playbook_engine",
    "playbook_list", "playbook_status",
    "vault_write", "vault_read", "vault_query", "vault_list", "vault_stats",
}

# Expert mode: everything
EXPERT_MODE_TOOLS: set[str] = set(TOOL_LAYERS.keys())


# ── helpers ──────────────────────────────────────────────────────────────

def _new_id(prefix: str) -> str:
    """Generate an opaque identifier: <prefix>_<uuid hex>."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _normalize_output_level(detail: str) -> str:
    """Validate and normalize the output detail level."""
    if detail not in ("summary", "normal", "full"):
        return "summary"
    return detail


def _make_assessment_result(
    tool_name: str,
    assessment_id: str,
    status: str,
    summary: dict[str, Any],
    findings: list[dict[str, Any]],
    next_actions: list[str],
    job_id: str | None = None,
    detail: str = "summary",
    raw_included: bool = False,
) -> dict[str, Any]:
    """Build a normalized assessment result payload."""
    payload: dict[str, Any] = {
        "assessment_id": assessment_id,
        "status": status,
        "summary": summary,
        "findings": findings,
        "next_actions": next_actions,
        "output_level": detail,
        "raw_included": raw_included,
    }
    if job_id:
        payload["job_id"] = job_id
    result = ExecutionResult(
        tool=tool_name,
        command=tool_name,
        stdout=json.dumps(payload, indent=2),
        stderr="",
        exit_code=0,
        success=True,
        timed_out=False,
        duration=0.0,
        start_time=utc_now_iso(),
        end_time=utc_now_iso(),
    )
    return success_response(result)


def _extract_assets_from_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort extraction of asset references from finding records."""
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in findings:
        asset_id = f.get("asset_id")
        if asset_id and asset_id not in seen:
            seen.add(asset_id)
            assets.append(
                {
                    "asset_id": asset_id,
                    "name": f.get("asset_name", asset_id),
                    "type": f.get("asset_type", "unknown"),
                    "severity_max": f.get("severity", "informational"),
                }
            )
    return assets


# ── 1. assessment_run ────────────────────────────────────────────────────

class AssessmentRunTool(BaseTool):
    """Execute a complete assessment workflow in a single MCP call."""

    @property
    def name(self) -> str:
        return "assessment_run"

    @property
    def description(self) -> str:
        return (
            "Execute a complete security assessment workflow in one call.\n\n"
            "Use when:\n"
            "  - You want to assess a target without orchestrating individual tools.\n"
            "  - You need discovery, scanning, correlation, and reporting automated.\n"
            "  - You want a compact, actionable response instead of raw terminal output.\n\n"
            "Inputs:\n"
            "  - workflow: playbook name (web_assessment, network_assessment, external_recon,\n"
            "    ad_assessment, api_assessment, vulnerability_validation, custom_assessment).\n"
            "  - targets: array of target strings (domains, IPs, URLs).\n"
            "  - scope_id: optional scope identifier for authorization boundary.\n"
            "  - profile: execution profile (safe_active, aggressive, passive; default safe_active).\n"
            "  - execution: {max_parallel, max_duration, resume}.\n"
            "  - output: {detail: summary|normal|full, include_raw: bool}.\n\n"
            "Returns:\n"
            "  - assessment_id, status, summary (counts by severity), findings[],\n"
            "    next_actions[], and optionally job_id for long-running assessments.\n"
            "  - Raw stdout/stderr are stored as evidence artifacts, not returned by default.\n\n"
            "Does not: expose raw scanner output unless output.detail=full or via evidence_get.\n"
        )

    @property
    def default_timeout(self) -> int:
        return 3600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workflow": {
                    "type": "string",
                    "description": "Assessment workflow/playbook name (required)",
                },
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target domains, IPs, or URLs to assess (required)",
                },
                "scope_id": {
                    "type": "string",
                    "description": "Optional scope identifier for authorization boundary",
                },
                "profile": {
                    "type": "string",
                    "description": "Execution profile: safe_active, aggressive, passive",
                    "default": "safe_active",
                },
                "execution": {
                    "type": "object",
                    "description": "Execution controls: max_parallel, max_duration, resume",
                    "properties": {
                        "max_parallel": {"type": "integer", "default": 4},
                        "max_duration": {"type": "integer", "default": 900},
                        "resume": {"type": "boolean", "default": False},
                    },
                },
                "output": {
                    "type": "object",
                    "description": "Output verbosity controls",
                    "properties": {
                        "detail": {
                            "type": "string",
                            "description": "summary | normal | full",
                            "default": "summary",
                        },
                        "include_raw": {
                            "type": "boolean",
                            "description": "Include raw stdout/stderr in response",
                            "default": False,
                        },
                    },
                },
            },
            "required": ["workflow", "targets"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("workflow"):
            raise ValueError("workflow is required")
        targets = arguments.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ValueError("targets must be a non-empty array")
        profile = arguments.get("profile", "safe_active")
        if profile not in ("safe_active", "aggressive", "passive"):
            raise ValueError("profile must be safe_active, aggressive, or passive")
        exec_cfg = arguments.get("execution", {})
        if "max_parallel" in exec_cfg:
            mp = exec_cfg["max_parallel"]
            if not isinstance(mp, int) or mp < 1 or mp > 50:
                raise ValueError("max_parallel must be an integer between 1 and 50")
        if "max_duration" in exec_cfg:
            md = exec_cfg["max_duration"]
            if not isinstance(md, int) or md < 60 or md > 3600:
                raise ValueError("max_duration must be between 60 and 3600 seconds")
        out = arguments.get("output", {})
        if "detail" in out and out["detail"] not in ("summary", "normal", "full"):
            raise ValueError("output.detail must be summary, normal, or full")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["assessment_run"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        workflow = arguments["workflow"]
        targets = arguments["targets"]
        scope_id = arguments.get("scope_id")
        profile = arguments.get("profile", "safe_active")
        exec_cfg = arguments.get("execution", {})
        max_parallel = exec_cfg.get("max_parallel", 4)
        max_duration = exec_cfg.get("max_duration", 900)
        resume = exec_cfg.get("resume", False)
        output_cfg = arguments.get("output", {})
        detail = _normalize_output_level(output_cfg.get("detail", "summary"))
        include_raw = output_cfg.get("include_raw", False)

        assessment_id = _new_id("assessment")
        job_id = None

        # Persist assessment start to DB
        db = dbm.get_db()
        target_ids: list[int] = []
        if db is not None:
            for t in targets:
                tid = db.upsert_target(t, target_type="host", scope="in-scope")
                target_ids.append(tid)
            for tid in target_ids:
                db.conn.execute(
                    "INSERT INTO scans (target_id, tool, command, started_at, "
                    "completed_at, duration, success, findings_count, artifact_uri, "
                    "assessment_id, job_id, workflow_name) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        tid, workflow, f"assessment_run:{workflow}", _now_utc(),
                        _now_utc(), 0.0, 0, 0, None, assessment_id, job_id, workflow,
                    ),
                )
            db.conn.commit()

        # Determine if this is a "long" assessment (should return job_id immediately)
        is_long = max_duration > 300 or len(targets) > 3 or max_parallel > 4

        if is_long:
            job_id = _new_id("job")
            # Fire-and-forget the actual execution in background
            asyncio.create_task(
                self._run_assessment_background(
                    assessment_id, job_id, workflow, targets, scope_id, profile,
                    max_parallel, max_duration, resume, detail, include_raw,
                )
            )
            return _make_assessment_result(
                self.name, assessment_id, "accepted", {"assets_discovered": 0,
                 "services_discovered": 0, "findings": {"critical": 0, "high": 0,
                 "medium": 0, "low": 0}},
                [], ["Assessment accepted. Use job_control with job_id to track progress."],
                job_id=job_id, detail=detail, raw_included=include_raw,
            )

        # Short assessment: execute inline
        findings, assets, next_actions = await self._run_assessment_inline(
            workflow, targets, scope_id, profile, max_parallel, max_duration,
            resume, detail, include_raw, assessment_id,
        )

        summary = {
            "assets_discovered": len(assets),
            "services_discovered": sum(
                len(a.get("services", [])) for a in assets
            ),
            "findings": {
                "critical": sum(1 for f in findings if f.get("severity") == "critical"),
                "high": sum(1 for f in findings if f.get("severity") == "high"),
                "medium": sum(1 for f in findings if f.get("severity") == "medium"),
                "low": sum(1 for f in findings if f.get("severity") == "low"),
            },
        }

        return _make_assessment_result(
            self.name, assessment_id, "completed", summary, findings, next_actions,
            job_id=None, detail=detail, raw_included=include_raw,
        )

    # ── internal: inline execution for short assessments ─────────────

    async def _run_assessment_inline(
        self,
        workflow: str,
        targets: list[str],
        scope_id: str | None,
        profile: str,
        max_parallel: int,
        max_duration: int,
        resume: bool,
        detail: str,
        include_raw: bool,
        assessment_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """Run the assessment inline and return (findings, assets, next_actions)."""
        from kali_mcp.tools.persist import persist_run

        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        next_actions: list[str] = []

        # Map workflow to execution strategy
        if workflow == "web_assessment":
            findings, assets, next_actions = await self._web_assessment(
                targets, max_parallel, detail, include_raw, assessment_id,
            )
        elif workflow == "network_assessment":
            findings, assets, next_actions = await self._network_assessment(
                targets, max_parallel, detail, include_raw, assessment_id,
            )
        elif workflow == "external_recon":
            findings, assets, next_actions = await self._external_recon(
                targets, max_parallel, detail, include_raw, assessment_id,
            )
        elif workflow == "ad_assessment":
            findings, assets, next_actions = await self._ad_assessment(
                targets, max_parallel, detail, include_raw, assessment_id,
            )
        elif workflow == "api_assessment":
            findings, assets, next_actions = await self._api_assessment(
                targets, max_parallel, detail, include_raw, assessment_id,
            )
        elif workflow == "vulnerability_validation":
            findings, assets, next_actions = await self._vulnerability_validation(
                targets, max_parallel, detail, include_raw, assessment_id,
            )
        elif workflow == "custom_assessment":
            findings, assets, next_actions = await self._custom_assessment(
                arguments={}, max_parallel=max_parallel, detail=detail,
                include_raw=include_raw, assessment_id=assessment_id,
            )
        else:
            # Unknown workflow: fall back to generic_command on first target
            res = await engine.execute(
                command=["echo", f"Unknown workflow: {workflow}"],
                tool="assessment_run",
                timeout=30,
            )
            findings = [{
                "id": _new_id("finding"),
                "title": f"Unknown workflow: {workflow}",
                "severity": "informational",
                "confidence": 1.0,
                "validation_status": "observed",
                "asset_id": targets[0] if targets else "unknown",
                "source_tools": ["assessment_run"],
                "evidence_refs": [],
            }]
            next_actions = ["Specify a valid workflow: web_assessment, network_assessment, "
                           "external_recon, ad_assessment, api_assessment, "
                           "vulnerability_validation, custom_assessment"]

        return findings, assets, next_actions

    # ── workflow implementations ───────────────────────────────────────

    async def _web_assessment(
        self, targets: list[str], max_parallel: int, detail: str,
        include_raw: bool, assessment_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """Web assessment: subfinder → httpx → katana → nuclei (parallel where safe)."""
        from kali_mcp.registry import registry

        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        next_actions: list[str] = []

        for target in targets:
            # Step 1: subfinder (DNS/subdomain discovery)
            subfinder = registry.get("subfinder")
            if subfinder:
                res = await subfinder.safe_execute({"target": target, "timeout": 300})
                subfinder_data = self._parse_tool_result(res, target, "subfinder", assessment_id)
                findings.extend(subfinder_data["findings"])
                assets.extend(subfinder_data["assets"])

            # Step 2: httpx (HTTP service discovery) — depends on subfinder
            httpx = registry.get("httpx")
            if httpx:
                res = await httpx.safe_execute({"target": target, "timeout": 300})
                httpx_data = self._parse_tool_result(res, target, "httpx", assessment_id)
                findings.extend(httpx_data["findings"])
                assets.extend(httpx_data["assets"])

            # Step 3: katana (web crawling) — only if HTTP services found
            if httpx_data.get("http_services", 0) > 0:
                katana = registry.get("katana")
                if katana:
                    res = await katana.safe_execute(
                        {"target": target, "timeout": 300, "max_parallel": max_parallel}
                    )
                    katana_data = self._parse_tool_result(res, target, "katana", assessment_id)
                    findings.extend(katana_data["findings"])
                    assets.extend(katana_data["assets"])

            # Step 4: nuclei (vulnerability checks) — parallel with katana results
            nuclei = registry.get("nuclei")
            if nuclei:
                res = await nuclei.safe_execute({"target": target, "timeout": 600})
                nuclei_data = self._parse_tool_result(res, target, "nuclei", assessment_id)
                findings.extend(nuclei_data["findings"])
                assets.extend(nuclei_data["assets"])

        next_actions = [
            "Review high/critical severity findings",
            "Retrieve evidence via evidence_get for confirmed findings",
            "Consider vulnerability_validation to verify observations",
        ]
        return findings, assets, next_actions

    async def _network_assessment(
        self, targets: list[str], max_parallel: int, detail: str,
        include_raw: bool, assessment_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """Network assessment: nmap → masscan → service enumeration."""
        from kali_mcp.registry import registry

        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        next_actions: list[str] = []

        for target in targets:
            nmap = registry.get("nmap")
            if nmap:
                res = await nmap.safe_execute({"target": target, "timeout": 600})
                nmap_data = self._parse_tool_result(res, target, "nmap", assessment_id)
                findings.extend(nmap_data["findings"])
                assets.extend(nmap_data["assets"])

        next_actions = [
            "Review open ports and service versions",
            "Run web_assessment against discovered HTTP services",
            "Validate findings with vulnerability_validation",
        ]
        return findings, assets, next_actions

    async def _external_recon(
        self, targets: list[str], max_parallel: int, detail: str,
        include_raw: bool, assessment_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """External recon: subfinder → amass → httpx → whatweb."""
        from kali_mcp.registry import registry

        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        next_actions: list[str] = []

        for target in targets:
            subfinder = registry.get("subfinder")
            if subfinder:
                res = await subfinder.safe_execute({"target": target, "timeout": 300})
                d = self._parse_tool_result(res, target, "subfinder", assessment_id)
                findings.extend(d["findings"]); assets.extend(d["assets"])

            amass = registry.get("amass")
            if amass:
                res = await amass.safe_execute({"target": target, "timeout": 300})
                d = self._parse_tool_result(res, target, "amass", assessment_id)
                findings.extend(d["findings"]); assets.extend(d["assets"])

            httpx = registry.get("httpx")
            if httpx:
                res = await httpx.safe_execute({"target": target, "timeout": 300})
                d = self._parse_tool_result(res, target, "httpx", assessment_id)
                findings.extend(d["findings"]); assets.extend(d["assets"])

        next_actions = [
            "Review discovered external assets",
            "Run network_assessment against discovered IPs",
            "Run web_assessment against discovered HTTP services",
        ]
        return findings, assets, next_actions

    async def _ad_assessment(
        self, targets: list[str], max_parallel: int, detail: str,
        include_raw: bool, assessment_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """AD assessment: enum4linux → bloodhound → netexec+crackmapexec."""
        from kali_mcp.registry import registry

        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        next_actions: list[str] = []

        for target in targets:
            enum4linux = registry.get("enum4linux")
            if enum4linux:
                res = await enum4linux.safe_execute({"target": target, "timeout": 300})
                d = self._parse_tool_result(res, target, "enum4linux", assessment_id)
                findings.extend(d["findings"]); assets.extend(d["assets"])

        next_actions = [
            "Review AD enumeration findings",
            "Validate credentials before any exploitation",
            "Run vulnerability_validation on confirmed issues",
        ]
        return findings, assets, next_actions

    async def _api_assessment(
        self, targets: list[str], max_parallel: int, detail: str,
        include_raw: bool, assessment_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """API assessment: katana → arjun → nuclei."""
        from kali_mcp.registry import registry

        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        next_actions: list[str] = []

        for target in targets:
            katana = registry.get("katana")
            if katana:
                res = await katana.safe_execute({"target": target, "timeout": 300})
                d = self._parse_tool_result(res, target, "katana", assessment_id)
                findings.extend(d["findings"]); assets.extend(d["assets"])

        next_actions = [
            "Review discovered API endpoints",
            "Test parameters with arjun/ffuf",
            "Run nuclei against API endpoints",
        ]
        return findings, assets, next_actions

    async def _vulnerability_validation(
        self, targets: list[str], max_parallel: int, detail: str,
        include_raw: bool, assessment_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """Validate previously discovered findings."""
        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        next_actions: list[str] = [
            "Re-check observations with nuclei verification templates",
            "Update validation_status to validated or false_positive",
        ]
        return findings, assets, next_actions

    async def _custom_assessment(
        self, arguments: dict[str, Any], max_parallel: int, detail: str,
        include_raw: bool, assessment_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """User-defined custom assessment (placeholder for Phase 2 DAG engine)."""
        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        next_actions: list[str] = [
            "Define custom DAG playbook via YAML definition",
            "Execute via playbook_engine or assessment_run with workflow=custom_assessment",
        ]
        return findings, assets, next_actions

    # ── result parsing ─────────────────────────────────────────────────

    def _parse_tool_result(
        self, res: dict[str, Any], target: str, tool_name: str,
        assessment_id: str,
    ) -> dict[str, Any]:
        """Parse a tool result into normalized findings and assets."""
        findings: list[dict[str, Any]] = []
        assets: list[dict[str, Any]] = []
        http_services = 0

        try:
            text = res.get("content", [{}])[0].get("text", "{}") if isinstance(res, dict) else str(res)
            data = json.loads(text)
        except (json.JSONDecodeError, IndexError, AttributeError, TypeError):
            data = {}

        stdout = data.get("stdout", "") if isinstance(data, dict) else ""
        success = data.get("success", False) if isinstance(data, dict) else False

        # Record evidence artifact
        evidence_id = _new_id("evidence")
        db = dbm.get_db()
        if db is not None and stdout:
            try:
                safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in target)
                path = f"artifacts/evidence/{evidence_id}_{tool_name}_{safe_name}.txt"
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(stdout)
                db.add_evidence_artifact(
                    evidence_id=evidence_id, tool=tool_name, target=target,
                    artifact_type="stdout", content_path=path,
                    content_size=len(stdout.encode("utf-8")),
                    assessment_id=assessment_id,
                )
            except Exception:
                pass

        # Build a normalized finding from the execution
        if stdout.strip():
            severity = "high" if not success and "error" in stdout.lower() else "informational"
            findings.append({
                "id": _new_id("finding"),
                "title": f"{tool_name} execution against {target}",
                "severity": severity,
                "confidence": 0.7,
                "validation_status": "observed",
                "asset_id": target,
                "source_tools": [tool_name],
                "evidence_refs": [evidence_id],
            })

            # Extract asset
            assets.append({
                "asset_id": target,
                "name": target,
                "type": "host",
                "services": [],
                "severity_max": severity,
            })

        # Count HTTP services for conditional execution
        if tool_name == "httpx" and stdout.strip():
            http_services = stdout.count("http") + stdout.count("https")

        return {"findings": findings, "assets": assets, "http_services": http_services}

    # ── background execution for long assessments ──────────────────────

    async def _run_assessment_background(
        self, assessment_id: str, job_id: str, workflow: str, targets: list[str],
        scope_id: str | None, profile: str, max_parallel: int, max_duration: int,
        resume: bool, detail: str, include_raw: bool,
    ) -> None:
        """Background task for long-running assessments."""
        try:
            findings, assets, next_actions = await self._run_assessment_inline(
                workflow, targets, scope_id, profile, max_parallel, max_duration,
                resume, detail, include_raw, assessment_id,
            )
            summary = {
                "assets_discovered": len(assets),
                "services_discovered": sum(
                    len(a.get("services", [])) for a in assets
                ),
                "findings": {
                    "critical": sum(1 for f in findings if f.get("severity") == "critical"),
                    "high": sum(1 for f in findings if f.get("severity") == "high"),
                    "medium": sum(1 for f in findings if f.get("severity") == "medium"),
                    "low": sum(1 for f in findings if f.get("severity") == "low"),
                },
            }
            # Store completed result in vault for retrieval
            payload = {
                "assessment_id": assessment_id,
                "job_id": job_id,
                "status": "completed",
                "summary": summary,
                "findings": findings,
                "next_actions": next_actions,
            }
            vault_write(
                category="assessments",
                name=assessment_id,
                content=payload,
                target=",".join(targets),
                tool=self.name,
                tags=f"assessment:{assessment_id},job:{job_id}",
            )
        except Exception:  # noqa: BLE001
            payload = {"assessment_id": assessment_id, "job_id": job_id, "status": "failed"}
            vault_write(
                category="assessments", name=assessment_id, content=payload,
                target=",".join(targets), tool=self.name,
                tags=f"assessment:{assessment_id},job:{job_id}",
            )


# ── 2. batch_run ─────────────────────────────────────────────────────────

class BatchRunTool(BaseTool):
    """Run multiple independent operations concurrently and aggregate outputs."""

    @property
    def name(self) -> str:
        return "batch_run"

    @property
    def description(self) -> str:
        return (
            "Execute multiple independent security operations in parallel.\n\n"
            "Use when:\n"
            "  - You have several unrelated targets or tools to run at once.\n"
            "  - You want the server to deduplicate identical jobs automatically.\n"
            "  - You do not want to manually coordinate parallel execution.\n\n"
            "Inputs:\n"
            "  - assessment_id: optional parent assessment identifier.\n"
            "  - operations: array of {tool, target_ref, args}.\n"
            "  - max_parallel: max concurrent operations (default 3).\n"
            "  - continue_on_error: keep going if one operation fails (default true).\n\n"
            "Returns:\n"
            "  - batch_id, per-operation results, aggregated summary, deduplication report.\n\n"
            "Does not: create dependencies between operations (use assessment_run for that).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 3600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "assessment_id": {
                    "type": "string",
                    "description": "Optional parent assessment identifier",
                },
                "operations": {
                    "type": "array",
                    "description": "Operations to run: {tool, target_ref, args}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "target_ref": {"type": "string"},
                            "args": {"type": "object"},
                        },
                        "required": ["tool"],
                    },
                },
                "max_parallel": {
                    "type": "integer",
                    "description": "Max concurrent operations",
                    "default": 3,
                },
                "continue_on_error": {
                    "type": "boolean",
                    "description": "Continue if one operation fails",
                    "default": True,
                },
            },
            "required": ["operations"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        ops = arguments.get("operations")
        if not isinstance(ops, list) or not ops:
            raise ValueError("operations must be a non-empty array")
        for i, op in enumerate(ops):
            if not isinstance(op, dict) or not op.get("tool"):
                raise ValueError(f"operations[{i}] must have a 'tool' field")
        mp = arguments.get("max_parallel", 3)
        if not isinstance(mp, int) or mp < 1 or mp > 20:
            raise ValueError("max_parallel must be between 1 and 20")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["batch_run"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        ops = arguments["operations"]
        max_parallel = arguments.get("max_parallel", 3)
        continue_on_error = arguments.get("continue_on_error", True)
        assessment_id = arguments.get("assessment_id")
        batch_id = _new_id("batch")

        # Deduplicate identical operations
        seen: set[str] = set()
        unique_ops: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        for op in ops:
            key = f"{op.get('tool')}:{json.dumps(op.get('args', {}), sort_keys=True)}"
            if key in seen:
                duplicates.append(op)
            else:
                seen.add(key)
                unique_ops.append(op)

        semaphore = asyncio.Semaphore(max_parallel)

        async def run_one(op: dict[str, Any]) -> dict[str, Any]:
            tool_name = op["tool"]
            args = op.get("args", {})
            from kali_mcp.registry import registry
            tool = registry.get(tool_name)
            if tool is None:
                return {"tool": tool_name, "target_ref": op.get("target_ref"),
                        "error": "unknown tool", "batch_id": batch_id}
            async with semaphore:
                try:
                    res = await tool.safe_execute(args)
                    return {"tool": tool_name, "target_ref": op.get("target_ref"),
                            "result": res, "batch_id": batch_id, "success": True}
                except Exception as e:  # noqa: BLE001
                    return {"tool": tool_name, "target_ref": op.get("target_ref"),
                            "error": str(e), "batch_id": batch_id, "success": False}

        results = await asyncio.gather(*[run_one(op) for op in unique_ops])

        successful = sum(1 for r in results if r.get("success"))
        failed = len(results) - successful

        payload = {
            "batch_id": batch_id,
            "assessment_id": assessment_id,
            "total_operations": len(ops),
            "unique_operations": len(unique_ops),
            "duplicates_skipped": len(duplicates),
            "successful": successful,
            "failed": failed,
            "results": results,
        }

        result = ExecutionResult(
            tool=self.name, command=self.name, stdout=json.dumps(payload, indent=2),
            stderr="", exit_code=0, success=failed == 0 or continue_on_error,
            timed_out=False, duration=0.0, start_time=utc_now_iso(),
            end_time=utc_now_iso(),
        )
        return success_response(result)


# ── 3. job_control ───────────────────────────────────────────────────────

class JobControlTool(BaseTool):
    """Check, wait for, or cancel execution jobs by job_id."""

    @property
    def name(self) -> str:
        return "job_control"

    @property
    def description(self) -> str:
        return (
            "Manage the lifecycle of long-running assessment and batch jobs.\n\n"
            "Use when:\n"
            "  - assessment_run returned a job_id and you need status.\n"
            "  - You want to wait for a job to complete (with timeout).\n"
            "  - You need to cancel a stuck or unwanted job.\n\n"
            "Inputs:\n"
            "  - job_id: opaque job identifier returned by assessment_run or batch_run.\n"
            "  - action: status | wait | cancel.\n"
            "  - timeout: seconds to wait when action=wait (default 60).\n\n"
            "Returns:\n"
            "  - job status: accepted | running | completed | failed | not_found.\n"
            "  - For completed jobs: the full assessment result.\n\n"
            "Does not: create new jobs (use assessment_run or batch_run).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 120

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Job identifier (required)",
                },
                "action": {
                    "type": "string",
                    "description": "status | wait | cancel",
                    "default": "status",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Seconds to wait when action=wait",
                    "default": 60,
                },
            },
            "required": ["job_id"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("job_id"):
            raise ValueError("job_id is required")
        action = arguments.get("action", "status")
        if action not in ("status", "wait", "cancel"):
            raise ValueError("action must be status, wait, or cancel")
        timeout = arguments.get("timeout", 60)
        if not isinstance(timeout, int) or timeout < 1 or timeout > 3600:
            raise ValueError("timeout must be between 1 and 3600 seconds")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["job_control", arguments["job_id"]]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        job_id = arguments["job_id"]
        action = arguments.get("action", "status")
        timeout = arguments.get("timeout", 60)

        # Look up job result in vault
        try:
            rows = vault_query(
                category="assessments",
                search=job_id,
                limit=10,
            )
        except Exception:
            rows = {"entries": []}

        entries = rows.get("entries", [])
        job_entry = None
        for e in entries:
            name = e.get("name", "")
            if job_id in name or job_id == name:
                job_entry = e
                break

        if not job_entry:
            # Also check active engine executions
            active = engine.get_active_jobs()
            for aj in active:
                if aj.get("request_id") == job_id:
                    payload = {
                        "job_id": job_id,
                        "status": "running",
                        "tool": aj.get("tool"),
                        "elapsed_seconds": aj.get("elapsed_seconds"),
                    }
                    result = ExecutionResult(
                        tool=self.name, command=self.name,
                        stdout=json.dumps(payload, indent=2), stderr="",
                        exit_code=0, success=True, timed_out=False,
                        duration=0.0, start_time=utc_now_iso(),
                        end_time=utc_now_iso(),
                    )
                    return success_response(result)
            payload = {"job_id": job_id, "status": "not_found"}
            result = ExecutionResult(
                tool=self.name, command=self.name,
                stdout=json.dumps(payload, indent=2), stderr="",
                exit_code=0, success=True, timed_out=False,
                duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
            )
            return success_response(result)

        if action == "status":
            try:
                content = vault_read("assessments", job_entry.get("name", job_id))
                data = json.loads(content) if content else {}
            except Exception:
                data = {}
            payload = {
                "job_id": job_id,
                "status": data.get("status", "unknown"),
                "assessment_id": data.get("assessment_id"),
            }
            if data.get("status") == "completed":
                payload["result"] = data
            result = ExecutionResult(
                tool=self.name, command=self.name,
                stdout=json.dumps(payload, indent=2), stderr="",
                exit_code=0, success=True, timed_out=False,
                duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
            )
            return success_response(result)

        if action == "wait":
            # Poll vault for completion
            import asyncio as _asyncio
            deadline = _asyncio.get_event_loop().time() + timeout
            while _asyncio.get_event_loop().time() < deadline:
                try:
                    content = vault_read("assessments", job_entry.get("name", job_id))
                    data = json.loads(content) if content else {}
                    if data.get("status") in ("completed", "failed"):
                        payload = {"job_id": job_id, "status": data.get("status")}
                        if data.get("status") == "completed":
                            payload["result"] = data
                        result = ExecutionResult(
                            tool=self.name, command=self.name,
                            stdout=json.dumps(payload, indent=2), stderr="",
                            exit_code=0, success=True, timed_out=False,
                            duration=0.0, start_time=utc_now_iso(),
                            end_time=utc_now_iso(),
                        )
                        return success_response(result)
                except Exception:
                    pass
                await _asyncio.sleep(2)
            payload = {"job_id": job_id, "status": "timeout",
                       "message": f"Job did not complete within {timeout}s"}
            result = ExecutionResult(
                tool=self.name, command=self.name,
                stdout=json.dumps(payload, indent=2), stderr="",
                exit_code=0, success=False, timed_out=True,
                duration=float(timeout), start_time=utc_now_iso(),
                end_time=utc_now_iso(),
            )
            return success_response(result)

        if action == "cancel":
            # Cancel via engine if active
            killed = engine.kill_job(job_id)
            payload = {"job_id": job_id, "status": "cancelled" if killed else "not_found_or_already_done"}
            result = ExecutionResult(
                tool=self.name, command=self.name,
                stdout=json.dumps(payload, indent=2), stderr="",
                exit_code=0, success=True, timed_out=False,
                duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
            )
            return success_response(result)

        return error_response(ToolError(error="unknown action", details=action))


# ── 4. findings_query ────────────────────────────────────────────────────

class FindingsQueryTool(BaseTool):
    """Search and filter normalized findings from the asset/finding model."""

    @property
    def name(self) -> str:
        return "findings_query"

    @property
    def description(self) -> str:
        return (
            "Query normalized security findings from the assessment database.\n\n"
            "Use when:\n"
            "  - You want findings filtered by severity, asset, tool, or status.\n"
            "  - You need paginated results without scanning raw terminal output.\n"
            "  - You want to correlate findings across multiple tools.\n\n"
            "Inputs:\n"
            "  - target: filter by target string.\n"
            "  - severity: critical | high | medium | low | informational.\n"
            "  - validation_status: observed | suspected | validated | remediated | false_positive | accepted_risk.\n"
            "  - tool: filter by source tool name.\n"
            "  - asset_id: filter by asset identifier.\n"
            "  - search: free-text search over finding titles and descriptions.\n"
            "  - limit / offset: pagination.\n\n"
            "Returns:\n"
            "  - count, findings[] with id, title, severity, confidence, validation_status,\n"
            "    asset_id, source_tools[], evidence_refs[].\n\n"
            "Does not: return raw scanner output (use evidence_get for that).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 60

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string",
                           "description": "Filter by target string"},
                "severity": {"type": "string",
                             "description": "critical | high | medium | low | informational"},
                "validation_status": {"type": "string",
                                      "description": "observed | suspected | validated | remediated | false_positive | accepted_risk"},
                "tool": {"type": "string",
                         "description": "Filter by source tool name"},
                "asset_id": {"type": "string",
                             "description": "Filter by asset identifier"},
                "search": {"type": "string",
                           "description": "Free-text search over findings"},
                "limit": {"type": "integer", "description": "Max results (default 100, max 1000)",
                          "default": 100},
                "offset": {"type": "integer", "description": "Pagination offset (default 0)",
                           "default": 0},
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        limit = arguments.get("limit", 100)
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        offset = arguments.get("offset", 0)
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["findings_query"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        db = dbm.get_db()
        if db is None:
            return error_response(ToolError(
                error="database unavailable",
                details="SQLite database is not enabled or could not be opened",
            ))

        result = db.query_findings(
            target=arguments.get("target"),
            severity=arguments.get("severity"),
            validation_status=arguments.get("validation_status"),
            tool=arguments.get("tool"),
            asset_id=arguments.get("asset_id"),
            limit=arguments.get("limit", 100),
            offset=arguments.get("offset", 0),
        )

        # Enrich findings with evidence refs already in the model
        findings = result.get("findings", [])
        for f in findings:
            if "evidence_refs" not in f or f["evidence_refs"] is None:
                f["evidence_refs"] = []
            if "source_tools" not in f or f["source_tools"] is None:
                f["source_tools"] = []

        payload = {
            "count": result.get("count", 0),
            "limit": arguments.get("limit", 100),
            "offset": arguments.get("offset", 0),
            "findings": findings,
        }
        result_obj = ExecutionResult(
            tool=self.name, command=self.name,
            stdout=json.dumps(payload, indent=2), stderr="",
            exit_code=0, success=True, timed_out=False,
            duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
        )
        return success_response(result_obj)


# ── 5. evidence_get ──────────────────────────────────────────────────────

class EvidenceGetTool(BaseTool):
    """Retrieve detailed evidence for selected findings by evidence_ref."""

    @property
    def name(self) -> str:
        return "evidence_get"

    @property
    def description(self) -> str:
        return (
            "Retrieve stored evidence artifacts for a finding.\n\n"
            "Use when:\n"
            "  - You need the raw stdout/stderr behind a finding.\n"
            "  - output.detail=summary or normal was used and you need more detail.\n"
            "  - You are investigating a specific finding identified via findings_query.\n\n"
            "Inputs:\n"
            "  - evidence_id: opaque evidence identifier from a finding's evidence_refs.\n"
            "  - category: optional vault category filter.\n"
            "  - name: optional vault name filter.\n\n"
            "Returns:\n"
            "  - evidence_id, content_type, size_bytes, captured_at, source_tool,\n"
            "    content (truncated if very large).\n\n"
            "Does not: execute new scans (only retrieves previously stored evidence).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 60

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "evidence_id": {"type": "string",
                                "description": "Evidence identifier (required)"},
                "category": {"type": "string",
                             "description": "Optional vault category filter"},
                "name": {"type": "string",
                         "description": "Optional vault name filter"},
            },
            "required": ["evidence_id"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("evidence_id"):
            raise ValueError("evidence_id is required")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["evidence_get", arguments["evidence_id"]]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        evidence_id = arguments["evidence_id"]
        category = arguments.get("category")
        name = arguments.get("name")

        # First try the DB evidence_artifacts table
        db = dbm.get_db()
        if db is not None:
            row = db.get_evidence(evidence_id)
            if row:
                content_path = row.get("content_path", "")
                content = ""
                if content_path and os.path.isfile(content_path):
                    try:
                        with open(content_path, "r", encoding="utf-8", errors="replace") as fh:
                            content = fh.read()
                    except OSError:
                        content = ""
                payload = {
                    "evidence_id": evidence_id,
                    "content_type": row.get("artifact_type", "text"),
                    "size_bytes": row.get("content_size", 0),
                    "captured_at": row.get("captured_at"),
                    "source_tool": row.get("tool"),
                    "target": row.get("target"),
                    "assessment_id": row.get("assessment_id"),
                    "job_id": row.get("job_id"),
                    "content": content[:100_000],  # cap at 100KB
                    "truncated": len(content) > 100_000 if content else False,
                }
                result = ExecutionResult(
                    tool=self.name, command=self.name,
                    stdout=json.dumps(payload, indent=2), stderr="",
                    exit_code=0, success=True, timed_out=False,
                    duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
                )
                return success_response(result)

        # Fallback: vault read
        if category and name:
            try:
                content = vault_read(category, name)
                payload = {
                    "evidence_id": evidence_id,
                    "content_type": "text",
                    "size_bytes": len(content.encode("utf-8")),
                    "source_tool": "vault",
                    "category": category,
                    "name": name,
                    "content": content[:100_000],
                    "truncated": len(content) > 100_000,
                }
                result = ExecutionResult(
                    tool=self.name, command=self.name,
                    stdout=json.dumps(payload, indent=2), stderr="",
                    exit_code=0, success=True, timed_out=False,
                    duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
                )
                return success_response(result)
            except Exception:
                pass

        return error_response(ToolError(
            error="evidence not found",
            details=f"No evidence found for id={evidence_id}",
        ))


# ── 6. asset_graph ───────────────────────────────────────────────────────

class AssetGraphTool(BaseTool):
    """Retrieve discovered assets and their relationships."""

    @property
    def name(self) -> str:
        return "asset_graph"

    @property
    def description(self) -> str:
        return (
            "Query the asset graph: hosts, domains, IPs, services, and their relationships.\n\n"
            "Use when:\n"
            "  - You want to know what services belong to a target.\n"
            "  - You want to find assets sharing the same IP.\n"
            "  - You want to see which assets have not been assessed.\n"
            "  - You want to trace findings back to their assets.\n\n"
            "Inputs:\n"
            "  - target: filter by target/domain/IP.\n"
            "  - asset_id: filter by specific asset identifier.\n"
            "  - relationship_type: resolves_to | contains | uses_technology | shared_by | child_of | supports.\n"
            "  - limit: max results.\n\n"
            "Returns:\n"
            "  - assets[] and relationships[] with confidence scores and timestamps.\n\n"
            "Does not: run new discovery (use assessment_run or external_recon for that).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 60

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string",
                           "description": "Filter by target/domain/IP"},
                "asset_id": {"type": "string",
                             "description": "Filter by specific asset identifier"},
                "relationship_type": {"type": "string",
                                      "description": "resolves_to | contains | uses_technology | shared_by | child_of | supports"},
                "limit": {"type": "integer", "description": "Max results (default 100)",
                          "default": 100},
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        limit = arguments.get("limit", 100)
        if not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["asset_graph"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        db = dbm.get_db()
        if db is None:
            return error_response(ToolError(
                error="database unavailable",
                details="SQLite database is not enabled or could not be opened",
            ))

        graph = db.get_asset_graph(target=arguments.get("target"))

        assets = graph.get("assets", [])
        relationships = graph.get("relationships", [])

        # Filter by asset_id if specified
        asset_id = arguments.get("asset_id")
        if asset_id:
            assets = [a for a in assets if a.get("asset_id") == asset_id]

        # Filter by relationship_type if specified
        rel_type = arguments.get("relationship_type")
        if rel_type:
            relationships = [r for r in relationships if r.get("relationship") == rel_type]

        limit = arguments.get("limit", 100)
        assets = assets[:limit]
        relationships = relationships[:limit]

        payload = {
            "target": arguments.get("target"),
            "asset_count": len(assets),
            "relationship_count": len(relationships),
            "assets": assets,
            "relationships": relationships,
        }
        result = ExecutionResult(
            tool=self.name, command=self.name,
            stdout=json.dumps(payload, indent=2), stderr="",
            exit_code=0, success=True, timed_out=False,
            duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
        )
        return success_response(result)


# ── 7. tool_catalog ──────────────────────────────────────────────────────

class ToolCatalogTool(BaseTool):
    """Search available tools and their capabilities."""

    @property
    def name(self) -> str:
        return "tool_catalog"

    @property
    def description(self) -> str:
        return (
            "Browse the available MCP tools and their capabilities.\n\n"
            "Use when:\n"
            "  - You need to discover what tools exist before calling them.\n"
            "  - You want to filter by layer (discovery, operations, workflows, intelligence).\n"
            "  - You want Agent mode (compact) vs Expert mode (full) tool sets.\n\n"
            "Inputs:\n"
            "  - layer: discovery | operations | workflows | intelligence | escape_hatch.\n"
            "  - mode: agent | expert (default agent).\n"
            "  - search: free-text search over tool names and descriptions.\n\n"
            "Returns:\n"
            "  - tools[] with name, description, layer, input_schema, default_timeout.\n\n"
            "Does not: execute any tool (only catalogs what is available).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 30

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "layer": {"type": "string",
                          "description": "discovery | operations | workflows | intelligence | escape_hatch"},
                "mode": {"type": "string",
                         "description": "agent (compact) | expert (full)",
                         "default": "agent"},
                "search": {"type": "string",
                           "description": "Free-text search over tool names and descriptions"},
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        mode = arguments.get("mode", "agent")
        if mode not in ("agent", "expert"):
            raise ValueError("mode must be agent or expert")
        layer = arguments.get("layer")
        if layer and layer not in ("discovery", "operations", "workflows", "intelligence", "escape_hatch"):
            raise ValueError("invalid layer")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["tool_catalog"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        layer = arguments.get("layer")
        mode = arguments.get("mode", "agent")
        search = arguments.get("search", "").lower()

        allowed = AGENT_MODE_TOOLS if mode == "agent" else EXPERT_MODE_TOOLS

        from kali_mcp.registry import registry
        tools = registry.list_all()

        catalog: list[dict[str, Any]] = []
        for tool in tools:
            tname = tool.name
            if tname not in allowed:
                continue
            tlayer = TOOL_LAYERS.get(tname, "operations")
            if layer and tlayer != layer:
                continue
            if search and search not in tname.lower() and search not in tool.description.lower():
                continue
            catalog.append({
                "name": tname,
                "description": tool.description,
                "layer": tlayer,
                "input_schema": tool.input_schema(),
                "default_timeout": tool.default_timeout,
                "mode": "agent" if tname in AGENT_MODE_TOOLS else "expert",
            })

        catalog.sort(key=lambda t: (t["layer"], t["name"]))

        payload = {
            "mode": mode,
            "layer": layer,
            "search": search,
            "total": len(catalog),
            "tools": catalog,
        }
        result = ExecutionResult(
            tool=self.name, command=self.name,
            stdout=json.dumps(payload, indent=2), stderr="",
            exit_code=0, success=True, timed_out=False,
            duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
        )
        return success_response(result)


# ── 8. report_generate ───────────────────────────────────────────────────

class ReportGenerateTool(BaseTool):
    """Produce an assessment report from findings and asset data."""

    @property
    def name(self) -> str:
        return "report_generate"

    @property
    def description(self) -> str:
        return (
            "Generate an assessment report from normalized findings.\n\n"
            "Use when:\n"
            "  - You need a shareable report after completing an assessment.\n"
            "  - You want findings organized by severity with evidence references.\n"
            "  - You need machine-readable output (JSON/SARIF/STIX) or human-readable (Markdown/HTML/CSV).\n\n"
            "Inputs:\n"
            "  - assessment_id: the assessment to report on (required).\n"
            "  - format: json | markdown | html | sarif | pdf | csv | stix (default json).\n"
            "    pdf is a placeholder pending a PDF renderer.\n"
            "  - include_raw: include raw evidence content (default false).\n\n"
            "Returns:\n"
            "  - report content in the requested format. Every format includes assessment_id, summary,\n"
            "    findings (each with source_tools, evidence_refs, validation_status), next_actions,\n"
            "    artifacts, and recommended_next_playbooks.\n\n"
            "Does not: run new scans (only reports on existing assessment data).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 60

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "assessment_id": {"type": "string",
                                  "description": "Assessment identifier (required)"},
                "format": {"type": "string",
                           "description": "json | markdown | html | sarif | pdf | csv | stix",
                           "default": "json"},
                "include_raw": {"type": "boolean",
                                "description": "Include raw evidence content",
                                "default": False},
            },
            "required": ["assessment_id"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("assessment_id"):
            raise ValueError("assessment_id is required")
        fmt = arguments.get("format", "json")
        if fmt not in ("json", "markdown", "html", "sarif", "pdf", "csv", "stix"):
            raise ValueError("format must be json, markdown, html, sarif, pdf, csv, or stix")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["report_generate", arguments["assessment_id"]]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        assessment_id = arguments["assessment_id"]
        fmt = arguments.get("format", "json")
        include_raw = arguments.get("include_raw", False)

        # Retrieve assessment data from vault
        try:
            rows = vault_query(
                category="assessments",
                search=assessment_id,
                limit=5,
            )
        except Exception:
            rows = {"entries": []}

        entries = rows.get("entries", [])
        if not entries:
            return error_response(ToolError(
                error="assessment not found",
                details=f"No assessment data found for id={assessment_id}",
            ))

        # Use the most recent entry
        entry = entries[0]
        try:
            content = vault_read("assessments", entry.get("name", assessment_id))
            data = json.loads(content) if content else {}
        except Exception:
            data = {}

        findings = data.get("findings", [])
        summary = data.get("summary", {})

        base = self._base_report(assessment_id, findings, summary, data, include_raw)

        if fmt == "json":
            report = dict(base)
            report["format"] = "json"
            content_out = json.dumps(report, indent=2)
        elif fmt == "sarif":
            report = self._sarif_report(assessment_id, findings, summary, base)
            content_out = json.dumps(report, indent=2)
        elif fmt == "markdown":
            content_out = self._markdown_report(assessment_id, findings, summary, base)
        elif fmt == "html":
            content_out = self._html_report(assessment_id, findings, summary, base)
        elif fmt == "pdf":
            content_out = self._pdf_report(assessment_id, findings, summary, base)
        elif fmt == "csv":
            content_out = self._csv_report(assessment_id, findings, base)
        elif fmt == "stix":
            content_out = json.dumps(self._stix_report(assessment_id, findings, summary, base), indent=2)
        else:
            content_out = json.dumps({"error": "unsupported format"}, indent=2)

        result = ExecutionResult(
            tool=self.name, command=self.name,
            stdout=content_out, stderr="",
            exit_code=0, success=True, timed_out=False,
            duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
        )
        return success_response(result)

    # ── report format helpers ──────────────────────────────────────────

    def _base_report(
        self,
        assessment_id: str,
        findings: list[dict[str, Any]],
        summary: dict[str, Any],
        data: dict[str, Any],
        include_raw: bool,
    ) -> dict[str, Any]:
        """Build the common report structure shared by every output format."""
        normalized_findings: list[dict[str, Any]] = []
        for f in findings:
            normalized_findings.append({
                "id": f.get("id") or f.get("finding_id") or "unknown",
                "title": f.get("title", "Untitled finding"),
                "severity": f.get("severity", "informational"),
                "confidence": f.get("confidence", 0.5),
                "validation_status": f.get("validation_status", "observed"),
                "asset_id": f.get("asset_id"),
                "source_tools": list(f.get("source_tools") or f.get("source_modules") or []),
                "evidence_refs": list(f.get("evidence_refs") or []),
                "description": f.get("description", ""),
            })
        return {
            "assessment_id": assessment_id,
            "generated_at": utc_now_iso(),
            "summary": summary,
            "findings": normalized_findings,
            "next_actions": list(data.get("next_actions") or []),
            "artifacts": list(data.get("artifacts") or []),
            "recommended_next_playbooks": list(data.get("recommended_next_playbooks") or []),
            "include_raw": include_raw,
        }

    def _sarif_report(
        self,
        assessment_id: str,
        findings: list[dict[str, Any]],
        summary: dict[str, Any],
        base: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a SARIF-formatted report."""
        results = []
        for f in findings:
            level = "error" if f.get("severity") in ("critical", "high") else "warning"
            results.append({
                "ruleId": f.get("id", "unknown"),
                "level": level,
                "message": {"text": f.get("title", "Untitled finding")},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": f.get("asset_id", "unknown")},
                }}],
                "properties": {
                    "severity": f.get("severity"),
                    "confidence": f.get("confidence"),
                    "validation_status": f.get("validation_status"),
                    "source_tools": f.get("source_tools", []),
                    "evidence_refs": f.get("evidence_refs", []),
                },
            })
        return {
            "$schema": "https://docs.oasis-open.org/sarif/sarif-2.1.0/csprd01/schemas/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "format": "sarif",
            "assessment_id": assessment_id,
            "generated_at": base.get("generated_at"),
            "summary": summary,
            "next_actions": base.get("next_actions", []),
            "artifacts": base.get("artifacts", []),
            "recommended_next_playbooks": base.get("recommended_next_playbooks", []),
            "runs": [{
                "tool": {"driver": {"name": "kali-mcp", "version": "2.0.0"}},
                "results": results,
                "properties": {"assessment_id": assessment_id, "summary": summary},
            }],
        }

    def _pdf_report(
        self,
        assessment_id: str,
        findings: list[dict[str, Any]],
        summary: dict[str, Any],
        base: dict[str, Any],
    ) -> str:
        """PDF report placeholder.

        A real PDF renderer (e.g. reportlab) is not a dependency of kali-mcp,
        so this returns a self-describing placeholder document that embeds the
        full report metadata. Replace with binary PDF generation when a renderer
        is available.
        """
        lines = [
            "============================================================",
            "              KALI-MCP ASSESSMENT REPORT (PDF PLACEHOLDER)",
            "============================================================",
            "",
            f"Assessment ID: {assessment_id}",
            f"Generated: {base.get('generated_at')}",
            f"Format: pdf (placeholder - install reportlab for real PDF rendering)",
            "",
            "--- Summary ---",
            f"Assets discovered: {summary.get('assets_discovered', 0)}",
            f"Services discovered: {summary.get('services_discovered', 0)}",
            f"Critical: {summary.get('findings', {}).get('critical', 0)}",
            f"High: {summary.get('findings', {}).get('high', 0)}",
            f"Medium: {summary.get('findings', {}).get('medium', 0)}",
            f"Low: {summary.get('findings', {}).get('low', 0)}",
            "",
            "--- Findings ---",
        ]
        for f in findings:
            lines.append(
                f"[{f.get('id')}] {f.get('title')} | severity={f.get('severity')} | "
                f"validation={f.get('validation_status')} | asset={f.get('asset_id')} | "
                f"tools={','.join(f.get('source_tools', []))} | evidence={','.join(f.get('evidence_refs', []))}"
            )
        lines.extend([
            "",
            "--- Next Actions ---",
        ])
        for action in base.get("next_actions", []):
            lines.append(f"- {action}")
        lines.extend([
            "",
            "--- Artifacts ---",
        ])
        for artifact in base.get("artifacts", []):
            lines.append(f"- {artifact}")
        lines.extend([
            "",
            "--- Recommended Next Playbooks ---",
        ])
        for pb in base.get("recommended_next_playbooks", []):
            lines.append(f"- {pb}")
        lines.append("")
        lines.append("Embedded report (JSON):")
        lines.append(json.dumps(base, indent=2))
        return "\n".join(lines)

    def _csv_report(
        self,
        assessment_id: str,
        findings: list[dict[str, Any]],
        base: dict[str, Any],
    ) -> str:
        """Export findings as CSV."""
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "assessment_id", "finding_id", "title", "severity", "confidence",
            "validation_status", "asset_id", "source_tools", "evidence_refs", "description",
        ])
        for f in findings:
            writer.writerow([
                assessment_id,
                f.get("id", ""),
                f.get("title", ""),
                f.get("severity", ""),
                f.get("confidence", ""),
                f.get("validation_status", ""),
                f.get("asset_id", ""),
                ";".join(f.get("source_tools", [])),
                ";".join(f.get("evidence_refs", [])),
                f.get("description", ""),
            ])
        return buf.getvalue()

    def _stix_report(
        self,
        assessment_id: str,
        findings: list[dict[str, Any]],
        summary: dict[str, Any],
        base: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a STIX 2.1 bundle with TAXII collection metadata."""
        import uuid

        bundle_id = f"bundle--{uuid.uuid4()}"
        identity_id = f"identity--{uuid.uuid4()}"
        marking_id = "marking-definition--34298f74-4e5d-4d5d-8d5d-3f8e9c2a1b0c"
        report_id = f"report--{uuid.uuid4()}"

        objects: list[dict[str, Any]] = [
            {
                "type": "identity",
                "id": identity_id,
                "spec_version": "2.1",
                "name": "kali-mcp",
                "identity_class": "system",
                "roles": ["assessment-engine"],
            },
            {
                "type": "marking-definition",
                "id": marking_id,
                "spec_version": "2.1",
                "definition_type": "statement",
                "definition": {"statement": "Copyright kali-mcp"},
            },
            {
                "type": "report",
                "id": report_id,
                "spec_version": "2.1",
                "name": f"Assessment Report — {assessment_id}",
                "published": base.get("generated_at"),
                "report_types": ["security-assessment"],
                "object_refs": [],
            },
        ]

        for f in findings:
            indicator_id = f"indicator--{uuid.uuid4()}"
            objects.append({
                "type": "indicator",
                "id": indicator_id,
                "spec_version": "2.1",
                "created": base.get("generated_at"),
                "modified": base.get("generated_at"),
                "labels": ["anomalous-activity"],
                "pattern_type": "stix",
                "pattern": f"[kali-mcp:finding.id = '{f.get('id')}']",
                "valid_from": base.get("generated_at"),
                "confidence": int(round(float(f.get("confidence", 0.5) * 100))),
                "marking_refs": [marking_id],
                "external_references": [{
                    "source_name": "kali-mcp",
                    "external_id": f.get("id"),
                    "description": f.get("title"),
                }],
            })
            objects[2]["object_refs"].append(indicator_id)  # append to report object_refs

        return {
            "type": "bundle",
            "id": bundle_id,
            "spec_version": "2.1",
            "assessment_id": assessment_id,
            "generated_at": base.get("generated_at"),
            "summary": summary,
            "next_actions": base.get("next_actions", []),
            "artifacts": base.get("artifacts", []),
            "recommended_next_playbooks": base.get("recommended_next_playbooks", []),
            "taxii": {
                "collection": "kali-mcp-assessments",
                "manifest_id": f"manifest--{uuid.uuid4()}",
                "api_version": "taxii2.1",
            },
            "objects": objects,
        }

    def _markdown_report(
        self, assessment_id: str, findings: list[dict[str, Any]],
        summary: dict[str, Any], base: dict[str, Any],
    ) -> str:
        lines = [
            f"# Assessment Report — {assessment_id}",
            f"Generated: {base.get('generated_at')}",
            "",
            "## Summary",
            f"- Assets discovered: {summary.get('assets_discovered', 0)}",
            f"- Services discovered: {summary.get('services_discovered', 0)}",
            f"- Critical: {summary.get('findings', {}).get('critical', 0)}",
            f"- High: {summary.get('findings', {}).get('high', 0)}",
            f"- Medium: {summary.get('findings', {}).get('medium', 0)}",
            f"- Low: {summary.get('findings', {}).get('low', 0)}",
            "",
            "## Findings",
        ]
        for f in findings:
            lines.extend([
                f"### {f.get('id')} — {f.get('title')}",
                f"- Severity: {f.get('severity')}",
                f"- Confidence: {f.get('confidence')}",
                f"- Validation: {f.get('validation_status')}",
                f"- Asset: {f.get('asset_id')}",
                f"- Source tools: {', '.join(f.get('source_tools', []))}",
                f"- Evidence refs: {', '.join(f.get('evidence_refs', []))}",
                f"- Description: {f.get('description', '')}",
                "",
            ])
        lines.extend([
            "## Next Actions",
        ])
        for action in base.get("next_actions", []):
            lines.append(f"- {action}")
        lines.extend([
            "",
            "## Artifacts",
        ])
        for artifact in base.get("artifacts", []):
            lines.append(f"- {artifact}")
        lines.extend([
            "",
            "## Recommended Next Playbooks",
        ])
        for pb in base.get("recommended_next_playbooks", []):
            lines.append(f"- {pb}")
        return "\n".join(lines)

    def _html_report(
        self, assessment_id: str, findings: list[dict[str, Any]],
        summary: dict[str, Any], base: dict[str, Any],
    ) -> str:
        rows = ""
        for f in findings:
            rows += (
                f"<tr><td>{f.get('id')}</td><td>{f.get('title')}</td>"
                f"<td>{f.get('severity')}</td><td>{f.get('validation_status')}</td>"
                f"<td>{f.get('asset_id')}</td><td>{', '.join(f.get('source_tools', []))}</td>"
                f"<td>{', '.join(f.get('evidence_refs', []))}</td></tr>"
            )
        actions = "".join(f"<li>{a}</li>" for a in base.get("next_actions", []))
        artifacts = "".join(f"<li>{a}</li>" for a in base.get("artifacts", []))
        playbooks = "".join(f"<li>{p}</li>" for p in base.get("recommended_next_playbooks", []))
        return (
            f"<!DOCTYPE html><html><head><title>Assessment Report — {assessment_id}</title>"
            f"<style>body{{font-family:sans-serif;padding:2em;}} table{{border-collapse:collapse;width:100%;}}"
            f"th,td{{border:1px solid #ccc;padding:0.5em;text-align:left;}} .critical{{color:#c00;}}"
            f".high{{color:#e65c00;}} .medium{{color:#ca9a00;}} .low{{color:#4a8c00;}}</style></head>"
            f"<body><h1>Assessment Report — {assessment_id}</h1>"
            f"<p>Generated: {base.get('generated_at')}</p>"
            f"<h2>Summary</h2><ul>"
            f"<li>Assets: {summary.get('assets_discovered', 0)}</li>"
            f"<li>Services: {summary.get('services_discovered', 0)}</li>"
            f"<li>Critical: <span class='critical'>{summary.get('findings', {}).get('critical', 0)}</span></li>"
            f"<li>High: <span class='high'>{summary.get('findings', {}).get('high', 0)}</span></li>"
            f"<li>Medium: <span class='medium'>{summary.get('findings', {}).get('medium', 0)}</span></li>"
            f"<li>Low: <span class='low'>{summary.get('findings', {}).get('low', 0)}</span></li>"
            f"</ul><h2>Findings</h2><table><tr><th>ID</th><th>Title</th><th>Severity</th><th>Status</th><th>Asset</th><th>Source Tools</th><th>Evidence Refs</th></tr>{rows}</table>"
            f"<h2>Next Actions</h2><ul>{actions}</ul>"
            f"<h2>Artifacts</h2><ul>{artifacts}</ul>"
            f"<h2>Recommended Next Playbooks</h2><ul>{playbooks}</ul>"
            f"</body></html>"
        )


# ── 9. finding_transition ──────────────────────────────────────────────────

class FindingTransitionTool:
    """Change the validation_status (lifecycle state) of a finding."""

    @property
    def name(self) -> str:
        return "finding_transition"

    @property
    def description(self) -> str:
        return (
            "Transition a finding through its verification lifecycle.\n\n"
            "Use when:\n"
            "  - A finding has been manually verified and should move to validated.\n"
            "  - A finding is determined to be a false positive.\n"
            "  - Risk has been accepted for a known issue.\n"
            "  - A finding has been remediated.\n\n"
            "Inputs:\n"
            "  - finding_id: the finding identifier (required).\n"
            "  - new_state: observed | suspected | validated | remediated | false_positive | accepted_risk.\n"
            "  - source: who initiated the transition (tool name or analyst).\n"
            "  - reason: human-readable reason for the transition.\n\n"
            "Returns:\n"
            "  - success flag, finding_id, previous_state, new_state, transition record.\n\n"
            "Does not: execute scans or modify the database directly (uses VerificationStates).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 30

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string", "description": "Finding identifier (required)"},
                "new_state": {
                    "type": "string",
                    "description": "observed | suspected | validated | remediated | false_positive | accepted_risk",
                },
                "source": {"type": "string", "description": "Tool or analyst initiating the transition"},
                "reason": {"type": "string", "description": "Reason for the state change"},
            },
            "required": ["finding_id", "new_state"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("finding_id"):
            raise ValueError("finding_id is required")
        state = arguments.get("new_state")
        valid = {"observed", "suspected", "validated", "remediated", "false_positive", "accepted_risk"}
        if state not in valid:
            raise ValueError(f"new_state must be one of: {sorted(valid)}")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["finding_transition", arguments["finding_id"]]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        finding_id = arguments["finding_id"]
        new_state = arguments["new_state"]
        source = arguments.get("source", "agent_interface")
        reason = arguments.get("reason", "")

        # Get current state from DB if available, then transition in-memory
        db = dbm.get_db()
        previous_state = "observed"
        if db is not None:
            try:
                rows = db.conn.execute(
                    "SELECT validation_status FROM findings WHERE id = ?",
                    (finding_id,),
                ).fetchall()
                if rows:
                    previous_state = rows[0][0]
                    # Persist the new state back to the findings table
                    db.conn.execute(
                        "UPDATE findings SET validation_status = ?, updated_at = ? WHERE id = ?",
                        (new_state, utc_now_iso(), finding_id),
                    )
                    db.conn.commit()
            except Exception:  # noqa: BLE001
                pass

        # Use VerificationStates for lifecycle validation
        states = VerificationStates()
        # Set current state from DB so can_transition works correctly
        states._states[finding_id] = previous_state

        if not states.can_transition(previous_state, new_state):
            payload = {
                "success": False,
                "finding_id": finding_id,
                "previous_state": previous_state,
                "requested_state": new_state,
                "error": f"Invalid transition from {previous_state} to {new_state}",
            }
            result = ExecutionResult(
                tool=self.name, command=self.name,
                stdout=json.dumps(payload, indent=2), stderr="",
                exit_code=0, success=False, timed_out=False,
                duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
            )
            return success_response(result)

        ok = states.transition(finding_id, new_state, source, reason)
        history = states.get_transition_history(finding_id)

        payload = {
            "success": ok,
            "finding_id": finding_id,
            "previous_state": previous_state,
            "new_state": new_state,
            "source": source,
            "reason": reason,
            "transition_history": history,
        }
        result = ExecutionResult(
            tool=self.name, command=self.name,
            stdout=json.dumps(payload, indent=2), stderr="",
            exit_code=0, success=ok, timed_out=False,
            duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
        )
        return success_response(result)


# ── 10. assessment_diff ────────────────────────────────────────────────────

class AssessmentDiffTool:
    """Compare two assessment runs and surface what changed."""

    @property
    def name(self) -> str:
        return "assessment_diff"

    @property
    def description(self) -> str:
        return (
            "Compare two assessment runs and highlight differences.\n\n"
            "Use when:\n"
            "  - You want to see new findings since the last scan.\n"
            "  - You need to know which findings were resolved.\n"
            "  - You want to track severity or confidence changes.\n"
            "  - You want to discover new assets or services.\n\n"
            "Inputs:\n"
            "  - assessment_id_a: baseline assessment identifier (required).\n"
            "  - assessment_id_b: current assessment identifier (required).\n\n"
            "Returns:\n"
            "  - new_findings, resolved_findings, changed_findings,\n"
            "    new_assets, resolved_assets, new_services, summary.\n\n"
            "Does not: execute new scans (only compares existing assessment data).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 30

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "assessment_id_a": {
                    "type": "string",
                    "description": "Baseline assessment identifier (required)",
                },
                "assessment_id_b": {
                    "type": "string",
                    "description": "Current assessment identifier (required)",
                },
            },
            "required": ["assessment_id_a", "assessment_id_b"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("assessment_id_a"):
            raise ValueError("assessment_id_a is required")
        if not arguments.get("assessment_id_b"):
            raise ValueError("assessment_id_b is required")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["assessment_diff"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        assessment_id_a = arguments["assessment_id_a"]
        assessment_id_b = arguments["assessment_id_b"]

        db = dbm.get_db()
        differ = AssessmentDiffer(db_manager=db)
        diff_result = differ.diff(assessment_id_a, assessment_id_b)

        payload = diff_result.to_dict()
        result = ExecutionResult(
            tool=self.name, command=self.name,
            stdout=json.dumps(payload, indent=2), stderr="",
            exit_code=0, success=True, timed_out=False,
            duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
        )
        return success_response(result)


# ── 11. coverage_summary ───────────────────────────────────────────────────

class CoverageSummaryTool:
    """Show coverage gaps and summary for an assessment."""

    @property
    def name(self) -> str:
        return "coverage_summary"

    @property
    def description(self) -> str:
        return (
            "Show what was tested and what was missed in an assessment.\n\n"
            "Use when:\n"
            "  - You need to know which services were never scanned.\n"
            "  - You want to see which assets have no findings.\n"
            "  - You want a coverage percentage and tool inventory.\n\n"
            "Inputs:\n"
            "  - assessment_id: the assessment to analyze (required).\n\n"
            "Returns:\n"
            "  - percent_covered, assets_discovered/scanned, services_scanned,\n"
            "    tools_used, total_findings, gap_count, coverage_gaps[].\n\n"
            "Does not: run new scans (only reports on existing coverage data).\n"
        )

    @property
    def default_timeout(self) -> int:
        return 30

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "assessment_id": {
                    "type": "string",
                    "description": "Assessment identifier (required)",
                },
            },
            "required": ["assessment_id"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("assessment_id"):
            raise ValueError("assessment_id is required")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["coverage_summary"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)

        assessment_id = arguments["assessment_id"]
        tracker = CoverageTracker()

        # Pull coverage data from the DB for this assessment
        db = dbm.get_db()
        if db is not None:
            try:
                # Get scans for this assessment
                scans = db.conn.execute(
                    "SELECT id, tool, target_id FROM scans WHERE assessment_id = ?",
                    (assessment_id,),
                ).fetchall()
                for scan_id, tool, target_id in scans:
                    # Get findings for this scan
                    findings = db.conn.execute(
                        "SELECT id FROM findings WHERE scan_id = ?",
                        (scan_id,),
                    ).fetchall()
                    findings_count = len(findings)
                    # Get target name
                    target_row = db.conn.execute(
                        "SELECT target FROM targets WHERE id = ?",
                        (target_id,),
                    ).fetchone()
                    asset_name = target_row[0] if target_row else str(target_id)
                    status = "findings" if findings_count > 0 else "no_findings"
                    tracker.record_coverage(
                        assessment_id=assessment_id,
                        asset_id=asset_name,
                        service=None,
                        tool=tool,
                        result_status=status,
                        findings_count=findings_count,
                    )
            except Exception:  # noqa: BLE001
                pass

        summary = tracker.get_coverage_summary(assessment_id)
        gaps = tracker.get_coverage_gaps(assessment_id)

        payload = {
            "assessment_id": assessment_id,
            "summary": summary,
            "coverage_gaps": gaps,
        }
        result = ExecutionResult(
            tool=self.name, command=self.name,
            stdout=json.dumps(payload, indent=2), stderr="",
            exit_code=0, success=True, timed_out=False,
            duration=0.0, start_time=utc_now_iso(), end_time=utc_now_iso(),
        )
        return success_response(result)


__all__ = [
    "AssessmentRunTool", "BatchRunTool", "JobControlTool",
    "FindingsQueryTool", "EvidenceGetTool", "AssetGraphTool",
    "FindingTransitionTool", "AssessmentDiffTool", "CoverageSummaryTool",
    "ToolCatalogTool", "ReportGenerateTool",
    "AGENT_MODE_TOOLS", "EXPERT_MODE_TOOLS", "TOOL_LAYERS",
]