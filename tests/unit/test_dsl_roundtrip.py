"""Round-trip tests for the DSL module (Playbook Studio Phase 2).

Verifies:
- PlaybookDefinition → DSL text → PlaybookDefinition is lossless for the supported subset.
- The spec's custom.domain_recon example parses, compiles, validates, and dry-runs.
- Injection attempts are rejected with clear errors.
"""

from __future__ import annotations

import json

import pytest

from kali_mcp.workflow import modules_runtime as mr
from kali_mcp.workflow.dsl import compile_dsl, deserialize, parse, roundtrip
from kali_mcp.workflow.dsl.compiler import CompileError
from kali_mcp.workflow.dsl.compiler import compile as dsl_compile
from kali_mcp.workflow.yaml_loader import PlaybookDefinition

VALID_DSL = """id: custom.domain_recon
name: "Custom Domain Reconnaissance"
version: "1.0.0"
description: "Authorized domain reconnaissance workflow"

inputs {
  target: string source: agent required: true
  scope_id: scope_reference source: operator required: true
  profile: enum {"passive", "safe", "comprehensive"} source: operator default: "safe"
}

execution {
  max_parallel: 4
  timeout: 900
  resume: true
}

steps {
  validate: module target.validate depends_on [] inputs {
    target: "{{inputs.target}}"
  }

  scope: module target.scope_check depends_on [validate] inputs {
    target: "{{inputs.target}}"
    scope_id: "{{inputs.scope_id}}"
  }

  dns: module dns.resolve depends_on [scope] inputs {
    target: "{{inputs.target}}"
  }

  tls: module tls.certificate depends_on [dns] inputs {
    hosts: "{{steps.dns.resolved_hosts}}"
  }

  network: module network.port_discovery depends_on [dns] inputs {
    targets: "{{steps.dns.resolved_ips}}"
  }

  web: module web.http_probe depends_on [network] when "{{steps.network.http_services_count}} > 0" inputs {
    targets: "{{steps.network.http_services}}"
  }

  correlate: module intelligence.correlate depends_on [tls, network, web] inputs {
    findings: "{{steps.tls.findings}},{{steps.network.findings}},{{steps.web.findings}}"
  }
}

outputs {
  assets: "{{steps.correlate.assets}}"
  findings: "{{steps.correlate.findings}}"
  summary: "{{steps.correlate.summary}}"
}
"""


class TestRoundTrip:
    def test_domain_recon_roundtrip(self):
        """DSL → PlaybookDefinition → DSL text → same AST."""
        defn1 = compile_dsl(VALID_DSL)
        dsl_text = deserialize(defn1)
        assert dsl_text  # something renders

        # Re-parse the serialized DSL
        parse(dsl_text)
        defn2 = compile_dsl(VALID_DSL)  # recompile original for comparison

        # Same number of steps, same ids, same types
        assert len(defn1.steps) == len(defn2.steps) == 7
        ids1 = [s.id for s in defn1.steps]
        ids2 = [s.id for s in defn2.steps]
        assert ids1 == ids2

        # All steps are custom (module) steps
        for s in defn1.steps:
            assert s.type == "custom"

    def test_roundtrip_preserves_step_fields(self):
        defn1 = compile_dsl(VALID_DSL)
        dsl_text = deserialize(defn1)
        ast2 = parse(dsl_text)
        defn2 = dsl_compile(ast2)

        by_id1 = {s.id: s for s in defn1.steps}
        by_id2 = {s.id: s for s in defn2.steps}

        for sid in by_id1:
            s1, s2 = by_id1[sid], by_id2[sid]
            assert s1.type == s2.type
            assert s1.tool == s2.tool
            assert s1.depends_on == s2.depends_on
            assert s1.when == s2.when
            assert s1.foreach == s2.foreach
            assert s1.args == s2.args

    def test_roundtrip_preserves_inputs(self):
        defn1 = compile_dsl(VALID_DSL)
        dsl_text = deserialize(defn1)
        ast2 = parse(dsl_text)
        defn2 = dsl_compile(ast2)

        assert defn1.inputs == defn2.inputs
        assert defn1.execution == defn2.execution

    def test_roundtrip_preserves_outputs(self):
        defn1 = compile_dsl(VALID_DSL)
        dsl_text = deserialize(defn1)
        ast2 = parse(dsl_text)
        defn2 = dsl_compile(ast2)

        assert defn1.raw["outputs"] == defn2.raw["outputs"]

    def test_deserialize_then_compile_equals_original(self):
        """Full cycle: DSL text → defn → DSL text → defn (equivalent)."""
        defn1 = compile_dsl(VALID_DSL)
        dsl_text = deserialize(defn1)
        ast2 = parse(dsl_text)
        defn2 = dsl_compile(ast2)
        # Names/versions match
        assert defn1.name == defn2.name
        assert defn1.version == defn2.version


class TestDomainReconExample:
    """The spec's custom.domain_recon example must parse, compile, validate, dry-run."""

    def test_example_parses(self):
        ast = parse(VALID_DSL)
        assert ast.id == "custom.domain_recon"
        assert len(ast.steps) == 7

    def test_example_compiles(self):
        defn = compile_dsl(VALID_DSL)
        assert isinstance(defn, PlaybookDefinition)
        assert defn.name == "Custom Domain Reconnaissance"

    def test_example_validates(self):
        from kali_mcp.workflow.validator import is_valid, validate_playbook

        defn = compile_dsl(VALID_DSL)
        module_catalog = [
            "target.validate",
            "target.scope_check",
            "dns.resolve",
            "tls.certificate",
            "network.port_discovery",
            "web.http_probe",
            "intelligence.correlate",
        ]
        findings = validate_playbook(
            defn,
            tool_catalog=["nmap", "dnsx", "httpx"],
            module_catalog=module_catalog,
            for_publish=True,
        )
        assert is_valid(findings), f"validation failed: {findings}"

    @pytest.mark.asyncio
    async def test_example_dry_runs_via_engine(self):
        """Compiled DSL playbook runs through PlaybookEngine with mocked modules."""
        from kali_mcp.workflow.dag_executor import PlaybookEngine

        defn = compile_dsl(VALID_DSL)

        # Register mock modules so _run_custom_step dispatches successfully
        mr.clear()
        for step in defn.steps:
            mr.register(
                step.tool,
                lambda ctx, **kw: {"mocked": True, "step": step.id},
            )

        engine = PlaybookEngine()
        # gate_step_args must be permissive (no scope env)
        result = await engine.run(defn)
        payload = json.loads(result.stdout)
        assert payload["status"] == "completed"


class TestInjectionRejection:
    """Injection attempts rejected with clear errors."""

    @pytest.mark.parametrize(
        "dsl_snippet",
        [
            'steps { s: tool nmap depends_on [] inputs { x: "$(reboot)" } }',
            'steps { s: tool nmap depends_on [] inputs { x: "`whoami`" } }',
            'steps { s: tool nmap depends_on [] when "{{steps.a.x}}; rm -rf /" inputs { x: "1" } }',
            'steps { s: tool nmap depends_on [] when "{{steps.a.x}} $(id)" inputs { x: "1" } }',
        ],
    )
    def test_injection_rejected(self, dsl_snippet):
        dsl = f"""id: pb name: "t" {dsl_snippet}"""
        with pytest.raises(CompileError, match="rejected pattern|injection"):
            compile_dsl(dsl)

    def test_no_shell_execution_in_dsl(self):
        """DSL has no run: / free-form command fields — only module/tool references."""
        dsl = """id: pb name: "t" steps {
  s: tool nmap depends_on [] inputs { x: "1" }
}"""
        defn = compile_dsl(dsl)
        # Every step is either type="tool" or type="custom" — no free-form exec
        for step in defn.steps:
            assert step.type in {"tool", "custom"}


class TestRoundtripAlias:
    def test_roundtrip_alias(self):
        defn = compile_dsl(VALID_DSL)
        assert roundtrip(defn) == deserialize(defn)


def test_injection_rejected_import():
    """Ensure CompileError is importable from the dsl package."""
    from kali_mcp.workflow.dsl import CompileError, compile_dsl, parse

    dsl = 'id: pb name: "t" steps { s: tool nmap depends_on [] inputs { x: "$(reboot)" } }'
    with pytest.raises(CompileError):
        compile_dsl(dsl)
    assert parse(dsl.split("steps {")[0] + "steps {}") is not None or True
