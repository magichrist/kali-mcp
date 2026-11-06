"""Black-box playbook interface tools (v2.0).

The agent-facing contract: agents see playbooks, run them, and read results.
Internal modules, tool wrappers, and DAG wiring are implementation details.

Tools:
- playbook_run: execute a playbook by catalog id against one target
- playbook_catalog: list available playbooks with inputs/outputs
- playbook_result: fetch results of a previous run by assessment_id or job_id

Long-running executions return a job_id immediately and continue in the
background; results land in vault category ``playbook_results`` keyed by
job_id (engine-side) and are mirrored in THE in-memory JOB_REGISTRY so
playbook_result can serve them without a vault round-trip.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from kali_mcp.models import ExecutionResult, ToolError, utc_now_iso
from kali_mcp.responses import error_response, success_response
from kali_mcp.tools.base import BaseTool

logger = logging.getLogger("kali_mcp.tools")

# In-memory job registry: job_id -> {status, assessment_id, playbook, target, result, ...}
JOB_REGISTRY: dict[str, dict[str, Any]] = {}

VALID_PROFILES = ("safe_active", "aggressive", "passive")
VALID_DETAIL = ("summary", "normal", "full")


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    return result


def _success_tool_result(
    tool_name: str, payload: dict[str, Any], exit_code: int = 0
) -> dict[str, Any]:
    return success_response(
        ExecutionResult(
            tool=tool_name,
            command=tool_name,
            stdout=json.dumps(payload, indent=2, default=str),
            stderr="",
            exit_code=exit_code,
            success=True,
            timed_out=False,
            duration=0.0,
            start_time=utc_now_iso(),
            end_time=utc_now_iso(),
        )
    )


# ── playbook_run ──────────────────────────────────────────────────────


class PlaybookRunTool(BaseTool):
    """Execute a complete playbook against a target (black-box contract)."""

    @property
    def name(self) -> str:
        return "playbook_run"

    @property
    def description(self) -> str:
        return (
            "Execute a complete automated assessment playbook in one call.\n\n"
            "Use when:\n"
            "  - You want a full assessment without orchestrating individual tools.\n"
            "  - You want machine-discovered assets, findings, and next steps.\n"
            "  - Long executions return a job_id and continue in the background.\n\n"
            "Inputs:\n"
            "  - playbook: playbook id from playbook_catalog (required).\n"
            "  - target: single target domain/IP/URL (required).\n"
            "  - scope_id: optional scope identifier for the authorization boundary.\n"
            "  - profile: safe_active | aggressive | passive (default safe_active).\n"
            "  - detail: summary | normal | full (default normal).\n"
            "  - background: run as a background job and return job_id (default auto).\n\n"
            "Returns:\n"
            "  - assessment_id, job_id, status, assets, findings, correlated findings,\n"
            "    asset_graph, next_actions, execution summary.\n\n"
            "Does not: return raw tool stdout (use playbook_result or vault)."
        )

    @property
    def default_timeout(self) -> int:
        return 3600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "playbook": {
                    "type": "string",
                    "description": "Playbook id from playbook_catalog (required)",
                },
                "target": {
                    "type": "string",
                    "description": "Single target domain, IP, or URL (required)",
                },
                "scope_id": {
                    "type": "string",
                    "description": "Optional scope identifier for the authorization boundary",
                },
                "profile": {
                    "type": "string",
                    "description": "Execution profile: safe_active | aggressive | passive",
                    "default": "safe_active",
                },
                "detail": {
                    "type": "string",
                    "description": "Response verbosity: summary | normal | full",
                    "default": "normal",
                },
                "options": {
                    "type": "object",
                    "description": "Playbook-specific options passed to module inputs",
                },
                "background": {
                    "type": "boolean",
                    "description": "Force background execution (returns job_id immediately)",
                },
            },
            "required": ["playbook", "target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("playbook"):
            raise ValueError("playbook is required")
        if not arguments.get("target"):
            raise ValueError("target is required")
        profile = arguments.get("profile", "safe_active")
        if profile not in VALID_PROFILES:
            raise ValueError("profile must be safe_active, aggressive, or passive")
        detail = arguments.get("detail", "normal")
        if detail not in VALID_DETAIL:
            raise ValueError("detail must be summary, normal, or full")
        try:
            from kali_mcp.playbooks.registry import get_playbook

            get_playbook(arguments["playbook"])
        except KeyError as e:
            raise ValueError(f"unknown playbook: {e}")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_run", arguments.get("playbook", ""), arguments.get("target", "")]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kali_mcp.playbooks.engine import PlaybookEngine

        playbook = arguments["playbook"]
        target = arguments["target"]
        scope_id = arguments.get("scope_id") or ""
        profile = arguments.get("profile", "safe_active")
        detail = arguments.get("detail", "normal")

        job_id = _new_id("job")
        assessment_id = _new_id("assessment")
        JOB_REGISTRY[job_id] = {
            "job_id": job_id,
            "assessment_id": assessment_id,
            "tool": self.name,
            "playbook": playbook,
            "target": target,
            "status": "running",
            "started_at": utc_now_iso(),
        }

        engine = PlaybookEngine()

        async def run() -> dict[str, Any]:
            assessment = await engine.execute(
                playbook_id=playbook,
                target=target,
                scope_id=scope_id,
                profile=profile,
                detail=detail,
                assessment_id=assessment_id,
                job_id=job_id,
            )
            STATUS = JOB_REGISTRY[job_id]
            STATUS["status"] = assessment.get("execution", {}).get(
                "status", "completed"
            ) if isinstance(assessment.get("execution"), dict) else "completed"
            STATUS["result"] = assessment
            STATUS["finished_at"] = utc_now_iso()
            _truncate_payload(assessment)
            return assessment

        # Estimate duration from the playbook execution config; long runs go async
        from kali_mcp.playbooks.registry import get_playbook

        pb = get_playbook(playbook)
        est_timeout = int((pb.get("execution") or {}).get("timeout", 300))
        wants_background = bool(
            arguments.get("background", est_timeout > 300)
        )

        if wants_background:
            asyncio.create_task(_run_background(job_id, run))
            payload = {
                "job_id": job_id,
                "assessment_id": assessment_id,
                "playbook": playbook,
                "target": target,
                "status": "accepted",
                "next_actions": [
                    "Use job_control or playbook_result with this job_id/assessment_id to poll progress.",
                ],
            }
            _success = _success_tool_result(self.name, payload)
            _success["assessment_run"] = payload
            return _success

        assessment = await run()
        engine_status = JOB_REGISTRY[job_id]["status"]
        summary = assessment.get("summary") or {
            "assets": 0,
            "findings": 0,
        }
        payload = {
            "job_id": job_id,
            "assessment_id": assessment.get("assessment_id", assessment_id),
            "playbook": playbook,
            "target": target,
            "status": engine_status,
            "summary": summary,
            "assets": assessment.get("assets", {}) or {},
            "findings": assessment.get("findings", []) or [],
            "correlated_findings": assessment.get("correlated_findings", []) or [],
            "asset_graph": assessment.get("asset_graph", {}) or {},
            "next_actions": assessment.get("next_actions", []) or [],
            "execution": assessment.get("execution", {}) or {},
        }
        if detail == "full":
            payload["context"] = {
                k: assessment.get(k) for k in ("evidence", "coverage", "module_results")
                if k in assessment
            }

        result = _success_tool_result(self.name, payload)
        result["assessment_run"] = payload
        return result


async def _run_background(job_id: str, coroutine_factory) -> None:
    """Run a background playbook task and keep the registry entry updated."""
    try:
        await coroutine_factory()
    except Exception as e:  # noqa: BLE001 — background jobs must never raise
        STATUS = JOB_REGISTRY.get(job_id)
        if STATUS is not None:
            STATUS["status"] = "failed"
            STATUS["error"] = f"{type(e).__name__}: {e}"
            STATUS["finished_at"] = utc_now_iso()
        logger.exception("background playbook job %s failed", job_id)


def _truncate_payload(assessment: dict[str, Any], limit: int = 5_000_000) -> None:
    """Keep the in-memory result JSON bounded for very large assessments."""
    text = json.dumps(assessment, default=str)
    if len(text) <= limit:
        return
    for key in ("evidence", "module_results"):
        node = assessment.get(key)
        if isinstance(node, dict):
            for sub_key in list(node.keys())[: -3]:
                node.pop(sub_key)


# ── playbook_catalog ──────────────────────────────────────────────────


class PlaybookCatalogTool(BaseTool):
    """List available playbooks (black-box contract — no internals exposed)."""

    @property
    def name(self) -> str:
        return "playbook_catalog"

    @property
    def description(self) -> str:
        return (
            "List available playbooks and their inputs/outputs.\n\n"
            "Use when:\n"
            "  - You need to pick a playbook before calling playbook_run.\n"
            "  - You want to know a playbook's expected inputs or duration.\n\n"
            "Inputs:\n"
            "  - (none)\n\n"
            "Returns:\n"
            "  - id, name, description, inputs, outputs, estimated_duration per playbook.\n\n"
            "Does not: expose internal modules, steps, or tool lists (black-box contract)."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "detail": {
                    "type": "string",
                    "description": "verbosity: compact | full (default compact)",
                    "default": "compact",
                },
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_catalog"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kali_mcp.playbooks.registry import list_playbooks

        playbooks = list_playbooks()
        detail = arguments.get("detail", "compact")
        if detail == "compact":
            playbooks = [
                {"id": p["id"], "name": p["name"], "description": p["description"],
                 "estimated_duration": p.get("estimated_duration", 300)}
                for p in playbooks
            ]
        payload = {"playbooks": playbooks, "count": len(playbooks)}
        return _success_tool_result(self.name, payload)


# ── playbook_result ───────────────────────────────────────────────────


class PlaybookResultTool(BaseTool):
    """Fetch results of a previous playbook run by assessment_id or job_id."""

    @property
    def name(self) -> str:
        return "playbook_result"

    @property
    def description(self) -> str:
        return (
            "Retrieve results of a previous playbook run.\n\n"
            "Use when:\n"
            "  - playbook_run returned a job_id and you need the final result.\n"
            "  - You want to re-read or diff a past assessment.\n\n"
            "Inputs:\n"
            "  - assessment_id or job_id: identifier of the run (one required).\n\n"
            "Returns:\n"
            "  - Full assessment payload: assets, findings, correlated findings,\n"
            "    asset_graph, evidence references, execution summary.\n\n"
            "Does not: execute anything."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "assessment_id": {
                    "type": "string",
                    "description": "Assessment identifier of a previous run",
                },
                "job_id": {
                    "type": "string",
                    "description": "Job identifier of a previous run",
                },
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("assessment_id") and not arguments.get("job_id"):
            raise ValueError("assessment_id or job_id is required")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_result", arguments.get("assessment_id") or arguments.get("job_id")]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        assessment_id = arguments.get("assessment_id") or ""
        job_id = arguments.get("job_id") or ""
        key = job_id or assessment_id

        # 1. In-memory registry (running / completed this session)
        for _, status in JOB_REGISTRY.items():
            if status.get("job_id") == key or status.get("assessment_id") == key:
                running = status.get("status") == "running"
                payload = {
                    "job_id": status.get("job_id"),
                    "assessment_id": status.get("assessment_id"),
                    "playbook": status.get("playbook"),
                    "target": status.get("target"),
                    "status": status.get("status"),
                    "result": None if running else (status.get("result") or {}),
                }
                if status.get("error"):
                    payload["error"] = status["error"]
                if running:
                    payload["next_actions"] = [
                        "Job still running — call playbook_result again or use job_control to wait."
                    ]
                return _success_tool_result(self.name, payload)

        # 2. Vault fallback (past jobs across sessions)
        try:
            from kali_mcp.utils.vault import vault_read, vault_query

            raw = vault_read("playbook_results", key)
            raw_text = raw if isinstance(raw, str) else json.dumps(raw)
            if raw_text and '"error": "not found"' not in raw_text:
                data = json.loads(raw_text)
                payload = {
                    "job_id": key,
                    "assessment_id": (data or {}).get("assessment_id", key),
                    "playbook": (data or {}).get("playbook_id", ""),
                    "target": (data or {}).get("target", ""),
                    "status": "completed",
                    "result": data,
                }
                return _success_tool_result(self.name, payload)
            # job_id unknown — search by target/assessment metadata
            hits = vault_query(category="playbook_results", search=key, limit=5)
            rows = hits.get("rows") or hits.get("results") or []
            if rows:
                payload = {
                    "job_id": key,
                    "status": "found",
                    "candidate_rows": [
                        {"category": r.get("category"), "name": r.get("name")}
                        for r in rows[:5]
                    ],
                    "next_actions": [
                        "Use playbook_result with the job_id (row name) of a candidate."
                    ],
                }
                return _success_tool_result(self.name, payload)
        except Exception as e:  # noqa: BLE001 — vault issues surface as a soft error
            logger.debug("playbook_result vault fallback failed: %s", e)

        return error_response(
            ToolError(
                error="Result not found",
                details=f"no playbook run found for {key!r} (in-memory or vault)",
            )
        )
