"""Template tools (v2.0).

Instantiated assessment blueprints with pre-declared parameters.
Agents can:
- template_list: browse available templates and their parameter schemas
- template_run: render a template with parameters and execute the resulting
  workflow-engine playbook (inline, or as a background job via job_id)

Templates live in ``src/kali_mcp/playbooks/templates/`` and are loaded by
``kali_mcp.playbooks.registry`` through its template loader.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from kali_mcp.models import ExecutionResult, utc_now_iso
from kali_mcp.responses import success_response
from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.playbook_blackbox import JOB_REGISTRY

logger = logging.getLogger("kali_mcp.tools")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _success_tool_result(
    tool_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return success_response(
        ExecutionResult(
            tool=tool_name,
            command=tool_name,
            stdout=json.dumps(payload, indent=2, default=str),
            stderr="",
            exit_code=0,
            success=True,
            timed_out=False,
            duration=0.0,
            start_time=utc_now_iso(),
            end_time=utc_now_iso(),
        )
    )


# ── template_list ─────────────────────────────────────────────────────


class TemplateListTool(BaseTool):
    """List assessment templates and their parameters."""

    @property
    def name(self) -> str:
        return "template_list"

    @property
    def description(self) -> str:
        return (
            "List available assessment templates and their required parameters.\n\n"
            "Use when:\n"
            "  - You want a pre-orchestrated assessment without building a\n"
            "    custom playbook.\n"
            "  - You need to know which parameters to pass to template_run.\n\n"
            "Inputs:\n"
            "  - (none)\n\n"
            "Returns:\n"
            "  - Templates with id, name, description, and parameter schema\n"
            "    (type, description, required, default).\n\n"
            "Does not: execute anything."
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
        return ["template_list"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kali_mcp.playbooks.registry import list_templates

        templates = list_templates()
        detail = arguments.get("detail", "compact")
        if detail == "compact":
            templates = [
                {"id": t["id"], "name": t["name"], "description": t["description"],
                 "required_params": [k for k, v in t["parameters"].items() if v["required"]]}
                for t in templates
            ]
        payload = {
            "templates": templates,
            "count": len(templates),
            "next_actions": [
                "Call template_run with a template id and its required parameters."
            ],
        }
        return _success_tool_result(self.name, payload)


# ── template_run ──────────────────────────────────────────────────────


class TemplateRunTool(BaseTool):
    """Render a template into a playbook and execute it."""

    @property
    def name(self) -> str:
        return "template_run"

    @property
    def description(self) -> str:
        return (
            "Execute a pre-orchestrated assessment template in one call.\n\n"
            "Use when:\n"
            "  - A template from template_list matches your scenario.\n"
            "  - You want curated tool orchestration with minimal parameters.\n\n"
            "Inputs:\n"
            "  - template_id: template id from template_list (required).\n"
            "  - params: template parameters — see template_list (required).\n"
            "    Every parameter is passed flat, e.g. target, depth, benchmark.\n"
            "  - background: force background execution, returning job_id.\n\n"
            "Returns:\n"
            "  - job_id, status, per-step results, findings, summary, next_actions.\n\n"
            "Does not: expose internal module wiring (templates are pre-authorized)."
        )

    @property
    def default_timeout(self) -> int:
        return 3600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "Template id from template_list (required; or use 'template')",
                },
                "template": {
                    "type": "string",
                    "description": "Alias for template_id (template id from template_list)",
                },
                "params": {
                    "type": "object",
                    "description": "Template parameters (flat key/value map). Top-level parameter keys are also accepted and merged into params.",
                },
                "background": {
                    "type": "boolean",
                    "description": "Force background execution (returns job_id)",
                },
            },
            "required": [],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        # Accept "template" as a user-friendly alias for "template_id".
        template_id = arguments.get("template_id") or arguments.get("template")
        if not template_id:
            raise ValueError("template_id is required")
        # Accept flat top-level params (e.g. target=..., benchmark=...) in
        # addition to the canonical "params" object. Merge them into params.
        params = arguments.get("params")
        if params is None:
            params = {}
        elif not isinstance(params, dict):
            raise ValueError("params must be an object")
        # Fold any top-level template-parameter keys into params (keys that
        # are not MCP-level fields).
        mcp_keys = {"template_id", "template", "params", "background"}
        for key, val in arguments.items():
            if key not in mcp_keys and key not in params:
                params[key] = val
        if params is not None and not isinstance(params, dict):
            raise ValueError("params must be an object")
        try:
            from kali_mcp.playbooks.registry import get_template

            get_template(template_id)
        except KeyError as e:
            raise ValueError(f"unknown template: {e}")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        template_id = arguments.get("template_id") or arguments.get("template", "")
        return ["template_run", template_id]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # Normalize: accept "template" alias for "template_id".
        template_id = arguments.get("template_id") or arguments.get("template")
        # Normalize: merge flat top-level params into params.
        params = arguments.get("params") or {}
        mcp_keys = {"template_id", "template", "params", "background"}
        for key, val in arguments.items():
            if key not in mcp_keys and key not in params:
                params[key] = val
        wants_background = bool(arguments.get("background", False))

        # Render FIRST: this validates required and merges defaults
        from kali_mcp.playbooks.registry import (
            TemplateNotFound,
            render_template,
        )
        from kali_mcp.workflow.yaml_loader import PlaybookError

        try:
            definition = render_template(template_id, params)
        except TemplateNotFound:
            raise
        except PlaybookError as e:
            raise ValueError(f"template produced an invalid playbook: {e}")

        # Explicit background flag → background execution returning job_id
        if wants_background:
            return await self._run_background(template_id, definition, params)

        job_id = _new_id("job")
        JOB_REGISTRY[job_id] = {
            "job_id": job_id,
            "assessment_id": job_id,
            "tool": self.name,
            "template": template_id,
            "status": "running",
            "started_at": utc_now_iso(),
        }

        from kali_mcp.workflow import PlaybookEngine as DAGEngine

        engine = DAGEngine()
        try:
            result = await engine.run(definition)
        except Exception as e:
            JOB_REGISTRY[job_id].update(
                status="failed",
                error=f"{type(e).__name__}: {e}",
                finished_at=utc_now_iso(),
            )
            raise
        JOB_REGISTRY[job_id].update(
            status="completed" if result.success else "failed",
            result=json.loads(result.stdout),
            finished_at=utc_now_iso(),
        )

        payload = self._payload_from_execution(
            template_id, job_id, result
        )
        response = _success_tool_result(self.name, payload)
        response["template_run"] = payload
        return response

    async def _run_background(
        self, template_id: str, definition: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        job_id = _new_id("job")
        JOB_REGISTRY[job_id] = {
            "job_id": job_id,
            "assessment_id": job_id,
            "tool": self.name,
            "template": template_id,
            "status": "running",
            "started_at": utc_now_iso(),
        }

        async def run() -> None:
            from kali_mcp.workflow import PlaybookEngine as DAGEngine

            engine = DAGEngine()
            result = await engine.run(definition)
            JOB_REGISTRY[job_id].update(
                status="completed" if result.success else "failed",
                result=json.loads(result.stdout),
                finished_at=utc_now_iso(),
            )

        asyncio.create_task(self._guarded(job_id, run))
        payload = {
            "job_id": job_id,
            "template_id": template_id,
            "status": "accepted",
            "params": {k: v for k, v in params.items() if "password" not in k.lower()},
            "next_actions": [
                "Use job_control or playbook_result with this job_id to poll progress.",
            ],
        }
        response = _success_tool_result(self.name, payload)
        response["template_run"] = payload
        return response

    async def _guarded(self, job_id: str, run) -> None:
        try:
            await run()
        except Exception as e:
            JOB_REGISTRY.setdefault(job_id, {})
            JOB_REGISTRY[job_id].update(
                status="failed",
                error=f"{type(e).__name__}: {e}",
                finished_at=utc_now_iso(),
            )
            logger.exception("background template job %s failed", job_id)

    @staticmethod
    def _payload_from_execution(
        template_id: str, job_id: str, result: Any
    ) -> dict[str, Any]:
        stdout_payload: dict[str, Any] = {}
        try:
            stdout_payload = json.loads(result.stdout or "{}")
        except (TypeError, ValueError):
            stdout_payload = {}

        step_results = stdout_payload.get("step_results", {}) or {}
        findings: list[dict[str, Any]] = []
        for step_name, res in step_results.items():
            if isinstance(res, dict):
                findings.extend(
                    f for f in res.get("findings", []) if isinstance(f, dict)
                )

        severity_counts: dict[str, int] = {}
        for f in findings:
            sev = f.get("severity", "informational")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        return {
            "job_id": job_id,
            "template_id": template_id,
            "status": "completed" if result.success else "failed",
            "steps": stdout_payload.get("steps", []),
            "step_results": step_results,
            "findings": findings,
            "summary": {"total": len(findings), "by_severity": severity_counts},
            "next_actions": [
                "Use playbook_result with this job_id for the raw payload.",
                "Use report_generate to package findings for delivery.",
            ],
        }
