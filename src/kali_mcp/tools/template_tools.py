"""Template tooling — render a template into a playbook and execute it."""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.utils.jobs import JOB_REGISTRY, _new_id, _run_background
from kali_mcp.utils.time import utc_now_iso


# ── Alias maps (AI-agent friendly: accept any common spelling) ──
# Any of these keys resolve to the template identifier.
_TEMPLATE_ID_KEYS = ("template_id", "template", "id", "name", "template_name")

# Any of these keys resolve to the target parameter.
_TARGET_KEYS = ("target", "host", "ip", "domain", "url", "target_host")

# MCP-level fields that are NOT template parameters.
_MCP_KEYS = frozenset(
    {"template_id", "template", "id", "name", "template_name",
     "params", "background", "target", "host", "ip", "domain", "url"}
)


def _resolve_template_id(arguments: dict[str, Any]) -> str:
    """Return the template identifier from any accepted alias."""
    for key in _TEMPLATE_ID_KEYS:
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _extract_params(arguments: dict[str, Any]) -> dict[str, Any]:
    """Merge canonical ``params`` object with any flat top-level parameter keys.

    Every top-level key that is not an MCP-level field is treated as a template
    parameter. This lets callers pass parameters either nested under ``params``
    or flat at the top level — both work identically.
    """
    params: dict[str, Any] = {}
    raw_params = arguments.get("params")
    if isinstance(raw_params, dict):
        params.update(raw_params)
    for key, val in arguments.items():
        if key in _MCP_KEYS:
            continue
        if key not in params:
            params[key] = val
    return params


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
            "Inputs (all flexible):\n"
            "  - template_id | template | id | name : template id from template_list (required)\n"
            "  - params : object of template parameters, OR pass parameters flat at top level\n"
            "    (e.g. target=..., depth=..., benchmark=...)\n"
            "  - target | host | ip | domain | url : the target to assess\n"
            "  - background : force background execution (returns job_id immediately)\n\n"
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
                    "description": "Template id from template_list (also accepted as 'template', 'id', or 'name')",
                },
                "template": {
                    "type": "string",
                    "description": "Alias for template_id",
                },
                "id": {
                    "type": "string",
                    "description": "Alias for template_id",
                },
                "name": {
                    "type": "string",
                    "description": "Alias for template_id",
                },
                "template_name": {
                    "type": "string",
                    "description": "Alias for template_id",
                },
                "params": {
                    "type": "object",
                    "description": "Template parameters (flat key/value map). Top-level parameter keys are also accepted and merged into params.",
                },
                "target": {
                    "type": "string",
                    "description": "Target to assess (also accepted as host, ip, domain, url)",
                },
                "host": {"type": "string", "description": "Alias for target"},
                "ip": {"type": "string", "description": "Alias for target"},
                "domain": {"type": "string", "description": "Alias for target"},
                "url": {"type": "string", "description": "Alias for target"},
                "background": {
                    "type": "boolean",
                    "description": "Force background execution (returns job_id)",
                },
            },
            "required": [],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        template_id = _resolve_template_id(arguments)
        if not template_id:
            raise ValueError(
                "template_id is required (also accepted as 'template', 'id', or 'name')"
            )
        params = _extract_params(arguments)
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        try:
            from kali_mcp.playbooks.registry import get_template

            get_template(template_id)
        except KeyError as e:
            raise ValueError(f"unknown template: {e}")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        template_id = _resolve_template_id(arguments)
        return ["template_run", template_id]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # Resolve template id from any accepted alias.
        template_id = _resolve_template_id(arguments)
        # Merge canonical params with flat top-level parameter keys.
        params = _extract_params(arguments)
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
            finished_at=utc_now_iso(),
            result={
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )

        return {
            "tool": self.name,
            "command": self.build_command(arguments),
            "job_id": job_id,
            "template": template_id,
            "status": JOB_REGISTRY[job_id]["status"],
            "result": result,
        }

    async def _run_background(
        self, template_id: str, definition: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        import asyncio

        job_id = _new_id("job")
        JOB_REGISTRY[job_id] = {
            "job_id": job_id,
            "assessment_id": job_id,
            "tool": self.name,
            "template": template_id,
            "status": "accepted",
            "started_at": utc_now_iso(),
        }

        async def _run() -> None:
            from kali_mcp.workflow import PlaybookEngine as DAGEngine

            engine = DAGEngine()
            try:
                result = await engine.run(definition)
                JOB_REGISTRY[job_id].update(
                    status="completed" if result.success else "failed",
                    finished_at=utc_now_iso(),
                    result={
                        "success": result.success,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    },
                )
            except Exception as e:  # noqa: BLE001
                JOB_REGISTRY[job_id].update(
                    status="failed",
                    error=f"{type(e).__name__}: {e}",
                    finished_at=utc_now_iso(),
                )

        asyncio.create_task(_run())
        return {
            "tool": self.name,
            "command": ["template_run", template_id],
            "job_id": job_id,
            "template": template_id,
            "status": "accepted",
            "next_actions": [
                "Use job_control or template_result with this job_id to poll progress.",
            ],
        }
