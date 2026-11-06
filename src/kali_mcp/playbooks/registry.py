"""Internal playbook and module registry.

Playbooks (agent-visible) and modules (internal) are registered here.
The playbook engine resolves dependencies and executes modules in order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PLAYBOOKS_DIR = Path(__file__).parent / "definitions"
TEMPLATES_DIR = Path(__file__).parent / "templates"

_playbooks: dict[str, dict[str, Any]] = {}
_modules: dict[str, dict[str, Any]] = {}
_templates: dict[str, dict[str, Any]] = {}


class PlaybookNotFound(KeyError):
    pass


class ModuleNotFound(KeyError):
    pass


class TemplateNotFound(KeyError):
    pass


def register_playbook(pb_id: str, definition: dict[str, Any]) -> None:
    _playbooks[pb_id] = definition


def register_module(mod_id: str, definition: dict[str, Any]) -> None:
    _modules[mod_id] = definition


def get_playbook(pb_id: str) -> dict[str, Any]:
    if pb_id not in _playbooks:
        raise PlaybookNotFound(f"Playbook not found: {pb_id}")
    return _playbooks[pb_id]


def get_module(mod_id: str) -> dict[str, Any]:
    if mod_id not in _modules:
        raise ModuleNotFound(f"Module not found: {mod_id}")
    return _modules[mod_id]


def list_playbooks() -> list[dict[str, Any]]:
    out = []
    for pb_id, pb in _playbooks.items():
        out.append({
            "id": pb_id,
            "name": pb.get("name", pb_id),
            "description": pb.get("description", ""),
            "inputs": pb.get("inputs", {}),
            "outputs": pb.get("outputs", {}),
            "estimated_duration": pb.get("execution", {}).get("timeout", 300),
        })
    return out


def load_yaml_playbooks() -> None:
    """Load all YAML playbook definitions from the definitions directory."""
    if not PLAYBOOKS_DIR.exists():
        return
    for yml in sorted(PLAYBOOKS_DIR.glob("*.yaml")):
        with open(yml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "id" in data:
            register_playbook(data["id"], data)


def load_yaml_modules() -> None:
    """Load all YAML module definitions from the modules directory tree."""
    modules_dir = Path(__file__).parent / "modules"
    if not modules_dir.exists():
        return
    for yml in sorted(modules_dir.rglob("*.yaml")):
        with open(yml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "id" in data:
            register_module(data["id"], data)


_TEMPLATABLE_PARAM_TOKEN = r"\{\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}\}"


def register_template(tmp_id: str, definition: dict[str, Any]) -> None:
    _templates[tmp_id] = definition


def get_template(template_id: str) -> dict[str, Any]:
    if template_id not in _templates:
        raise TemplateNotFound(f"Template not found: {template_id}")
    return _templates[template_id]


def list_templates() -> list[dict[str, Any]]:
    out = []
    for tmp_id, tmp in _templates.items():
        params = tmp.get("parameters", {}) or {}
        out.append({
            "id": tmp_id,
            "name": tmp.get("name", tmp_id),
            "description": tmp.get("description", ""),
            "parameters": {
                name: {
                    "type": spec.get("type", "string"),
                    "description": spec.get("description", ""),
                    "required": bool(spec.get("required", False)),
                    "default": spec.get("default"),
                }
                for name, spec in params.items()
            },
        })
    return out


def load_yaml_templates() -> None:
    """Load all YAML template definitions from the templates directory."""
    if not TEMPLATES_DIR.exists():
        return
    for yml in sorted(TEMPLATES_DIR.glob("*.yaml")):
        with open(yml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "id" in data:
            register_template(data["id"], data)


def _merge_params(
    template: dict[str, Any], params: dict[str, Any]
) -> dict[str, Any]:
    """Merge user params over template defaults and validate requirements.

    Missing required parameters raise TemplateNotFound (ValueError subclass
    of KeyError but validated at tool layer with a clear message).
    """
    resolved: dict[str, Any] = {}
    for name, spec in (template.get("parameters", {}) or {}).items():
        if name in params and params[name] is not None:
            resolved[name] = params[name]
        elif spec.get("default") is not None:
            resolved[name] = spec["default"]
        elif spec.get("required"):
            raise TemplateNotFound(f"Template parameter is required: {name}")
        else:
            resolved[name] = None
    # Extra user params beyond declared ones are kept (useful for step args)
    for name, value in params.items():
        if name not in resolved:
            resolved[name] = value
    return resolved


def render_template(template_id: str, params: dict[str, Any] | None = None) -> Any:
    """Instantiate a template into a validated workflow-engine PlaybookDefinition.

    ``{{param}}`` tokens referencing resolved template parameters are replaced
    with their values. Tokens that resolve to typed values (int/list/object)
    replace the whole string; token fragments inside longer strings are
    substituted textually. The result is parsed/validated with the
    workflow engine's yaml_loader so steps are executable immediately.
    """
    import re

    template = get_template(template_id)
    params = params or {}
    resolved = _merge_params(template, params)

    def substitute(value: Any) -> Any:
        if isinstance(value, str):
            spans = re.findall(_TEMPLATABLE_PARAM_TOKEN, value)
            if not spans:
                return value
            # Full-string token: replace with the typed parameter value
            if value.strip() == "{{" + spans[0] + "}}" and len(spans) == 1:
                return resolved.get(spans[0], "")
            # Embedded token: substitute textually
            for token in spans:
                value = value.replace(
                    "{{" + token + "}}", str(resolved.get(token, ""))
                )
            return value
        if isinstance(value, dict):
            return {k: substitute(v) for k, v in value.items()}
        if isinstance(value, list):
            return [substitute(v) for v in value]
        return value

    rendered = substitute(dict(template.get("playbook_definition", {}) or {}))
    rendered["name"] = rendered.get("name") or template_id

    from kali_mcp.workflow.yaml_loader import load_playbook

    return load_playbook(rendered)


# Auto-load YAML playbook and module definitions on import so the registry
# is populated whenever the playbook package is used.
_load_yaml_done = False


def _ensure_loaded() -> None:
    global _load_yaml_done
    if not _load_yaml_done:
        load_yaml_playbooks()
        load_yaml_modules()
        load_yaml_templates()
        _load_yaml_done = True


_ensure_loaded()
