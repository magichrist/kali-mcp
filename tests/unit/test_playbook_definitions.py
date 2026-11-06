"""Unit tests for the black-box playbook definitions (definitions/*.yaml).

Validates every agent-facing playbook definition: schema, module references,
DAG integrity (no unresolvable dependencies or cycles), and black-box
contract (no raw tool names leak into the module step entries).
"""

from __future__ import annotations

import os

import pytest
import yaml

from kali_mcp.playbooks import registry as pb_registry
from kali_mcp.playbooks.engine import PlaybookEngine

DEFINITIONS_DIR = os.path.join(os.path.dirname(pb_registry.__file__), "definitions")


def _load_definitions() -> list[dict]:
    out = []
    for fn in sorted(os.listdir(DEFINITIONS_DIR)):
        if fn.endswith(".yaml"):
            with open(os.path.join(DEFINITIONS_DIR, fn), "r", encoding="utf-8") as f:
                out.append(yaml.safe_load(f))
    return out


ALL_DEFINITIONS = _load_definitions()


def test_definitions_exist():
    assert len(ALL_DEFINITIONS) >= 6, (
        f"expected at least 6 playbook definitions, got {len(ALL_DEFINITIONS)}"
    )


@pytest.mark.parametrize(
    "definition", ALL_DEFINITIONS, ids=lambda d: d["id"]
)
def test_required_fields(definition):
    assert definition["id"]
    assert definition.get("name"), f"{definition['id']}: missing name"
    assert definition.get("description"), f"{definition['id']}: missing description"
    assert "version" in definition, f"{definition['id']}: missing version"
    assert "inputs" in definition, f"{definition['id']}: missing inputs"
    assert "execution" in definition, f"{definition['id']}: missing execution"
    assert "steps" in definition, f"{definition['id']}: missing steps"

    execution = definition["execution"]
    assert int(execution.get("max_parallel", 0)) >= 1
    assert int(execution.get("timeout", 0)) >= 60


def test_definition_ids_unique():
    ids = [d["id"] for d in ALL_DEFINITIONS]
    assert len(ids) == len(set(ids)), f"duplicate playbook ids: {sorted(ids)}"


@pytest.mark.parametrize(
    "definition", ALL_DEFINITIONS, ids=lambda d: d["id"]
)
def test_first_step_is_scope_check(definition):
    first = definition["steps"][0]
    assert first.get("type") == "scope_check", (
        f"{definition['id']}: first step must be scope_check, "
        f"got {first.get('type')}"
    )


@pytest.mark.parametrize(
    "definition", ALL_DEFINITIONS, ids=lambda d: d["id"]
)
def test_module_steps_reference_registered_modules(definition):
    """Every module: step must exist in the module registry (black-box wiring)."""
    pb_registry._ensure_loaded()
    for step in definition["steps"]:
        mod_id = step.get("module")
        if mod_id is not None:
            assert mod_id in pb_registry._modules, (
                f"{definition['id']}: step {step['id']} references unknown "
                f"module {mod_id}"
            )


@pytest.mark.parametrize(
    "definition", ALL_DEFINITIONS, ids=lambda d: d["id"]
)
def test_step_depends_on_resolvable(definition):
    steps = definition["steps"]
    step_ids = [s["id"] for s in steps]
    assert len(step_ids) == len(set(step_ids)), (
        f"{definition['id']}: duplicate step ids"
    )
    for step in steps:
        for dep in step.get("depends_on", []) or []:
            assert dep in step_ids, (
                f"{definition['id']}: step {step['id']} depends on unknown "
                f"step {dep}"
            )


@pytest.mark.parametrize(
    "definition", ALL_DEFINITIONS, ids=lambda d: d["id"]
)
def test_topological_sort_resolves_dag(definition):
    """The playbook engine's DAG sort must terminate for every definition."""
    engine = PlaybookEngine()
    order = engine._topological_sort(definition["steps"])
    assert sorted(order) == list(range(len(definition["steps"])))
    assert len(order) == len(definition["steps"])


def test_definitions_in_registry():
    pb_registry._ensure_loaded()
    for d in ALL_DEFINITIONS:
        pb = pb_registry.get_playbook(d["id"])
        assert pb["id"] == d["id"]
        assert pb.get("steps"), f"{d['id']}: registered definition has no steps"


@pytest.mark.parametrize(
    "definition", ALL_DEFINITIONS, ids=lambda d: d["id"]
)
def test_at_least_one_correlation_and_report(definition):
    types = {s.get("type") for s in definition["steps"]}
    assert "finding_correlation" in types, (
        f"{definition['id']}: missing finding_correlation step"
    )
    assert "assessment_report" in types, (
        f"{definition['id']}: missing assessment_report step"
    )


@pytest.mark.parametrize(
    "definition", ALL_DEFINITIONS, ids=lambda d: d["id"]
)
def test_black_box_metadata_only(definition):
    """Playbook definitions must not declare raw tool names at the playbook
    level — tools are the modules' concern (black-box contract). Only applies
    to module-based (black-box) playbooks; YAML playbooks that legitimately
    use ``type: tool`` steps are exempt.
    """
    for step in definition["steps"]:
        if step.get("module"):
            assert not step.get("tool"), (
                f"{definition['id']}: module-based steps must not also declare tools "
                f"(offender: {step['id']} -> {step['tool']})"
            )
