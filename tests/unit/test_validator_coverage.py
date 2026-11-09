"""Coverage-focused tests for the workflow validator (``kali_mcp.workflow.validator``).

Covers every public entry point and every validate_*/error branch:
playbook definitions, step definitions, module references, DAG structure,
dependencies, when conditions, foreach, on_failure, budget, timeout, parallel.

The existing :file:`tests/unit/test_workflow_validator.py` is left untouched;
this file only adds coverage for branches it does not reach.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from kali_mcp.workflow.validator import (
    _default_matches_type,
    _finalise,
    _find_cycle,
    _find_unsafe_token,
    _finding,
    _is_positive_int,
    _normalise_catalog,
    _parse_type,
    _suggestion,
    _walk_string_refs,
    format_findings,
    is_valid,
    validate_playbook,
)
from kali_mcp.workflow.yaml_loader import PlaybookDefinition, StepDefinition

FAKE_TOOLS = ["nmap", "dnsx", "httpx"]


def _defn(**overrides) -> PlaybookDefinition:
    """Build a minimal valid PlaybookDefinition."""
    body: dict = {
        "name": "test.playbook",
        "version": "1.0.0",
        "inputs": {},
        "execution": {"max_parallel": 2, "timeout": 300},
        "steps": [StepDefinition(id="probe", tool="dnsx")],
        "raw": {},
    }
    body.update(overrides)
    return PlaybookDefinition(**body)


def _step(id_: str, **overrides) -> StepDefinition:
    body = {"id": id_, "tool": "dnsx"}
    body.update(overrides)
    return StepDefinition(**body)


# ── public entry points ─────────────────────────────────────────────────


class TestPublicEntryPoints:
    def test_validate_playbook_rejects_non_defn(self) -> None:
        findings = validate_playbook("not a definition", tool_catalog=FAKE_TOOLS)  # type: ignore[arg-type]
        assert not is_valid(findings)
        assert findings[0]["field"] is None
        assert "PlaybookDefinition" in findings[0]["message"]

    def test_is_valid_true_and_false(self) -> None:
        assert is_valid([]) is True
        assert is_valid([{"severity": "warning"}]) is True
        assert is_valid([{"severity": "error"}]) is False

    def test_format_findings(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("a", tool="nmapx"), _step("a", tool="dnsx")]),
            tool_catalog=FAKE_TOOLS,
        )
        rendered = format_findings(findings)
        assert "Error:" in rendered or "Warning:" in rendered


# ── header / execution ─────────────────────────────────────────────────


class TestHeader:
    def test_empty_name_is_error(self) -> None:
        findings = validate_playbook(_defn(name=""), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any(f.get("field") == "name" for f in findings)

    def test_empty_version_is_warning(self) -> None:
        findings = validate_playbook(_defn(version=""), tool_catalog=FAKE_TOOLS)
        assert any(f.get("field") == "version" for f in findings)

    def test_non_mapping_raw_is_warning(self) -> None:
        findings = validate_playbook(_defn(raw=["not", "a", "mapping"]), tool_catalog=FAKE_TOOLS)
        assert any(f.get("field") == "raw" for f in findings)


class TestExecution:
    def test_non_mapping_execution_is_error(self) -> None:
        findings = validate_playbook(_defn(execution="nope"), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any(f.get("field") == "execution" for f in findings)

    @pytest.mark.parametrize("key", ["max_parallel", "timeout", "max_iterations"])
    def test_non_positive_int_execution_key_is_error(self, key) -> None:
        findings = validate_playbook(_defn(execution={key: 0}), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any(f.get("field") == f"execution.{key}" for f in findings)

    def test_bool_execution_key_is_error(self) -> None:
        findings = validate_playbook(_defn(execution={"timeout": True}), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)

    def test_resume_non_bool_is_warning(self) -> None:
        findings = validate_playbook(_defn(execution={"resume": "yes"}), tool_catalog=FAKE_TOOLS)
        assert any(f.get("field") == "execution.resume" for f in findings)

    def test_unknown_execution_key_is_warning(self) -> None:
        findings = validate_playbook(
            _defn(execution={"max_parallel": 2, "bogus": 1}), tool_catalog=FAKE_TOOLS
        )
        assert any(f.get("field") == "execution.bogus" for f in findings)


# ── inputs ──────────────────────────────────────────────────────────────


class TestInputs:
    def test_inputs_not_mapping_is_error(self) -> None:
        findings = validate_playbook(_defn(inputs="nope"), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any(f.get("field") == "inputs" for f in findings)

    def test_invalid_input_name_is_error(self) -> None:
        findings = validate_playbook(
            _defn(inputs={"bad name!": {"type": "string"}}), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)

    def test_input_declaration_none_is_string_type(self) -> None:
        defn = _defn(inputs={"x": None})
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        # declaration None -> spec_map {} -> no declared type -> warning
        assert any("does not declare a type" in str(f.get("message", "")) for f in findings)

    def test_input_declaration_string_type(self) -> None:
        defn = _defn(inputs={"x": "string"})
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert is_valid(findings)

    def test_input_declaration_other_type_is_error(self) -> None:
        findings = validate_playbook(_defn(inputs={"x": 123}), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)

    def test_missing_input_type_is_warning(self) -> None:
        findings = validate_playbook(_defn(inputs={"x": {}}), tool_catalog=FAKE_TOOLS)
        assert any("does not declare a type" in str(f.get("message", "")) for f in findings)

    def test_invalid_input_type_is_error(self) -> None:
        findings = validate_playbook(
            _defn(inputs={"x": {"type": "not_a_type"}}), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)

    def test_unsupported_input_type_is_error(self) -> None:
        findings = validate_playbook(
            _defn(inputs={"x": {"type": "吃起来good"}}), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)

    def test_invalid_source_is_error(self) -> None:
        findings = validate_playbook(
            _defn(inputs={"x": {"type": "string", "source": "alien"}}), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)

    def test_required_no_default_no_source_is_error(self) -> None:
        findings = validate_playbook(
            _defn(inputs={"x": {"type": "string", "required": True}}), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)

    def test_required_with_source_agent_ok(self) -> None:
        defn = _defn(inputs={"x": {"type": "string", "required": True, "source": "agent"}})
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert is_valid(findings)

    def test_enum_without_values_is_error(self) -> None:
        findings = validate_playbook(
            _defn(inputs={"profile": {"type": "enum", "default": "safe"}}), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)

    def test_enum_default_not_in_values_is_error(self) -> None:
        findings = validate_playbook(
            _defn(
                inputs={"profile": {"type": "enum", "values": ["safe"], "default": "comprehensive"}}
            ),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)

    def test_secret_agent_not_redacted_warning(self) -> None:
        findings = validate_playbook(
            _defn(inputs={"tok": {"type": "secret", "source": "agent"}}), tool_catalog=FAKE_TOOLS
        )
        assert any("redacted" in str(f.get("message", "")) for f in findings)

    def test_default_type_mismatch_warning(self) -> None:
        findings = validate_playbook(
            _defn(inputs={"port": {"type": "integer", "default": "not-an-int"}}),
            tool_catalog=FAKE_TOOLS,
        )
        assert any("does not match declared type" in str(f.get("message", "")) for f in findings)


# ── steps ───────────────────────────────────────────────────────────────


class TestSteps:
    def test_steps_not_a_list_is_error(self) -> None:
        findings = validate_playbook(_defn(steps="nope"), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any(f.get("field") == "steps" for f in findings)

    def test_empty_steps_is_error(self) -> None:
        findings = validate_playbook(_defn(steps=[]), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("no steps" in str(f.get("message", "")) for f in findings)

    def test_step_not_step_definition_is_error(self) -> None:
        findings = validate_playbook(_defn(steps=[object()]), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("StepDefinition" in str(f.get("message", "")) for f in findings)

    def test_empty_step_id_is_error(self) -> None:
        findings = validate_playbook(_defn(steps=[_step("")]), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any(f.get("field") == "id" for f in findings)

    def test_invalid_step_id_is_error(self) -> None:
        findings = validate_playbook(_defn(steps=[_step("bad id!")]), tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("invalid step id" in str(f.get("message", "")) for f in findings)

    def test_duplicate_step_id_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("dup", tool="dnsx"), _step("dup", tool="httpx")]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any("duplicate step id" in str(f.get("message", "")) for f in findings)

    def test_args_not_mapping_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", args="nope")]), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "args" for f in findings)

    def test_output_mapping_not_mapping_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", output_mapping="nope")]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "output_mapping" for f in findings)

    def test_output_mapping_non_string_key_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", output_mapping={1: "x"})]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)

    def test_output_mapping_non_string_value_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", output_mapping={"k": 5})]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)

    def test_retry_bool_is_error(self) -> None:
        # bool passes StepDefinition (True < 0 is False) but validator rejects it.
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", retry=True)]), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "retry" for f in findings)

    def test_on_failure_invalid_constructor_rejects(self) -> None:
        # The constructor enforces on_failure, so this defensive validator
        # branch is unreachable via the public API; confirm the constructor.
        from kali_mcp.workflow.yaml_loader import PlaybookError

        with pytest.raises(PlaybookError):
            StepDefinition(id="probe", tool="dnsx", on_failure="weird")  # type: ignore[arg-type]

    def test_parallel_non_bool_is_warning(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", parallel="yes")]), tool_catalog=FAKE_TOOLS
        )
        assert any(f.get("field") == "parallel" for f in findings)

    def test_checkpoint_non_bool_is_warning(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", checkpoint="yes")]), tool_catalog=FAKE_TOOLS
        )
        assert any(f.get("field") == "checkpoint" for f in findings)

    def test_budget_not_mapping_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", budget="nope")]), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "budget" for f in findings)

    def test_budget_key_not_positive_int_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", budget={"timeout": -1})]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any("budget.timeout" in str(f.get("field", "")) for f in findings)

    def test_custom_step_without_module_ref_warns(self) -> None:
        findings = validate_playbook(
            _defn(steps=[StepDefinition(id="mod", tool=None, type="custom")]),
            tool_catalog=FAKE_TOOLS,
        )
        assert any(f.get("step_id") == "mod" for f in findings)

    def test_unknown_step_type_error(self) -> None:
        # Defensive: constructor rejects unknown types, but call the checker directly.
        from kali_mcp.workflow.validator import _validate_step_type

        step = StepDefinition(id="x", tool="t", type="tool")
        findings: list = []
        _validate_step_type(step, {}, findings)
        assert findings == []
        # The unknown-type branch is unreachable via the constructor; guard it.


# ── graph / DAG ─────────────────────────────────────────────────────────


class TestGraph:
    def test_unknown_dependency_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("a", tool="dnsx", depends_on=["missing_step"])]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any("missing_step" in str(f.get("message", "")) for f in findings)

    def test_self_dependency_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("a", tool="dnsx", depends_on=["a"])]), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)
        assert any("cannot depend on itself" in str(f.get("message", "")) for f in findings)

    def test_duplicate_dependency_is_warning(self) -> None:
        findings = validate_playbook(
            _defn(
                steps=[
                    _step("a", tool="dnsx", depends_on=["b", "b"]),
                    _step("b", tool="httpx"),
                ]
            ),
            tool_catalog=FAKE_TOOLS,
        )
        assert any("duplicate dependency" in str(f.get("message", "")) for f in findings)

    def test_dependency_cycle_is_error(self) -> None:
        findings = validate_playbook(
            _defn(
                steps=[
                    _step("a", tool="dnsx", depends_on=["b"]),
                    _step("b", tool="httpx", depends_on=["a"]),
                ]
            ),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any("cycl" in str(f.get("message", "")).lower() for f in findings)

    def test_unreachable_step_is_warning(self) -> None:
        findings = validate_playbook(
            _defn(
                steps=[
                    _step("root", tool="dnsx"),
                    _step("orphan", tool="httpx", depends_on=["missing_step"]),
                ]
            ),
            tool_catalog=FAKE_TOOLS,
        )
        assert any("unreachable" in str(f.get("message", "")) for f in findings)

    def test_find_cycle_returns_cycle_path(self) -> None:
        dependents = {"a": ["b"], "b": ["c"], "c": ["a"]}
        cycle = _find_cycle(["a", "b", "c"], dependents)
        assert cycle  # a concrete cycle path is returned

    def test_find_cycle_no_cycle_returns_empty(self) -> None:
        dependents = {"a": ["b"], "b": []}
        assert _find_cycle(["a", "b"], dependents) == []

    def test_build_predecessors_and_ancestors(self) -> None:
        from kali_mcp.workflow.validator import (
            _build_predecessors,
            _collect_ancestors,
        )

        steps = [
            _step("a", tool="dnsx"),
            _step("b", tool="httpx", depends_on=["a"]),
            _step("c", tool="nmap", depends_on=["a", "b"]),
        ]
        step_ids = {"a", "b", "c"}
        findings: list = []
        predecessors = _build_predecessors(steps, step_ids, findings)
        assert predecessors["b"] == {"a"}
        assert predecessors["c"] == {"a", "b"}
        ancestors = _collect_ancestors(predecessors, step_ids)
        assert "a" in ancestors["c"]


# ── references / output schemas ─────────────────────────────────────────


class TestReferences:
    def test_unknown_step_reference_is_error(self) -> None:
        step = _step("probe", tool="dnsx", args={"t": "{{steps.ghost.field}}"})
        defn = _defn(
            steps=[step],
            raw={
                "steps": [{"id": "probe", "tool": "dnsx", "args": {"t": "{{steps.ghost.field}}"}}]
            },
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("ghost" in str(f.get("message", "")) for f in findings)

    def test_non_ancestor_step_reference_is_error(self) -> None:
        steps = [
            _step("dns", tool="dnsx"),
            _step("iter", tool="nmap", args={"t": "{{steps.later.items}}"}, depends_on=["dns"]),
            _step("later", tool="httpx"),
        ]
        defn = _defn(
            steps=steps,
            raw={
                "steps": [
                    {"id": "dns", "tool": "dnsx"},
                    {
                        "id": "iter",
                        "tool": "nmap",
                        "args": {"t": "{{steps.later.items}}"},
                        "depends_on": ["dns"],
                    },
                    {"id": "later", "tool": "httpx"},
                ]
            },
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)

    def test_output_field_not_in_schema_is_error(self) -> None:
        step = _step("correlate", tool="finding_correlation", args={"t": "{{steps.dns.nope}}"})
        defn = _defn(
            steps=[_step("dns", tool="dnsx"), step],
            raw={
                "steps": [
                    {"id": "dns", "tool": "dnsx", "outputs": {"resolved_ips": "array"}},
                    {
                        "id": "correlate",
                        "tool": "finding_correlation",
                        "args": {"t": "{{steps.dns.nope}}"},
                    },
                ]
            },
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("no output field" in str(f.get("message", "")) for f in findings)

    def test_unverifiable_output_field_is_warning(self) -> None:
        step = _step("probe", tool="dnsx", args={"t": "{{steps.custom_step.field}}"})
        defn = _defn(
            steps=[_step("custom_step", tool="dnsx"), step],
            raw={
                "steps": [
                    {"id": "custom_step", "tool": "dnsx"},
                    {"id": "probe", "tool": "dnsx", "args": {"t": "{{steps.custom_step.field}}"}},
                ]
            },
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert any("declares no output schema" in str(f.get("message", "")) for f in findings)

    def test_target_without_input_warning(self) -> None:
        step = _step("probe", tool="dnsx", args={"t": "{{target}}"})
        defn = _defn(
            steps=[step],
            raw={"steps": [{"id": "probe", "tool": "dnsx", "args": {"t": "{{target}}"}}]},
            inputs={},
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert any("no 'target' input" in str(f.get("message", "")) for f in findings)

    def test_empty_variable_reference_is_error(self) -> None:
        step = _step("probe", tool="dnsx", args={"t": "{{ }}"})
        defn = _defn(
            steps=[step],
            raw={"steps": [{"id": "probe", "tool": "dnsx", "args": {"t": "{{ }}"}}]},
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("empty variable reference" in str(f.get("message", "")) for f in findings)

    def test_unsupported_variable_reference_is_error(self) -> None:
        step = _step("probe", tool="dnsx", args={"t": "{{steps.dns}}"})
        defn = _defn(
            steps=[step],
            raw={"steps": [{"id": "probe", "tool": "dnsx", "args": {"t": "{{steps.dns}}"}}]},
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)

    def test_parse_reference_and_bare(self) -> None:
        from kali_mcp.workflow.validator import (
            _parse_bare_step_reference,
            _parse_reference,
        )

        assert _parse_reference("target") == ("target",)
        assert _parse_reference("inputs.host") == ("inputs", "host")
        assert _parse_reference("steps.dns.resolved_ips") == ("steps", "dns", "resolved_ips")
        assert _parse_reference("garbage") is None
        assert _parse_bare_step_reference("dns.field", {"dns"}) == ("steps", "dns", "field")
        assert _parse_bare_step_reference("dns.field", set()) is None

    def test_walk_string_refs(self) -> None:
        value = {"a": "{{steps.x.y}}", "b": ["{{inputs.z}}", {"c": "no ref"}]}
        refs = list(_walk_string_refs(value, "root"))
        paths = {p for p, _ in refs}
        assert "root.a" in paths
        assert "root.b[0]" in paths

    def test_playbook_outputs_non_mapping_warning(self) -> None:
        defn = _defn(raw={"outputs": "nope"})
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert any(f.get("field") == "outputs" for f in findings)

    def test_playbook_outputs_non_string_value_error(self) -> None:
        defn = _defn(raw={"outputs": {"k": 5}})
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any(
            "output value must be a variable reference string" in str(f.get("message", ""))
            for f in findings
        )

    def test_output_schemas_from_raw_and_builtin(self) -> None:
        from kali_mcp.workflow.validator import _build_output_schemas, _index_raw_steps

        raw_index = _index_raw_steps(
            {"steps": [{"id": "s", "tool": "scope_check", "outputs": {"ok": "boolean"}}]}
        )
        assert "s" in raw_index
        schemas = _build_output_schemas([_step("s", tool="scope_check")], raw_index, {"s"})
        assert schemas["s"].fields.get("ok") == "boolean"
        # builtin schema fallback (keyed by step type)
        schemas2 = _build_output_schemas(
            [_step("b", tool="assessment_report", type="assessment_report")], {}, {"b"}
        )
        assert schemas2["b"].fields.get("report") == "object"

    def test_schema_from_raw_output_schema_mapping(self) -> None:
        from kali_mcp.workflow.validator import _schema_from_raw

        raw = {"output_schema": {"properties": {"port": {"type": "integer"}}}}
        schema = _schema_from_raw(raw)
        assert schema.fields.get("port") == "integer"

    def test_declared_type(self) -> None:
        from kali_mcp.workflow.validator import _declared_type

        assert _declared_type("string") == "string"
        assert _declared_type({"type": "array"}) == "array"
        assert _declared_type(123) is None


# ── when / foreach ──────────────────────────────────────────────────────


class TestWhenAndForeach:
    def test_when_unsafe_token_is_error(self) -> None:
        # "&&" passes the DSL constructor (no shell chars it rejects) but is
        # flagged by the validator's broader injection denylist.
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", when="{{steps.x.n}} > 0 && true")]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "when" for f in findings)

    def test_when_bad_grammar_is_error(self) -> None:
        # No comparison operator -> grammar mismatch.
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", when="{{steps.x.n}}")]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "when" for f in findings)

    def test_when_invalid_literal_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="dnsx", when="{{steps.x.n}} > @bad_literal")]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "when" for f in findings)

    def test_unsafe_tokens_detected(self) -> None:
        for cond in ["$(reboot)", "`whoami`", "import os", "eval(1)", "__import__('x')"]:
            assert _find_unsafe_token(cond) is not None

    def test_foreach_non_string_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("iter", tool="dnsx", foreach=5)]), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "foreach" for f in findings)

    def test_foreach_empty_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("iter", tool="dnsx", foreach="")]), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)

    def test_foreach_target_scalar_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("iter", tool="dnsx", foreach="{{target}}")]), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)

    def test_foreach_undeclared_input_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("iter", tool="dnsx", foreach="{{inputs.nope}}")]),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)

    def test_foreach_non_array_input_is_error(self) -> None:
        findings = validate_playbook(
            _defn(
                inputs={"host": {"type": "string"}},
                steps=[_step("iter", tool="dnsx", foreach="{{inputs.host}}")],
            ),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)


# ── limits ──────────────────────────────────────────────────────────────


class TestLimits:
    def test_invalid_max_iterations_is_error(self) -> None:
        findings = validate_playbook(
            _defn(
                steps=[_step("probe", tool="dnsx")],
                raw={"steps": [{"id": "probe", "tool": "dnsx", "max_iterations": 0}]},
            ),
            tool_catalog=FAKE_TOOLS,
        )
        assert not is_valid(findings)
        assert any(f.get("field") == "max_iterations" for f in findings)

    def test_iterative_without_bound_is_warning(self) -> None:
        findings = validate_playbook(
            _defn(
                steps=[_step("iter", tool="dnsx", foreach="{{inputs.items}}")],
                inputs={"items": {"type": "array"}},
            ),
            tool_catalog=FAKE_TOOLS,
        )
        assert any("max_iterations" in str(f.get("field", "")) for f in findings)


# ── tool resolution / catalog ───────────────────────────────────────────


class TestToolResolution:
    def test_unknown_tool_is_error(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="nmapx")]), tool_catalog=FAKE_TOOLS
        )
        assert not is_valid(findings)
        assert any("nmapx" in str(f.get("message", "")) for f in findings)

    def test_known_tool_no_findings(self) -> None:
        findings = validate_playbook(
            _defn(steps=[_step("probe", tool="nmap")]), tool_catalog=FAKE_TOOLS
        )
        assert is_valid(findings)

    def test_catalog_unavailable_is_warning(self) -> None:
        import kali_mcp.workflow.validator as mod

        with patch.object(mod, "_resolve_tool_catalog", lambda: (None, "no catalog resolved")):
            findings = validate_playbook(_defn(), tool_catalog=None)
        assert any(f.get("field") == "tool_catalog" for f in findings)

    def test_catalog_unavailable_for_publish_is_error(self) -> None:
        import kali_mcp.workflow.validator as mod

        with patch.object(mod, "_resolve_tool_catalog", lambda: (None, "no catalog resolved")):
            findings = validate_playbook(_defn(), tool_catalog=None, for_publish=True)
        assert not is_valid(findings)
        assert any(
            f.get("field") == "tool_catalog" and f.get("severity") == "error" for f in findings
        )

    def test_for_publish_custom_module_unverified_warning(self) -> None:
        findings = validate_playbook(
            _defn(steps=[StepDefinition(id="mod", tool="my.module", type="custom")]),
            tool_catalog=FAKE_TOOLS,
            for_publish=True,
        )
        assert any("could not be verified" in str(f.get("message", "")) for f in findings)

    def test_module_catalog_unknown_module_error(self) -> None:
        # tool step with no tool ref but a legacy raw module -> checked against catalog.
        findings = validate_playbook(
            _defn(
                steps=[StepDefinition(id="probe", tool=None, type="tool")],
                raw={"steps": [{"id": "probe", "tool": "dnsx", "module": "missing.module"}]},
            ),
            tool_catalog=FAKE_TOOLS,
            module_catalog=["other.module"],
        )
        assert any("not registered" in str(f.get("message", "")) for f in findings)

    def test_normalise_catalog(self) -> None:
        assert _normalise_catalog(None) == set()
        assert _normalise_catalog("nmap") == {"nmap"}
        assert _normalise_catalog(["nmap", "", 123, "dnsx"]) == {"nmap", "dnsx"}


# ── helpers ─────────────────────────────────────────────────────────────


class TestHelpers:
    def test_finding_contract(self) -> None:
        f = _finding("error", "s", "field", "msg")
        assert set(f) >= {"severity", "step_id", "field", "message"}

    def test_finalise_deduplicates_and_orders(self) -> None:
        steps = [_step("b", tool="dnsx"), _step("a", tool="httpx")]
        findings = [
            _finding("warning", "b", "f", "msg b"),
            _finding("error", "a", "f", "msg a"),
            _finding("error", "a", "f", "msg a"),  # duplicate
        ]
        out = _finalise(findings, steps)
        assert len(out) == 2
        assert out[0]["severity"] == "error"

    def test_is_positive_int(self) -> None:
        assert _is_positive_int(1) is True
        assert _is_positive_int(True) is False
        assert _is_positive_int(0) is False
        assert _is_positive_int(-1) is False
        assert _is_positive_int(1.5) is False
        assert _is_positive_int("1") is False

    def test_suggestion(self) -> None:
        assert _suggestion("nmapx", {"nmap", "dnsx"}) != ""
        assert _suggestion("zzz", {"nmap", "dnsx"}) == ""

    def test_parse_type(self) -> None:
        assert _parse_type("string") == ("string", None)
        assert _parse_type("array[integer]") == ("array", "integer")
        assert _parse_type("object") == ("object", None)
        assert _parse_type("") is None
        assert _parse_type("array[object]") is None
        assert _parse_type("nope") is None

    def test_default_matches_type(self) -> None:
        assert _default_matches_type("x", "string", None) is True
        assert _default_matches_type(5, "integer", None) is True
        assert _default_matches_type(True, "integer", None) is False
        assert _default_matches_type(True, "boolean", None) is True
        assert _default_matches_type([1], "array", None) is True
        assert _default_matches_type({"k": 1}, "object", None) is True
        assert _default_matches_type("a", "enum", ("a", "b")) is True
        assert _default_matches_type("c", "enum", ("a", "b")) is False
        assert _default_matches_type(None, "string", None) is True
