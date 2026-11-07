"""Template tooling — render a template into a playbook and execute it."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from kali_mcp.models import utc_now_iso
from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.playbook_blackbox import JOB_REGISTRY, _new_id, _success_tool_result


# ── Alias maps (AI-agent friendly: accept any common spelling) ──
# Any of these keys resolve to the template identifier.
_TEMPLATE_ID_KEYS = ("template_id", "template", "id", "name", "template_name")

# Keys that contain sensitive values and should be redacted from outputs.
_SENSITIVE_KEYS = frozenset(
    {"password", "passwd", "secret", "api_key", "apikey", "token", "private_key"}
)


def _is_sensitive_key(key: str) -> bool:
    """Return True if a parameter key looks sensitive."""
    k = key.lower()
    return any(s in k for s in _SENSITIVE_KEYS)


def _redact_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of params with sensitive keys removed."""
    redacted: dict[str, Any] = {}
    for key, val in params.items():
        if _is_sensitive_key(key):
            continue  # drop sensitive keys entirely
        redacted[key] = val
    return redacted


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
    # MCP-level fields that are NOT template parameters.
    _mcp_keys = frozenset(
        {
            "template_id",
            "template",
            "id",
            "name",
            "template_name",
            "params",
            "background",
            "target",
            "host",
            "ip",
            "domain",
            "url",
        }
    )
    params: dict[str, Any] = {}
    raw_params = arguments.get("params")
    if isinstance(raw_params, dict):
        params.update(raw_params)
    for key, val in arguments.items():
        if key in _mcp_keys:
            continue
        if key not in params:
            params[key] = val
    return params


# ── template_list ─────────────────────────────────────────────────────


class TemplateListTool(BaseTool):
    """List available templates with their parameters."""

    @property
    def name(self) -> str:
        return "template_list"

    @property
    def description(self) -> str:
        return (
            "List available assessment templates.\n\n"
            "Returns each template's id, name, description, and declared\n"
            "parameters (with types, required flags, and defaults). Use the\n"
            "template id with template_run to execute a template.\n\n"
            "No inputs required."
        )

    @property
    def default_timeout(self) -> int:
        return 30

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "detail": {
                    "type": "string",
                    "description": "Output detail level: compact (default) or full",
                    "default": "compact",
                }
            },
            "required": [],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        # No inputs required — accept anything or nothing.
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["template_list"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kali_mcp.playbooks.registry import list_templates

        templates = list_templates()
        detail = arguments.get("detail", "compact")

        if detail == "full":
            out_templates = templates
        else:
            out_templates = []
            for t in templates:
                params = t.get("parameters", {}) or {}
                required = [n for n, s in params.items() if isinstance(s, dict) and s.get("required")]
                out_templates.append({
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "required_params": required,
                })

        payload = {
            "tool": self.name,
            "command": ["template_list"],
            "templates": out_templates,
            "count": len(out_templates),
            "next_actions": [
                "Use template_run with a template id from the list to execute.",
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
        raw_params = arguments.get("params")
        if raw_params is not None and not isinstance(raw_params, dict):
            raise ValueError("params must be an object")
        params = _extract_params(arguments)
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
                "stderr": getattr(result, "stderr", ""),
            },
        )

        payload = {
            "job_id": job_id,
            "template_id": template_id,
            "status": JOB_REGISTRY[job_id]["status"],
            "steps": [],
            "step_results": {},
            "findings": [],
            "summary": {"total": 0, "by_severity": {}},
            "result": {
                "success": result.success,
                "stdout": result.stdout,
                "stderr": getattr(result, "stderr", ""),
            },
        }

        # Populate steps, step_results, findings from engine output if available
        try:
            stdout = getattr(result, "stdout", "") or ""
            data = json.loads(stdout) if isinstance(stdout, str) else {}
            if isinstance(data, dict):
                steps = data.get("steps", [])
                if isinstance(steps, list):
                    payload["steps"] = steps
                sr = data.get("step_results", {})
                if isinstance(sr, dict):
                    payload["step_results"] = sr
                findings = []
                for _sid, sr_item in sr.items():
                    if isinstance(sr_item, dict):
                        for f in sr_item.get("findings", []) or []:
                            if isinstance(f, dict):
                                findings.append(f)
                payload["findings"] = findings
                by_severity: dict[str, int] = {}
                for f in findings:
                    sev = f.get("severity", "informational") if isinstance(f, dict) else "informational"
                    by_severity[sev] = by_severity.get(sev, 0) + 1
                payload["summary"] = {
                    "total": len(findings),
                    "by_severity": by_severity,
                }
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

        wrapped = {
            "isError": False,
            "template_run": payload,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"stdout": json.dumps(payload)}),
                }
            ],
        }
        return wrapped

    async def _run_background(
        self, template_id: str, definition: Any, params: dict[str, Any]
    ) -> dict[str, Any]:
        job_id = _new_id("job")
        JOB_REGISTRY[job_id] = {
            "job_id": job_id,
            "assessment_id": job_id,
            "tool": self.name,
            "template": template_id,
            "status": "accepted",
            "started_at": utc_now_iso(),
        }

        # Redact sensitive params for the returned payload
        safe_params = _redact_params(params)

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
                        "stderr": getattr(result, "stderr", ""),
                    },
                )
            except Exception as e:  # noqa: BLE001
                JOB_REGISTRY[job_id].update(
                    status="failed",
                    error=f"{type(e).__name__}: {e}",
                    finished_at=utc_now_iso(),
                )

        asyncio.create_task(_run())

        payload = {
            "tool": self.name,
            "command": ["template_run", template_id],
            "job_id": job_id,
            "template_id": template_id,
            "template": template_id,
            "status": "accepted",
            "params": safe_params,
            "next_actions": [
                "Use job_control or template_result with this job_id to poll progress.",
            ],
        }
        return {
            "isError": False,
            "template_run": payload,
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"stdout": json.dumps(payload)}),
                }
            ],
        }

    async def _guarded(self, job_id: str, coro) -> None:
        """Run a coroutine under a job id; mark failed on exception."""
        try:
            if asyncio.iscoroutinefunction(coro):
                await coro()
            else:
                await coro
        except Exception as e:  # noqa: BLE001
            JOB_REGISTRY[job_id] = {
                "job_id": job_id,
                "status": "failed",
                "error": f"{type(e).__name__}: {e}",
                "finished_at": utc_now_iso(),
            }

    @staticmethod
    def _payload_from_execution(
        template_id: str, job_id: str, result: Any
    ) -> dict[str, Any]:
        """Convert an engine ExecutionResult into a compact tool payload."""
        stdout = getattr(result, "stdout", "") or ""
        success = getattr(result, "success", False)

        try:
            data = json.loads(stdout) if isinstance(stdout, str) else {}
        except (json.JSONDecodeError, TypeError):
            data = {}

        step_results = data.get("step_results", {}) if isinstance(data, dict) else {}
        if not isinstance(step_results, dict):
            step_results = {}

        findings = []
        for _step_id, sr in step_results.items():
            if isinstance(sr, dict):
                for f in sr.get("findings", []) or []:
                    if isinstance(f, dict):
                        findings.append(f)

        by_severity: dict[str, int] = {}
        for f in findings:
            sev = f.get("severity", "informational") if isinstance(f, dict) else "informational"
            by_severity[sev] = by_severity.get(sev, 0) + 1

        steps = data.get("steps", []) if isinstance(data, dict) else []
        if not isinstance(steps, list):
            steps = []

        return {
            "job_id": job_id,
            "template_id": template_id,
            "status": "completed" if success else "failed",
            "steps": steps,
            "step_results": step_results,
            "findings": findings,
            "summary": {
                "total": len(findings),
                "by_severity": by_severity,
            },
        }
