"""Tests for the DSL compiler (Playbook Studio Phase 2)."""

from __future__ import annotations

import pytest

from kali_mcp.workflow.dsl.compiler import CompileError, compile as dsl_compile
from kali_mcp.workflow.dsl.parser import DSLParseError, parse
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


class TestCompilerHappyPath:
    def test_compile_full_example(self):
        ast = parse(VALID_DSL)
        defn = dsl_compile(ast)
        assert isinstance(defn, PlaybookDefinition)
        assert defn.name == "Custom Domain Reconnaissance"
        assert defn.version == "1.0.0"
        assert len(defn.steps) == 7

    def test_step_types_are_custom_for_modules(self):
        defn = dsl_compile(parse(VALID_DSL))
        for step in defn.steps:
            assert step.type == "custom", f"step {step.id} type={step.type}"
            assert step.tool is not None

    def test_depends_on_preserved(self):
        defn = dsl_compile(parse(VALID_DSL))
        by_id = {s.id: s for s in defn.steps}
        assert by_id["scope"].depends_on == ["validate"]
        assert by_id["dns"].depends_on == ["scope"]
        assert by_id["correlate"].depends_on == ["tls", "network", "web"]

    def test_when_preserved(self):
        defn = dsl_compile(parse(VALID_DSL))
        by_id = {s.id: s for s in defn.steps}
        assert by_id["web"].when == "{{steps.network.http_services_count}} > 0"

    def test_args_resolved(self):
        defn = dsl_compile(parse(VALID_DSL))
        by_id = {s.id: s for s in defn.steps}
        assert by_id["validate"].args == {"target": "{{inputs.target}}"}
        assert by_id["tls"].args == {"hosts": "{{steps.dns.resolved_hosts}}"}

    def test_inputs_dict(self):
        defn = dsl_compile(parse(VALID_DSL))
        assert defn.inputs["target"]["type"] == "string"
        assert defn.inputs["target"]["source"] == "agent"
        assert defn.inputs["target"]["required"] is True
        assert defn.inputs["profile"]["type"] == "enum"
        assert defn.inputs["profile"]["values"] == ["passive", "safe", "comprehensive"]
        assert defn.inputs["profile"]["default"] == "safe"

    def test_execution_dict(self):
        defn = dsl_compile(parse(VALID_DSL))
        assert defn.execution["max_parallel"] == 4
        assert defn.execution["timeout"] == 900
        assert defn.execution["resume"] is True

    def test_tool_step_compiles(self):
        dsl = """id: pb.tools name: "t" steps {
  scan: tool nmap depends_on [] inputs { target: "127.0.0.1" }
}"""
        defn = dsl_compile(parse(dsl))
        s = defn.steps[0]
        assert s.type == "tool"
        assert s.tool == "nmap"
        assert s.args == {"target": "127.0.0.1"}

    def test_foreach_compiles(self):
        dsl = """id: pb.foreach name: "t" steps {
  dns: module dns.resolve depends_on [] inputs { target: "{{inputs.target}}" }
  iter: module dns.resolve depends_on [dns] foreach: "{{steps.dns.resolved_ips}}" inputs {
    target: "{{steps.dns.resolved_ips}}"
  }
}"""
        defn = dsl_compile(parse(dsl))
        by_id = {s.id: s for s in defn.steps}
        assert by_id["iter"].foreach == "{{steps.dns.resolved_ips}}"

    def test_outputs_in_raw(self):
        defn = dsl_compile(parse(VALID_DSL))
        assert defn.raw["outputs"]["assets"] == "{{steps.correlate.assets}}"
        assert defn.raw["outputs"]["findings"] == "{{steps.correlate.findings}}"


class TestCompilerValidation:
    def test_duplicate_step_id(self):
        dsl = """id: pb name: "t" steps {
  a: tool nmap depends_on [] inputs { x: "1" }
  a: tool nmap depends_on [] inputs { x: "2" }
}"""
        with pytest.raises(DSLParseError, match="duplicate step id"):
            dsl_compile(parse(dsl))

    def test_unknown_depends_on(self):
        dsl = """id: pb name: "t" steps {
  a: tool nmap depends_on [ghost] inputs { x: "1" }
}"""
        with pytest.raises(CompileError, match="depends_on"):
            dsl_compile(parse(dsl))

    def test_dependency_cycle(self):
        dsl = """id: pb name: "t" steps {
  a: tool nmap depends_on [b] inputs { x: "1" }
  b: tool nmap depends_on [a] inputs { x: "2" }
}"""
        with pytest.raises((CompileError, DSLParseError), match="cycle"):
            dsl_compile(parse(dsl))

    def test_step_ref_out_of_scope(self):
        # tls references dns.resolved_hosts but dns is not in tls.depends_on
        dsl = """id: pb name: "t" steps {
  dns: module dns.resolve depends_on [] inputs { target: "{{inputs.target}}" }
  tls: module tls.certificate depends_on [] inputs {
    hosts: "{{steps.dns.resolved_hosts}}"
  }
}"""
        with pytest.raises(CompileError, match="not in depends_on"):
            dsl_compile(parse(dsl))

    def test_injection_in_when(self):
        dsl = """id: pb name: "t" steps {
  dns: module dns.resolve depends_on [] inputs { target: "{{inputs.target}}" }
  web: module web.http_probe depends_on [dns] when "{{steps.dns.x}}; rm -rf /" inputs {
    target: "{{inputs.target}}"
  }
}"""
        with pytest.raises(CompileError, match="rejected pattern|injection"):
            dsl_compile(parse(dsl))

    def test_injection_in_literal(self):
        dsl = """id: pb name: "t" steps {
  s: tool nmap depends_on [] inputs { target: "$(reboot)" }
}"""
        with pytest.raises(CompileError, match="rejected pattern"):
            dsl_compile(parse(dsl))

    def test_unknown_tool_at_publish(self):
        dsl = """id: pb name: "t" steps {
  s: tool nonexistent_tool_xyz depends_on [] inputs { x: "1" }
}"""
        with pytest.raises(CompileError, match="not registered"):
            dsl_compile(parse(dsl), tool_catalog=["nmap"], for_publish=True)

    def test_unknown_module_at_publish(self):
        dsl = """id: pb name: "t" steps {
  s: module nonexistent.module depends_on [] inputs { x: "1" }
}"""
        with pytest.raises(CompileError, match="not registered"):
            dsl_compile(parse(dsl), module_catalog=["dns.resolve"], for_publish=True)

    def test_known_tool_ok_at_publish(self):
        dsl = """id: pb name: "t" steps {
  s: tool nmap depends_on [] inputs { x: "1" }
}"""
        defn = dsl_compile(parse(dsl), tool_catalog=["nmap"], for_publish=True)
        assert defn.steps[0].tool == "nmap"

    def test_known_module_ok_at_publish(self):
        dsl = """id: pb name: "t" steps {
  s: module dns.resolve depends_on [] inputs { x: "1" }
}"""
        defn = dsl_compile(parse(dsl), module_catalog=["dns.resolve"], for_publish=True)
        assert defn.steps[0].tool == "dns.resolve"

    def test_non_publish_allows_unknown_refs(self):
        dsl = """id: pb name: "t" steps {
  s: tool weird_tool depends_on [] inputs { x: "1" }
}"""
        # Without catalogs, unknown refs are allowed (validator catches later)
        defn = dsl_compile(parse(dsl))
        assert defn.steps[0].tool == "weird_tool"

    def test_top_level_output_must_reference_steps(self):
        dsl = """id: pb name: "t" steps {
  s: tool nmap depends_on [] inputs { x: "1" }
} outputs {
  bad: "{{inputs.target}}"
}"""
        with pytest.raises(CompileError, match="must reference"):
            dsl_compile(parse(dsl))


class TestCompilerEdgeCases:
    def test_empty_steps_list(self):
        dsl = 'id: pb name: "t" steps {}'
        defn = dsl_compile(parse(dsl))
        assert defn.steps == []

    def test_no_inputs(self):
        dsl = 'id: pb name: "t" steps { s: tool nmap depends_on [] inputs { x: "1" } }'
        defn = dsl_compile(parse(dsl))
        assert defn.inputs == {}

    def test_retry_and_checkpoint(self):
        dsl = """id: pb name: "t" steps {
  s: tool nmap depends_on [] retry: 3 checkpoint: true on_failure: continue inputs { x: "1" }
}"""
        defn = dsl_compile(parse(dsl))
        s = defn.steps[0]
        assert s.retry == 3
        assert s.checkpoint is True
        assert s.on_failure == "continue"

    def test_parallel(self):
        dsl = """id: pb name: "t" steps {
  s: tool nmap depends_on [] parallel: true inputs { x: "1" }
}"""
        defn = dsl_compile(parse(dsl))
        assert defn.steps[0].parallel is True


def test_compile_dsl_convenience():
    from kali_mcp.workflow.dsl import compile_dsl

    defn = compile_dsl(VALID_DSL)
    assert isinstance(defn, PlaybookDefinition)
    assert len(defn.steps) == 7
