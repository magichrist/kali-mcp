"""Extra coverage tests for the DSL deserializer (dsl/deserializer.py).

Targets the render branches (enum/array type exprs, literal flavours,
version/header, module vs tool steps, step options and budget) that the
existing round-trip tests do not fully exercise.
"""

from __future__ import annotations

from kali_mcp.workflow.dsl.deserializer import deserialize
from kali_mcp.workflow.yaml_loader import (
    PlaybookDefinition,
    StepDefinition,
)


def _make_step(**overrides) -> StepDefinition:
    base = dict(
        id="s1",
        tool="dns.resolve",
        type="custom",
        depends_on=[],
        when=None,
        parallel=False,
        foreach=None,
        output_mapping={},
        retry=0,
        on_failure="abort",
        checkpoint=False,
        budget={},
        args={},
    )
    base.update(overrides)
    return StepDefinition(**base)


def _make_defn(**overrides) -> PlaybookDefinition:
    base = dict(
        name="test-playbook",
        version="1.0",
        inputs={},
        execution={},
        steps=[],
        raw={},
    )
    base.update(overrides)
    return PlaybookDefinition(**base)


class TestDeserializerHeaderAndInputs:
    def test_version_and_description_rendered(self):
        defn = _make_defn(
            raw={"id": "pb.hello", "description": "A playbook"},
            version="2.3.0",
        )
        text = deserialize(defn)
        assert 'id: pb.hello' in text
        assert 'name: "test-playbook"' in text
        assert 'version: "2.3.0"' in text
        assert 'description: "A playbook"' in text

    def test_inputs_enum_and_array_type_exprs(self):
        defn = _make_defn(
            inputs={
                "profile": {
                    "type": "enum",
                    "values": ["passive", "safe", "full"],
                    "required": True,
                },
                "ports": {"type": "array", "element_type": "integer"},
                "timeout": {"type": "float", "default": 5.5},
                "label": {"type": "string", "default": "hello"},
                "flag": {"type": "boolean", "default": True},
                "count": {"type": "integer", "default": 7},
            }
        )
        text = deserialize(defn)
        assert "inputs {" in text
        assert 'profile: enum {"passive", "safe", "full"} required: true' in text
        assert "ports: array [integer]" in text
        assert "timeout: float default: 5.5" in text
        assert 'label: string default: "hello"' in text
        assert "flag: boolean default: true" in text
        assert "count: integer default: 7" in text

    def test_input_default_fallback_quoted(self):
        # A non-scalar default falls to _quote(str(value)).
        defn = _make_defn(inputs={"cfg": {"type": "string", "default": {"a": 1}}})
        text = deserialize(defn)
        assert 'default: ' in text
        assert "{'a': 1}" in text


class TestDeserializerSteps:
    def test_custom_step_renders_module(self):
        defn = _make_defn(steps=[_make_step(id="r", type="custom", tool="dns.resolve")])
        text = deserialize(defn)
        assert "r: module: dns.resolve" in text or "r: module dns.resolve" in text

    def test_tool_step_renders_tool(self):
        defn = _make_defn(steps=[_make_step(id="s", type="tool", tool="nmap")])
        text = deserialize(defn)
        assert "s: tool: nmap" in text or "s: tool nmap" in text

    def test_step_options_rendered(self):
        step = _make_step(
            id="web",
            type="tool",
            tool="httpx",
            depends_on=["dns"],
            when="{{steps.dns.count}} > 0",
            parallel=True,
            foreach="{{steps.dns.ips}}",
            retry=3,
            on_failure="continue",
            checkpoint=True,
            budget={"timeout": 60, "retries": 2},
            args={"target": "{{inputs.target}}", "rate": 500, "name": "scan"},
        )
        defn = _make_defn(steps=[step])
        text = deserialize(defn)
        assert "depends_on: [dns]" in text
        assert 'when: "{{steps.dns.count}} > 0"' in text
        assert "parallel: true" in text
        assert 'foreach: "{{steps.dns.ips}}"' in text
        assert "retry: 3" in text
        assert "on_failure: continue" in text
        assert "checkpoint: true" in text
        assert "budget: {timeout: 60, retries: 2}" in text
        assert 'target: "{{inputs.target}}"' in text
        assert "rate: 500" in text
        assert 'name: "scan"' in text

    def test_empty_inputs_mapping(self):
        defn = _make_defn(steps=[_make_step(id="s", args={})])
        text = deserialize(defn)
        assert "inputs: {}" in text

    def test_execution_block_rendered(self):
        defn = _make_defn(execution={"max_parallel": 8, "timeout": 1200, "resume": False})
        text = deserialize(defn)
        assert "execution {" in text
        assert "max_parallel: 8" in text
        assert "timeout: 1200" in text
        assert "resume: false" in text


class TestDeserializerOutputs:
    def test_outputs_rendered(self):
        defn = _make_defn(raw={"outputs": {"assets": "{{steps.correlate.assets}}"}})
        text = deserialize(defn)
        assert "outputs {" in text
        assert 'assets: "{{steps.correlate.assets}}"' in text

    def test_trailing_newline(self):
        defn = _make_defn()
        text = deserialize(defn)
        assert text.endswith("\n")
