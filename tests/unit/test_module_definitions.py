"""Unit tests for internal module definitions (modules/**/*.yaml).

Modules are internal building blocks a playbook engine executes; they must
declare a real registered tool, typed inputs, and declared outputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

MODULES_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "kali_mcp" / "playbooks" / "modules"


def _load_modules() -> list[dict]:
    out = []
    for yml in sorted(MODULES_DIR.rglob("*.yaml")):
        with open(yml, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data:
            data["_path"] = str(yml)
            out.append(data)
    return out


ALL_MODULES = _load_modules()


def test_modules_exist():
    assert len(ALL_MODULES) >= 10, (
        f"expected at least 10 module definitions, got {len(ALL_MODULES)}"
    )


def test_module_ids_unique():
    ids = [m["id"] for m in ALL_MODULES]
    assert len(ids) == len(set(ids)), f"duplicate module ids: {sorted(ids)}"


@pytest.mark.parametrize(
    "module", ALL_MODULES, ids=lambda m: m["id"]
)
def test_required_fields(module):
    assert module["id"]
    assert module.get("name"), f"{module['id']}: missing name"
    assert module.get("description"), f"{module['id']}: missing description"
    assert module.get("tool"), f"{module['id']}: missing tool"
    assert int(module.get("timeout", 0)) >= 1, f"{module['id']}: missing timeout"
    assert "inputs" in module, f"{module['id']}: missing inputs"
    assert "outputs" in module, f"{module['id']}: missing outputs"


def test_modules_registered_in_registry():
    from kali_mcp.playbooks import registry as pb_registry

    for module in ALL_MODULES:
        mod = pb_registry.get_module(module["id"])
        assert mod["id"] == module["id"]
        assert mod.get("tool") == module["tool"]


@pytest.mark.parametrize(
    "module", ALL_MODULES, ids=lambda m: m["id"]
)
def test_inputs_are_typed(module):
    for name, spec in (module.get("inputs") or {}).items():
        assert "type" in spec, f"{module['id']}.{name}: input spec missing type"
        assert spec["type"] in (
            "string", "integer", "number", "boolean", "array", "object",
        ), f"{module['id']}.{name}: unknown input type {spec['type']}"


@pytest.mark.parametrize(
    "module", ALL_MODULES, ids=lambda m: m["id"]
)
def test_outputs_are_declared(module):
    outputs = module.get("outputs") or []
    assert isinstance(outputs, list) and outputs, (
        f"{module['id']}: outputs must be a non-empty list"
    )
    for out in outputs:
        assert isinstance(out, str) and out.strip(), (
            f"{module['id']}: output entry must be a non-empty string"
        )


def test_module_tools_are_registered_tools():
    """Every module tool must be an actual registered native tool."""
    from kali_mcp.tools import ALL_TOOLS

    tool_names = {t.name for t in ALL_TOOLS}
    for module in ALL_MODULES:
        tool = module.get("tool")
        assert tool in tool_names, (
            f"{module['id']} references unregistered tool {tool!r}"
        )


def test_module_sensitivity_guardrails():
    """Modules must not run destructive shell patterns by default — only
    read-oriented enumeration commands belong in a safe profile."""
    dangerous_patterns = ("rm -rf", "mkfs", "dd if=", ":(){", "shutdown")
    for module in ALL_MODULES:
        commands = (module.get("default_args") or {}).get("command", "")
        if isinstance(commands, str):
            for pattern in dangerous_patterns:
                assert pattern not in commands, (
                    f"{module['id']}: contains destructive pattern {pattern!r}"
                )
