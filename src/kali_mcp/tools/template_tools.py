"""Template tooling — render a template into a playbook and execute it.

Templates are playbooks with parameters. ``template_run`` is a thin wrapper
around ``playbook_run``: it resolves the template id, merges flat parameter
keys into a params dict, and delegates to the shared template execution path
in ``playbook_blackbox``. Everything is a playbook — templates are just
playbooks with declared parameters.
"""

from __future__ import annotations

from typing import Any

from kali_mcp.models import utc_now_iso
from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.playbook_blackbox import (
    JOB_REGISTRY,
    _new_id,
    _run_template_defn,
    _success_tool_result,
)

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
    parameter.
    """
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
            "List available templates — playbooks with declared parameters.\n\n"
            "Returns each template's id, name, description, and declared\n"
            "parameters (with types, required flags, and defaults). Use the\n"
            "template id with template_run (or playbook_run with template=) to\n"
            "execute a template.\n\n"
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
                    "description": "verbosity: compact | full (default compact)",
                    "default": "compact",
                }
            },
            "required": [],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
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
                required = [
                    n for n, s in params.items() if isinstance(s, dict) and s.get("required")
                ]
                out_templates.append(
                    {
                        "id": t.get("id"),
                        "name": t.get("name"),
                        "description": t.get("description", ""),
                        "required_params": required,
                    }
                )

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
    """Execute a template — thin wrapper around playbook_run."""

    @property
    def name(self) -> str:
        return "template_run"

    @property
    def description(self) -> str:
        return (
            "Execute a template — thin wrapper around playbook_run.\n\n"
            "Templates are playbooks with declared parameters. This tool is a\n"
            "thin wrapper: it resolves the template id, merges flat parameter\n"
            "keys, and delegates to the shared playbook_run execution path.\n\n"
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
        # Validate the template exists
        from kali_mcp.playbooks.registry import get_template

        try:
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

        job_id = _new_id("job")
        assessment_id = _new_id("assessment")

        _, _, run_coro = await _run_template_defn(
            template_id, params, job_id, assessment_id, self.name
        )

        if wants_background:
            from kali_mcp.tools.playbook_blackbox import _run_background

            asyncio.create_task(_run_background(job_id, run_coro))
            payload = {
                "job_id": job_id,
                "assessment_id": assessment_id,
                "template": template_id,
                "target": params.get("target", ""),
                "status": "accepted",
                "next_actions": [
                    "Use job_control or playbook_result with this job_id to poll progress.",
                ],
            }
            result = _success_tool_result(self.name, payload)
            result["template_run"] = payload
            return result

        try:
            res = await run_coro()
        except Exception as e:
            JOB_REGISTRY[job_id]["status"] = "failed"
            JOB_REGISTRY[job_id]["error"] = f"{type(e).__name__}: {e}"
            JOB_REGISTRY[job_id]["finished_at"] = utc_now_iso()
            raise
        res_dict = res if isinstance(res, dict) else {}
        payload = {
            "job_id": job_id,
            "assessment_id": assessment_id,
            "template": template_id,
            "target": params.get("target", ""),
            "status": res.status if hasattr(res, "status") else "completed",
            "summary": res_dict.get("summary") or {},
            "results": res_dict.get("results", []) or [],
            "steps": res_dict.get("steps", []) or [],
            "step_results": res_dict.get("step_results", {}) or {},
            "findings": res_dict.get("findings", []) or [],
            "correlated_findings": res_dict.get("correlated_findings", []) or [],
            "asset_graph": res_dict.get("asset_graph", {}) or {},
            "next_actions": res_dict.get("next_actions", []) or [],
            "execution": res_dict.get("execution", {}) or {},
        }
        result = _success_tool_result(self.name, payload)
        result["template_run"] = payload
        return result
