"""Extra coverage tests for the DSL compiler (dsl/compiler.py).

Targets branches that are either dead code via the normal parse path or
only reachable by constructing an AST directly: when conditions without
an operator, input-mapping values that are neither FieldRef nor Literal,
foreach/on_failure/output validation errors, and compiler-level cycle
detection.
"""

from __future__ import annotations

import pytest

from kali_mcp.workflow.dsl.compiler import CompileError, compile as dsl_compile
from kali_mcp.workflow.dsl.parser import (
    Execution,
    FieldRef,
    InputDecl,
    InputMapping,
    Literal,
    OutputMap,
    PlaybookAST,
    StepDecl,
    TypeExpr,
)


def _step(
    id: str,
    kind: str = "tool",
    ref: str = "nmap",
    depends_on=None,
    when=None,
    parallel=False,
    foreach=None,
    retry=0,
    on_failure="abort",
    checkpoint=False,
    budget=None,
    inputs=None,
) -> StepDecl:
    return StepDecl(
        id=id,
        kind=kind,
        ref=ref,
        depends_on=depends_on or [],
        when=when,
        parallel=parallel,
        foreach=foreach,
        retry=retry,
        on_failure=on_failure,
        checkpoint=checkpoint,
        budget=budget or {},
        inputs=inputs or [],
    )


def _ast(**overrides) -> PlaybookAST:
    base = dict(
        id="pb.test",
        name="test",
        version="1.0",
        description=None,
        inputs=[],
        execution=Execution(),
        steps=[],
        outputs=[],
    )
    base.update(overrides)
    return PlaybookAST(**base)


class TestCompilerWhenConditions:
    def test_when_without_operator_raises(self):
        # A field reference with no comparison operator fails the regex check.
        ast = _ast(
            steps=[
                _step(
                    id="web",
                    when="{{steps.dns.count}}",
                    inputs=[InputMapping(name="x", value=Literal(kind="string", value="1"))],
                )
            ]
        )
        with pytest.raises(CompileError, match="must be 'field_ref OP literal'"):
            dsl_compile(ast)

    def test_when_ok(self):
        ast = _ast(
            steps=[
                _step(
                    id="web",
                    when="{{steps.dns.count}} > 0",
                    inputs=[InputMapping(name="x", value=Literal(kind="string", value="1"))],
                )
            ]
        )
        defn = dsl_compile(ast)
        assert defn.steps[0].when == "{{steps.dns.count}} > 0"


class TestCompilerInputMappingEdge:
    def test_mapping_value_neither_fieldref_nor_literal(self):
        # value is a plain int -> falls to the else branch (args[name] = None).
        ast = _ast(
            steps=[
                _step(
                    id="s",
                    inputs=[InputMapping(name="x", value=42)],  # type: ignore[arg-type]
                )
            ]
        )
        defn = dsl_compile(ast)
        assert defn.steps[0].args == {"x": None}


class TestCompilerForeachAndOnFailure:
    def test_foreach_references_step_not_in_depends_on(self):
        ast = _ast(
            steps=[
                _step(id="dns", ref="dns.resolve", depends_on=[]),
                _step(
                    id="iter",
                    depends_on=[],
                    foreach=FieldRef(kind="steps", path=["dns", "resolved_ips"]),
                    inputs=[InputMapping(name="x", value=Literal(kind="string", value="1"))],
                ),
            ]
        )
        with pytest.raises(CompileError, match="which is not in depends_on"):
            dsl_compile(ast)

    def test_invalid_on_failure_raises(self):
        ast = _ast(
            steps=[
                _step(id="s", on_failure="delete-everything")  # type: ignore[arg-type]
            ]
        )
        with pytest.raises(CompileError, match="invalid on_failure"):
            dsl_compile(ast)


class TestCompilerOutputs:
    def test_top_level_output_references_unknown_step(self):
        ast = _ast(
            steps=[_step(id="s")],
            outputs=[
                OutputMap(name="o", field_ref=FieldRef(kind="steps", path=["ghost", "x"]))
            ],
        )
        with pytest.raises(CompileError, match="references unknown step"):
            dsl_compile(ast)


class TestCompilerCycleDetection:
    def test_dependency_cycle_detected_at_compile(self):
        # Constructed directly so the parser's own cycle check is bypassed.
        ast = _ast(
            steps=[
                _step(id="a", depends_on=["b"]),
                _step(id="b", depends_on=["a"]),
            ]
        )
        with pytest.raises(CompileError, match="dependency cycle"):
            dsl_compile(ast)
