"""DSL deserializer for the Playbook Studio workflow language.

Serializes a :class:`kali_mcp.workflow.yaml_loader.PlaybookDefinition` back to
DSL text (see docs/visual/03_DSL_SPECIFICATION.md §3), enabling round-trip
equivalence between visual editor, DSL text, and YAML.

Round-trip is lossless for the supported subset: any PlaybookDefinition
produced by :func:`kali_mcp.workflow.dsl.compiler.compile` can be
deserialized and re-parsed to an equivalent definition.
"""

from __future__ import annotations

from typing import Any

from kali_mcp.workflow.yaml_loader import PlaybookDefinition


def _quote(s: str) -> str:
    """Double-quote a string, escaping inner quotes and backslashes."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_type_expr(decl: dict[str, Any]) -> str:
    """Render an input declaration's type expression."""
    t = decl.get("type", "string")
    if t == "enum":
        vals = ", ".join(_quote(v) for v in decl.get("values", []))
        return f"enum {{{vals}}}"
    if t == "array":
        elem = decl.get("element_type", "string")
        return f"array [{elem}]"
    return t


def _render_field_ref(ref: str) -> str:
    """Render a stored field reference string (already in {{...}} form)."""
    return ref


def _render_literal(value: Any) -> str:
    """Render a literal value for DSL output."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return _quote(value)
    return _quote(str(value))


def _render_mapping(name: str, value: Any) -> str:
    """Render a single input_mapping entry: name: value."""
    return f"{name}: {_render_literal(value)}"


def deserialize(defn: PlaybookDefinition) -> str:
    """Serialize a :class:`PlaybookDefinition` to DSL text.

    The output is valid DSL that :func:`kali_mcp.workflow.dsl.parser.parse`
    can consume, and :func:`kali_mcp.workflow.dsl.compiler.compile` can
    compile back to an equivalent definition.

    Lossless for the supported subset (all constructs in the grammar §3).
    """
    lines: list[str] = []

    # ── header ───────────────────────────────────────────────────────────
    pb_id = defn.raw.get("id", defn.name.replace(" ", "_").lower())
    lines.append(f"id: {pb_id}")
    lines.append(f"name: {_quote(defn.name)}")
    if defn.version:
        lines.append(f"version: {_quote(defn.version)}")
    if defn.raw.get("description"):
        lines.append(f"description: {_quote(defn.raw['description'])}")

    # ── inputs ───────────────────────────────────────────────────────────
    if defn.inputs:
        lines.append("inputs {")
        for name, decl in defn.inputs.items():
            parts = [f"{name}: {_render_type_expr(decl)}"]
            if decl.get("source"):
                parts.append(f"source: {decl['source']}")
            if decl.get("required"):
                parts.append("required: true")
            if "default" in decl:
                parts.append(f"default: {_render_literal(decl['default'])}")
            lines.append("  " + " ".join(parts))
        lines.append("}")

    # ── execution ────────────────────────────────────────────────────────
    exec_ = defn.execution
    if exec_:
        lines.append("execution {")
        if exec_.get("max_parallel") is not None:
            lines.append(f"  max_parallel: {exec_['max_parallel']}")
        if exec_.get("timeout") is not None:
            lines.append(f"  timeout: {exec_['timeout']}")
        if exec_.get("resume") is not None:
            lines.append(f"  resume: {'true' if exec_['resume'] else 'false'}")
        lines.append("}")

    # ── steps ────────────────────────────────────────────────────────────
    if defn.steps:
        lines.append("steps {")
        for step in defn.steps:
            parts: list[str] = [f"{step.id}:"]
            if step.type == "custom":
                parts.append(f"module: {step.tool}")
            else:
                parts.append(f"tool: {step.tool}")

            if step.depends_on:
                deps = ", ".join(step.depends_on)
                parts.append(f"depends_on: [{deps}]")

            if step.when:
                parts.append(f"when: {_quote(step.when)}")

            if step.parallel:
                parts.append("parallel: true")

            if step.foreach:
                parts.append(f"foreach: {_quote(step.foreach)}")

            if step.retry:
                parts.append(f"retry: {step.retry}")

            if step.on_failure != "abort":
                parts.append(f"on_failure: {step.on_failure}")

            if step.checkpoint:
                parts.append("checkpoint: true")

            if step.budget:
                items = ", ".join(f"{k}: {_render_literal(v)}" for k, v in step.budget.items())
                parts.append(f"budget: {{{items}}}")

            # inputs mapping
            mapping_parts: list[str] = []
            for arg_name, arg_val in step.args.items():
                mapping_parts.append(f"{arg_name}: {_render_literal(arg_val)}")
            parts.append("inputs: {" + ", ".join(mapping_parts) + "}")

            lines.append("  " + " ".join(parts))
        lines.append("}")

    # ── outputs ──────────────────────────────────────────────────────────
    raw_outputs = defn.raw.get("outputs", {})
    if raw_outputs:
        lines.append("outputs {")
        for name, ref in raw_outputs.items():
            lines.append(f"  {name}: {_quote(ref)}")
        lines.append("}")

    return "\n".join(lines) + "\n"


__all__ = ["deserialize"]
