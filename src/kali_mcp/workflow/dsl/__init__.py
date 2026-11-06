"""DSL parser + compiler for the Playbook Studio workflow language.

Compiles DSL text (docs/visual/03_DSL_SPECIFICATION.md) into the canonical
:class:`kali_mcp.workflow.yaml_loader.PlaybookDefinition` consumed by
:class:`kali_mcp.workflow.dag_executor.PlaybookEngine`, and serializes
back to DSL text for round-trip equivalence.

Public API:

- :func:`parse` — DSL text → AST
- :func:`compile` — AST → :class:`PlaybookDefinition`
- :func:`deserialize` — :class:`PlaybookDefinition` → DSL text
- :func:`roundtrip` — :class:`PlaybookDefinition` → DSL text (alias for deserialize)
- :func:`compile_dsl` — DSL text → :class:`PlaybookDefinition` (parse + compile)
"""

from __future__ import annotations

from kali_mcp.workflow.dsl.compiler import CompileError, compile
from kali_mcp.workflow.dsl.deserializer import deserialize
from kali_mcp.workflow.dsl.parser import DSLParseError, PlaybookAST, parse

__all__ = [
    "CompileError",
    "DSLParseError",
    "PlaybookAST",
    "compile",
    "compile_dsl",
    "deserialize",
    "parse",
    "roundtrip",
]


def compile_dsl(
    text: str,
    *,
    tool_catalog: list[str] | None = None,
    module_catalog: list[str] | None = None,
    for_publish: bool = False,
):
    """Parse DSL text and compile to :class:`PlaybookDefinition` in one step."""
    ast = parse(text)
    return compile(
        ast,
        tool_catalog=tool_catalog,
        module_catalog=module_catalog,
        for_publish=for_publish,
    )


def roundtrip(defn) -> str:
    """Serialize a :class:`PlaybookDefinition` to DSL text (alias for :func:`deserialize`)."""
    return deserialize(defn)
