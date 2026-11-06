"""Extra coverage tests for the DSL parser (dsl/parser.py).

Targets the error paths and type-expression branches the existing parser
tests do not exercise: dotted-id segments, non-string version/description,
enum with colon, array/object types, unknown execution keys, module/tool
reference validation, step-kind requirement, on_failure validation, budget
parsing, condition operators, and all field-ref shape validations.
"""

from __future__ import annotations

import pytest

from kali_mcp.workflow.dsl.parser import DSLParseError, parse


def _wrap(section: str) -> str:
    return f'id: t name: "t" {section}'


class TestHeader:
    def test_dotted_id_non_identifier_segment_raises(self):
        with pytest.raises(DSLParseError, match="identifier segment"):
            parse('id: a.1 name: "t" steps {}')

    def test_version_not_a_string_raises(self):
        with pytest.raises(DSLParseError, match="version string"):
            parse('id: a name: "t" version: 42 steps {}')

    def test_description_not_a_string_raises(self):
        with pytest.raises(DSLParseError, match="description string"):
            parse('id: a name: "t" description: 42 steps {}')


class TestInputTypes:
    def test_enum_with_optional_colon(self):
        ast = parse('id: a name: "t" inputs { x: enum: {"a","b"} } steps {}')
        assert ast.inputs[0].type_expr.kind == "enum"
        assert ast.inputs[0].type_expr.values == ["a", "b"]

    def test_array_type(self):
        ast = parse('id: a name: "t" inputs { x: array: [integer] } steps {}')
        assert ast.inputs[0].type_expr.kind == "array"
        assert ast.inputs[0].type_expr.element.kind == "integer"

    def test_object_type(self):
        ast = parse('id: a name: "t" inputs { x: object: {} } steps {}')
        assert ast.inputs[0].type_expr.kind == "object"


class TestExecution:
    def test_unknown_execution_key_raises(self):
        with pytest.raises(DSLParseError, match="unknown execution key"):
            parse('id: a name: "t" execution { bogus: 1 } steps {}')


class TestStepDecl:
    def test_module_ref_must_be_identifier(self):
        with pytest.raises(DSLParseError, match="module reference"):
            parse('id: a name: "t" steps { s: module 123 depends_on [] inputs { x: "1" } }')

    def test_module_dotted_segment_must_be_identifier(self):
        with pytest.raises(DSLParseError, match="module name segment"):
            parse('id: a name: "t" steps { s: module dns.123 depends_on [] inputs { x: "1" } }')

    def test_tool_ref_must_be_identifier(self):
        with pytest.raises(DSLParseError, match="tool name"):
            parse('id: a name: "t" steps { s: tool 123 depends_on [] inputs { x: "1" } }')

    def test_step_must_declare_module_or_tool(self):
        with pytest.raises(DSLParseError, match="module: or tool:"):
            parse('id: a name: "t" steps { s: depends_on [] inputs { x: "1" } }')


class TestStepOptions:
    def test_invalid_on_failure_raises(self):
        with pytest.raises(DSLParseError, match="on_failure must be"):
            parse('id: a name: "t" steps { s: tool nmap depends_on [] on_failure: weird inputs { x: "1" } }')

    def test_budget_parsing(self):
        ast = parse('id: a name: "t" steps { s: tool nmap depends_on [] budget { timeout: 60 retries: 3 } inputs { x: "1" } }')
        assert ast.steps[0].budget == {"timeout": 60, "retries": 3}

    def test_condition_operator_required(self):
        # Unquoted conditions skip the first token (parser quirk), so place a
        # field ref before the non-operator to reach the operator check.
        with pytest.raises(DSLParseError, match="comparison operator"):
            parse('id: a name: "t" steps { s: tool nmap depends_on [] when {{steps.a.x}} {{steps.b.y}} eq 1 inputs { x: "1" } }')

    def test_condition_unquoted_happy_path(self):
        ast = parse('id: a name: "t" steps { s: tool nmap depends_on [] when {{steps.a.x}} {{steps.b.y}} > 0 inputs { x: "1" } }')
        assert ast.steps[0].when == "{{steps.b.y}} > 0"


class TestFieldRefShapes:
    def test_quoted_field_ref_must_wrap_braces(self):
        with pytest.raises(DSLParseError, match="expected field reference"):
            parse('id: a name: "t" steps { s: tool nmap depends_on [] inputs { x: "1" } } outputs { o: "hello" }')

    def test_field_ref_wrong_token_raises(self):
        with pytest.raises(DSLParseError, match="expected field reference"):
            parse('id: a name: "t" steps { s: tool nmap depends_on [] when > 1 inputs { x: "1" } }')

    def test_target_takes_no_segments(self):
        with pytest.raises(DSLParseError, match="takes no additional path segments"):
            parse('id: a name: "t" steps { s: tool nmap depends_on [] inputs { x: "{{target.foo}}" } }')

    def test_inputs_takes_exactly_one_segment(self):
        with pytest.raises(DSLParseError, match="takes exactly one segment"):
            parse('id: a name: "t" steps { s: tool nmap depends_on [] inputs { x: "{{inputs.a.b}}" } }')

    def test_steps_requires_step_and_field(self):
        with pytest.raises(DSLParseError, match="requires at least step id and field"):
            parse('id: a name: "t" steps { s: tool nmap depends_on [] inputs { x: "{{steps}}" } }')

    def test_input_mapping_plain_literal(self):
        ast = parse('id: a name: "t" steps { s: tool nmap depends_on [] inputs { x: 42 } }')
        mapping = ast.steps[0].inputs[0]
        assert mapping.name == "x"
        assert mapping.value.value == 42

    def test_bare_word_literal(self):
        ast = parse('id: a name: "t" inputs { x: string default: safe } steps { s: tool nmap depends_on [] inputs { y: "1" } }')
        assert ast.inputs[0].default == "safe"

    def test_unexpected_literal_raises(self):
        with pytest.raises(DSLParseError, match="expected literal"):
            parse('id: a name: "t" steps { s: tool nmap depends_on [] inputs { x: > } }')
