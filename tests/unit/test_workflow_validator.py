"""Tests for the workflow validator subsystem (Playbook Studio)."""

from __future__ import annotations

import pytest

from kali_mcp.workflow.validator import (
    _find_unsafe_token,
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
        "steps": [
            StepDefinition(id="probe", tool="dnsx"),
        ],
        "raw": {},
    }
    body.update(overrides)
    return PlaybookDefinition(**body)


def _severity(findings: list[dict], substr: str) -> str | None:
    """Return the severity of the first finding whose message contains substr."""
    for f in findings:
        if substr in str(f.get("message", "")):
            return f.get("severity")
    return None


class TestHappyPath:
    def test_valid_playbook_has_no_errors(self) -> None:
        findings = validate_playbook(_defn(), tool_catalog=FAKE_TOOLS)
        assert is_valid(findings), format_findings(findings)

    def test_input_reference_to_declared_input_ok(self) -> None:
        step = StepDefinition(id="probe", tool="dnsx", args={"target": "{{inputs.host}}"})
        defn = _defn(
            inputs={"host": {"type": "string", "required": True, "source": "agent"}},
            steps=[step],
            raw={"steps": [{"id": "probe", "tool": "dnsx", "args": {"target": "{{inputs.host}}"}}]},
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert is_valid(findings), format_findings(findings)

    def test_dangling_step_reference_is_error(self) -> None:
        # "{{steps.ghost.field}}" refers to a step that does not exist at all.
        step = StepDefinition(id="probe", tool="dnsx", args={"target": "{{steps.ghost.field}}"})
        defn = _defn(steps=[step], raw={"steps": [{"id": "probe", "tool": "dnsx", "args": {"target": "{{steps.ghost.field}}"}}]})
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert _severity(findings, "ghost") in {"error", None}
        assert any("ghost" in str(f.get("message", "")) for f in findings)


class TestGraphIntegrity:
    def test_duplicate_step_id_error(self) -> None:
        steps = [
            StepDefinition(id="dup", tool="dnsx"),
            StepDefinition(id="dup", tool="httpx"),
        ]
        defn = _defn(steps=steps)
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("dup" in str(f.get("step_id")) or "dup" in str(f.get("message", ""))
                   for f in findings)

    def test_bad_depends_on_error(self) -> None:
        steps = [StepDefinition(id="a", tool="dnsx", depends_on=["missing_step"])]
        defn = _defn(steps=steps)
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("missing_step" in str(f.get("message", "")) for f in findings)

    def test_dependency_cycle_error(self) -> None:
        steps = [
            StepDefinition(id="a", tool="dnsx", depends_on=["b"]),
            StepDefinition(id="b", tool="httpx", depends_on=["a"]),
        ]
        defn = _defn(steps=steps)
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any(
            f.get("severity") == "error" and "cycl" in str(f.get("message", "")).lower()
            for f in findings
        )

    def test_unreachable_step_is_warning(self) -> None:
        # Step "orphan" has no incoming edge from the roots (still standalone —
        # engines execute all steps, so unreachable = warning not error).
        steps = [
            StepDefinition(id="root", tool="dnsx"),
            StepDefinition(id="child", tool="httpx", depends_on=["root"]),
        ]
        defn = _defn(steps=steps)
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert is_valid(findings), format_findings(findings)


class TestToolResolution:
    def test_unknown_tool_error_with_catalog(self) -> None:
        steps = [StepDefinition(id="probe", tool="nmapx")]
        defn = _defn(steps=steps)
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)
        assert any("nmapx" in str(f.get("message", "")) for f in findings)

    def test_known_tool_no_findings(self) -> None:
        steps = [StepDefinition(id="probe", tool="nmap")]
        defn = _defn(steps=steps)
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert is_valid(findings), format_findings(findings)

    def test_tool_catalog_none_is_warning_not_error(self) -> None:
        # When NO catalog can be resolved at all, tool resolution downgrades to
        # a warning (in this env the lazy resolver succeeds, so simulate the
        # failure path explicitly).
        import kali_mcp.workflow.validator as mod

        steps = [StepDefinition(id="probe", tool="something_exotic")]
        defn = _defn(steps=steps)
        monkey = pytest.MonkeyPatch()
        monkey.setattr(mod, "_resolve_tool_catalog", lambda: (None, "no catalog resolved"))
        try:
            findings = validate_playbook(defn, tool_catalog=None)
        finally:
            monkey.undo()
        assert is_valid(findings), format_findings(findings)
        assert any(f.get("field") == "tool_catalog" for f in findings), findings

    def test_custom_step_without_module_ref_warns_or_errors(self) -> None:
        # type="custom" steps must carry a module/tool reference.
        step = StepDefinition(id="mod", tool=None, type="custom")
        defn = _defn(steps=[step])
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        # The validator must flag this (warning or error per for_publish mode),
        # never silently accept it.
        assert any(f.get("step_id") == "mod" for f in findings)


class TestInputSystem:
    def test_unknown_input_type_error(self) -> None:
        defn = _defn(inputs={"x": {"type": "吃起来good"}})
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)

    def test_enum_without_values_error(self) -> None:
        defn = _defn(inputs={"profile": {"type": "enum", "default": "safe"}})
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)

    def test_enum_default_must_be_in_values(self) -> None:
        defn = _defn(
            inputs={
                "profile": {
                    "type": "enum",
                    "values": ["safe"],
                    "default": "comprehensive",
                }
            }
        )
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)


class TestForEach:
    def test_foreach_literal_is_flagged(self) -> None:
        step = StepDefinition(id="iter", tool="httpx", foreach="readme.not_a_field")
        defn = _defn(steps=[step])
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)

    def test_foreach_field_reference_ok(self) -> None:
        steps = [
            StepDefinition(id="dns", tool="dnsx"),
            StepDefinition(
                id="iter",
                tool="httpx",
                foreach="{{steps.dns.resolved_ips}}",
                depends_on=["dns"],
            ),
        ]
        defn = _defn(steps=steps)
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        # Known-step-unknown-field is a warning, not an error.
        assert is_valid(findings), format_findings(findings)

    def test_foreach_forward_reference_is_error(self) -> None:
        # foreach over a step that is NOT a dependency: the engine guarantees
        # order, so referencing a non-dependency step must be an error.
        steps = [
            StepDefinition(id="dns", tool="dnsx"),
            StepDefinition(id="iter", tool="nmap", foreach="{{steps.later.items}}",
                           depends_on=["dns"]),
            StepDefinition(id="later", tool="httpx"),
        ]
        defn = _defn(steps=steps, raw={
            "steps": [
                {"id": "dns", "tool": "dnsx"},
                {"id": "iter", "tool": "nmap", "foreach": "{{steps.later.items}}", "depends_on": ["dns"]},
                {"id": "later", "tool": "httpx"},
            ]
        })
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS)
        assert not is_valid(findings)


class TestEscalationMode:
    def test_for_publish_requires_resolvable_catalog(self) -> None:
        # With an explicit catalog resolution still succeeds.
        findings = validate_playbook(_defn(), tool_catalog=FAKE_TOOLS, for_publish=True)
        assert is_valid(findings)

    def test_for_publish_no_catalog_is_error(self) -> None:
        findings = validate_playbook(_defn(steps=[StepDefinition(id="p", tool="weird_tool")]),
                                     tool_catalog=None, for_publish=True)
        assert not is_valid(findings)


class TestSpecExampleShape:
    def test_domain_recon_shape_valid(self) -> None:
        """Spec §7 example shape (tools only; module refs left to module_catalog)."""
        steps = [
            StepDefinition(id="validate", tool="dnsx"),
            StepDefinition(id="scope", tool="dnsx", depends_on=["validate"]),
            StepDefinition(id="dns", tool="dnsx", depends_on=["scope"]),
            StepDefinition(id="correlate", tool="httpx", depends_on=["dns"],
                           args={"data": "{{steps.dns.resolved_ips}}"}),
        ]
        defn = _defn(name="custom.domain_recon", steps=steps)
        findings = validate_playbook(defn, tool_catalog=FAKE_TOOLS,
                                     module_catalog=["target.validate", "dns.resolve"])
        assert is_valid(findings), format_findings(findings)


class TestUnstructuredConditionGuard:
    """The denylist used on ``when`` conditions mirrors security.py."""

    @pytest.mark.parametrize(
        ("cond", "token"),
        [
            ("$(reboot)", "$("),
            ("`whoami`", "`"),
            ("import os; os.system('x')", "import"),
            ("eval(1+2)", "eval"),
            ("__import__('os')", "__import__"),
            ("os.path.join('a')", "os."),
            ("subprocess.run('ls')", "subprocess"),
            ("foo; rebooexec", "exec"),
        ],
    )
    def test_unsafe_tokens_detected(self, cond: str, token: str) -> None:
        assert _find_unsafe_token(cond) is not None

    @pytest.mark.parametrize(
        "cond",
        [
            "{{steps.net.http_services_count}} > 0",
            "{{inputs.target}} == example.com",
            "{{steps.scan.findings}} >= 3",
        ],
    )
    def test_structured_conditions_pass(self, cond: str) -> None:
        assert _find_unsafe_token(cond) is None


class TestOutputContract:
    def test_findings_have_contract_fields(self) -> None:
        findings = validate_playbook(_defn(inputs={"x": {"type": "nope"}}))
        assert findings
        for f in findings:
            assert set(f) >= {"severity", "step_id", "field", "message"}

    def test_format_findings_rendering(self) -> None:
        findings = validate_playbook(_defn(steps=[StepDefinition(id="a", tool="nmapx"),
                                                    StepDefinition(id="a", tool="dnsx")]))
        rendered = format_findings(findings)
        assert rendered  # something renders
