"""Unit tests for assessment templates (templates/*.yaml).

Covers the template loader, parameter merging/validation, rendering into a
workflow-engine PlaybookDefinition, and each bundled template.
"""

from __future__ import annotations

import pytest

from kmcp.playbooks.registry import (
    TemplateNotFound,
    _templates,
    get_template,
    list_templates,
    load_yaml_templates,
    register_template,
    render_template,
)


def test_templates_loaded_from_yaml():
    load_yaml_templates()
    ids = set(_templates.keys())
    assert {
        "quick_web_scan",
        "comprehensive_external",
        "compliance_audit",
        "incident_response",
    } <= ids, f"missing bundled templates; got {sorted(ids)}"


def test_template_ids_unique_in_dir():
    load_yaml_templates()
    assert len(_templates) == len({t.get("id") for t in _templates.values()})


@pytest.mark.parametrize(
    "template_id",
    ["quick_web_scan", "comprehensive_external", "compliance_audit", "incident_response"],
)
def test_each_bundled_template_has_metadata(template_id):
    tpl = get_template(template_id)
    assert tpl.get("name"), f"{template_id}: missing name"
    assert tpl.get("description"), f"{template_id}: missing description"
    params = tpl.get("parameters") or {}
    assert params, f"{template_id}: missing parameters"
    for pname, spec in params.items():
        assert "type" in spec, f"{template_id}.{pname}: parameter spec missing type"
    # A template must embed a playbook definition to render against
    pbd = tpl.get("playbook_definition") or {}
    assert pbd.get("steps"), f"{template_id}: playbook_definition has no steps"


def test_list_templates_shape():
    templates = list_templates()
    assert len(templates) >= 4
    for t in templates:
        assert set(t) >= {"id", "name", "description", "parameters"}
        for spec in t["parameters"].values():
            assert set(spec) >= {"type", "description", "required"}


def test_register_and_get_template():
    register_template(
        "test_tpl",
        {
            "id": "test_tpl",
            "name": "T",
            "description": "d",
            "parameters": {},
            "playbook_definition": {"name": "t", "steps": []},
        },
    )
    assert get_template("test_tpl")["id"] == "test_tpl"


def test_get_template_not_found():
    with pytest.raises(TemplateNotFound):
        get_template("no_such_template_xyz")


def test_render_missing_required_param_raises():
    with pytest.raises(TemplateNotFound, match="target"):
        render_template("quick_web_scan", {})


def test_render_resolves_required_param():
    pb = render_template("quick_web_scan", {"target": "render.test"})
    rendered_args = [s.args.get("target") for s in pb.steps if s.args and "target" in s.args]
    assert rendered_args, "no step received the rendered target"
    assert all(t == "render.test" for t in rendered_args)


def test_render_applies_default_params():
    pb = render_template("quick_web_scan", {"target": "render.test"})
    # depth defaults to shallow; scope_check step must reference the target
    validate_step = pb.steps[0]
    assert validate_step.type == "scope_check"
    assert validate_step.args["target"] == "render.test"


def test_render_explicit_override_wins_over_default():
    pb = render_template("quick_web_scan", {"target": "render.test", "depth": "deep"})
    assert pb.inputs.get("depth") == "deep"


def test_render_produces_workflow_definition():
    from kmcp.workflow.yaml_loader import PlaybookDefinition

    pb = render_template("quick_web_scan", {"target": "render.test"})
    assert isinstance(pb, PlaybookDefinition)
    assert pb.name == "quick_web_scan"
    assert pb.max_parallel >= 1
    assert pb.timeout >= 60


def test_render_incident_response_list_default():
    """Array-typed defaults render as actual lists (not the string '[]')."""
    tpl = get_template("incident_response")
    assert tpl["parameters"]["finding_ids"].get("default") == []
    pb = render_template("incident_response", {"target": "render.test"})
    recheck = [s for s in pb.steps if s.id == "finding_recheck"]
    assert recheck and recheck[0].args.get("finding_ids") == []


def test_render_full_token_replaces_typed_value():
    """`{{param}}` as a complete string swaps in the typed value; embedded
    tokens are substituted textually."""
    register_template(
        "test_typed",
        {
            "id": "test_typed",
            "name": "T",
            "description": "d",
            "parameters": {
                "target": {"type": "string", "required": True},
                "flags": {"type": "array", "default": ["-x", "-y"]},
            },
            "playbook_definition": {
                "name": "test_typed",
                "steps": [
                    {
                        "id": "probe",
                        "type": "scope_check",
                        "depends_on": [],
                        "args": {
                            "target": "{{target}}",
                            "flags": "{{flags}}",
                            "note": "scan {{target}} now",
                        },
                    }
                ],
            },
        },
    )
    pb = render_template("test_typed", {"target": "h1"})
    step = pb.steps[0]
    assert step.args["flags"] == ["-x", "-y"]
    assert step.args["note"] == "scan h1 now"


def test_render_unknown_template_raises():
    with pytest.raises(TemplateNotFound):
        render_template("no_such_template_xyz", {"target": "x"})
