"""Tests for BaseTool argument normalization (_normalize_arguments)."""

from __future__ import annotations

from kmcp.tools.base import _camel_to_snake, _coerce_value, _normalize_arguments

STRING_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "scan_type": {"type": "string"},
        "tags": {"type": ["string", "array"]},
        "timeout": {"type": "integer", "default": 300},
        "recursive": {"type": "boolean", "default": False},
        "operations": {"type": "array"},
    },
}


class TestCamelToSnake:
    def test_basic(self):
        assert _camel_to_snake("scanType") == "scan_type"

    def test_multi_word(self):
        assert _camel_to_snake("inputFile") == "input_file"
        assert _camel_to_snake("extraArgs") == "extra_args"

    def test_already_snake(self):
        assert _camel_to_snake("scan_type") == "scan_type"


class TestCoerceValue:
    def test_string_typed_field_never_converts_numbers(self):
        # A string-typed field named "3" must stay the string "3"
        assert _coerce_value("3", "string") == "3"

    def test_string_typed_field_never_converts_bools(self):
        assert _coerce_value("true", "string") == "true"
        assert _coerce_value("false", "string") == "false"

    def test_integer_field_coerces(self):
        assert _coerce_value("300", "integer") == 300

    def test_integer_field_coerces_float_string(self):
        assert _coerce_value("60.0", "integer") == 60

    def test_boolean_field_coerces(self):
        assert _coerce_value("true", "boolean") is True
        assert _coerce_value("false", "boolean") is False
        assert _coerce_value("1", "boolean") is True
        assert _coerce_value("0", "boolean") is False

    def test_number_field_coerces(self):
        assert _coerce_value("300.5", "number") == 300.5

    def test_none_becomes_empty_string(self):
        assert _coerce_value(None) == ""

    def test_list_to_comma_string_when_string_expected(self):
        assert _coerce_value(["a", "b"], "string") == "a,b"

    def test_list_passthrough_when_array_expected(self):
        assert _coerce_value([{"tool": "nmap"}], "array") == [{"tool": "nmap"}]

    def test_dict_passthrough_when_object_expected(self):
        obj = {"k": "v"}
        assert _coerce_value(obj, "object") is obj

    def test_dict_json_string_when_string_expected(self):
        assert _coerce_value({"k": "v"}, "string") == '{"k": "v"}'


class TestNormalizeArguments:
    def test_camel_case_keys_mapped_to_schema(self):
        out = _normalize_arguments(
            {"scanType": "-sV", "timeout": "60"}, STRING_SCHEMA
        )
        assert out["scan_type"] == "-sV"
        assert out["timeout"] == 60

    def test_string_values_not_corrupted(self):
        out = _normalize_arguments(
            {"name": "3", "tags": "true"}, STRING_SCHEMA
        )
        assert out["name"] == "3"
        assert out["tags"] == "true"

    def test_null_integer_field_dropped_so_default_applies(self):
        out = _normalize_arguments({"timeout": None, "name": "x"}, STRING_SCHEMA)
        assert "timeout" not in out  # tool's .get("timeout", default) hits default
        assert out["name"] == "x"

    def test_null_string_field_becomes_empty_string(self):
        out = _normalize_arguments({"name": None}, STRING_SCHEMA)
        assert out["name"] == ""

    def test_null_boolean_field_dropped(self):
        out = _normalize_arguments({"recursive": None}, STRING_SCHEMA)
        assert "recursive" not in out

    def test_array_string_union_takes_first_type(self):
        # tags is ["string","array"] — a list is joined per the field's
        # documented contract ("array will be joined with commas")
        out = _normalize_arguments({"tags": ["agent:x", "stage:1"]}, STRING_SCHEMA)
        assert out["tags"] == "agent:x,stage:1"

    def test_array_typed_field_untouched(self):
        ops = [{"tool": "nmap"}]
        out = _normalize_arguments({"operations": ops}, STRING_SCHEMA)
        assert out["operations"] is ops

    def test_empty_arguments(self):
        assert _normalize_arguments({}, STRING_SCHEMA) == {}
        assert _normalize_arguments(None, STRING_SCHEMA) == {}

    def test_whitespace_stripped(self):
        out = _normalize_arguments({"name": "  x  "}, STRING_SCHEMA)
        assert out["name"] == "x"

    def test_unknown_keys_ignored_not_rejected(self):
        out = _normalize_arguments({"name": "x", "bogus": 1}, STRING_SCHEMA)
        assert out["bogus"] == 1
