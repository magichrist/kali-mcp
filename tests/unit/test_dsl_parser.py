"""Tests for the DSL parser (Playbook Studio Phase 2)."""

from __future__ import annotations

import pytest

from kali_mcp.workflow.dsl.parser import (
    DSLParseError,
    Execution,
    FieldRef,
    parse,
)

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


class TestParserHappyPath:
    def test_parse_full_example(self):
        ast = parse(VALID_DSL)
        assert ast.id == "custom.domain_recon"
        assert ast.name == "Custom Domain Reconnaissance"
        assert ast.version == "1.0.0"
        assert ast.description == "Authorized domain reconnaissance workflow"

    def test_parse_inputs(self):
        ast = parse(VALID_DSL)
        assert len(ast.inputs) == 3
        t = ast.inputs[0]
        assert t.name == "target"
        assert t.type_expr.kind == "string"
        assert t.source == "agent"
        assert t.required is True
        assert t.default is None

        p = ast.inputs[2]
        assert p.name == "profile"
        assert p.type_expr.kind == "enum"
        assert p.type_expr.values == ["passive", "safe", "comprehensive"]
        assert p.source == "operator"
        assert p.required is False
        assert p.default == "safe"

    def test_parse_execution(self):
        ast = parse(VALID_DSL)
        e = ast.execution
        assert isinstance(e, Execution)
        assert e.max_parallel == 4
        assert e.timeout == 900
        assert e.resume is True

    def test_parse_steps(self):
        ast = parse(VALID_DSL)
        assert len(ast.steps) == 7

        s0 = ast.steps[0]
        assert s0.id == "validate"
        assert s0.kind == "module"
        assert s0.ref == "target.validate"
        assert s0.depends_on == []
        assert s0.inputs[0].name == "target"
        assert isinstance(s0.inputs[0].value, FieldRef)

        s6 = ast.steps[6]
        assert s6.id == "correlate"
        assert s6.kind == "module"
        assert s6.ref == "intelligence.correlate"
        assert s6.depends_on == ["tls", "network", "web"]

    def test_parse_when_condition(self):
        ast = parse(VALID_DSL)
        web = next(s for s in ast.steps if s.id == "web")
        assert web.when == "{{steps.network.http_services_count}} > 0"

    def test_parse_outputs(self):
        ast = parse(VALID_DSL)
        assert len(ast.outputs) == 3
        assert ast.outputs[0].name == "assets"
        assert ast.outputs[0].field_ref.kind == "steps"
        assert ast.outputs[0].field_ref.path == ["correlate", "assets"]

    def test_tool_step(self):
        dsl = """id: pb.tools name: "t" steps {
  scan: tool nmap depends_on [] inputs { target: "10.0.0.1" }
}"""
        ast = parse(dsl)
        s = ast.steps[0]
        assert s.kind == "tool"
        assert s.ref == "nmap"

    def test_foreach(self):
        dsl = """id: pb.foreach name: "t" steps {
  dns: module dns.resolve depends_on [] inputs { target: "{{inputs.target}}" }
  iter: module dns.resolve depends_on [dns] foreach: "{{steps.dns.resolved_ips}}" inputs {
    target: "{{steps.dns.resolved_ips}}"
  }
}"""
        ast = parse(dsl)
        s = ast.steps[1]
        assert s.foreach is not None
        assert s.foreach.kind == "steps"
        assert s.foreach.path == ["dns", "resolved_ips"]

    def test_minimal_playbook(self):
        dsl = 'id: pb.min name: "min" steps { s: tool nmap depends_on [] inputs { target: "x" } }'
        ast = parse(dsl)
        assert ast.version == "1.0"
        assert ast.description is None
        assert len(ast.inputs) == 0
        assert len(ast.outputs) == 0


class TestParserErrors:
    def test_duplicate_step_id(self):
        dsl = """id: pb name: "t" steps {
  a: tool nmap depends_on [] inputs { x: "1" }
  a: tool nmap depends_on [] inputs { x: "2" }
}"""
        with pytest.raises(DSLParseError, match="duplicate step id|expected"):
            parse(dsl)

    def test_unknown_type(self):
        dsl = """id: pb name: "t" inputs {
  x: unknown_type
} steps { s: tool nmap depends_on [] inputs { x: "1" } }"""
        with pytest.raises(DSLParseError):
            parse(dsl)

    def test_bad_source(self):
        dsl = """id: pb name: "t" inputs {
  x: string source: invalid
} steps { s: tool nmap depends_on [] inputs { x: "1" } }"""
        with pytest.raises(DSLParseError):
            parse(dsl)

    def test_dependency_cycle(self):
        dsl = """id: pb name: "t" steps {
  a: tool nmap depends_on [b] inputs { x: "1" }
  b: tool nmap depends_on [a] inputs { x: "2" }
}"""
        with pytest.raises(DSLParseError, match="cycle"):
            parse(dsl)

    def test_missing_step_id(self):
        dsl = 'id: pb name: "t" steps { : tool nmap depends_on [] inputs { x: "1" } }'
        with pytest.raises(DSLParseError):
            parse(dsl)

    def test_empty_input(self):
        with pytest.raises(DSLParseError):
            parse("")

    def test_unknown_section(self):
        dsl = """id: pb name: "t" unknown_section { x: 1 }"""
        with pytest.raises(DSLParseError):
            parse(dsl)


class TestFieldRef:
    def test_steps_ref(self):
        f = FieldRef(kind="steps", path=["dns", "resolved_hosts"])
        assert str(f) == "{{steps.dns.resolved_hosts}}"

    def test_inputs_ref(self):
        f = FieldRef(kind="inputs", path=["target"])
        assert str(f) == "{{inputs.target}}"

    def test_target_ref(self):
        f = FieldRef(kind="target", path=[])
        assert str(f) == "{{target}}"
