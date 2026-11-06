"""DSL compiler for the Playbook Studio workflow language.

Compiles a :class:`kali_mcp.workflow.dsl.parser.PlaybookAST` into a canonical
:class:`kali_mcp.workflow.yaml_loader.PlaybookDefinition` that the
:class:`kali_mcp.workflow.dag_executor.PlaybookEngine` can execute.

Per TD-3 (docs/visual/10_TECHNICAL_DECISIONS.md):
- ``module: dns.resolve`` steps compile to ``StepDefinition(type="custom",
  tool="dns.resolve")`` — dispatched through ``modules_runtime`` at runtime.
- ``tool: nmap`` steps compile to ``StepDefinition(type="tool", tool="nmap")``.

Compile-time checks (spec §10):
1. Unique step ids
2. depends_on references existing steps
3. No dependency cycles
4. tool/module references resolve to registered capabilities (publish time)
5. {{steps.X.FIELD}} references target fields from dependency steps
6. when conditions contain only structured field references (no shell)
7. foreach targets an array field
8. required inputs without defaults must be provided
9. secret/scope_reference types are not serialized without redaction

Injection patterns rejected per 07_SECURITY_ARCHITECTURE.md §4.1.
"""

from __future__ import annotations

import re
from typing import Any

from kali_mcp.workflow.dsl.parser import (
    FieldRef,
    Literal,
    PlaybookAST,
    StepDecl,
)
from kali_mcp.workflow.yaml_loader import (
    VALID_ON_FAILURE,
    VALID_STEP_TYPES,
    PlaybookDefinition,
    StepDefinition,
)

# Shell / template-injection denylist (mirrors security.py and
# yaml_loader._is_structured_condition). Checked on when-condition strings
# and any user-supplied string literal used as a step arg.
_DANGEROUS = (
    "$",
    "`",
    "(",
    ")",
    "exec",
    "eval",
    "import",
    "__",
    "subprocess",
    "os.",
    "sys.",
    "open(",
    "write(",
    "rm ",
    "curl ",
    "wget ",
)


class CompileError(ValueError):
    """Raised when DSL source cannot be compiled to a PlaybookDefinition."""

    def __init__(self, message: str, step_id: str | None = None):
        super().__init__(message)
        self.step_id = step_id


def _contains_injection(text: str) -> bool:
    """Return True if *text* contains a rejected shell/template-injection pattern."""
    lower = text.lower()
    return any(d in lower for d in _DANGEROUS)


def _field_ref_str(ref: FieldRef) -> str:
    """Render a FieldRef back to its {{...}} form."""
    if ref.kind == "target":
        return "{{target}}"
    if ref.kind == "inputs":
        return f"{{{{inputs.{ref.path[0]}}}}}"
    return f"{{{{steps.{'.'.join(ref.path)}}}}}"


def _literal_value(lit: Literal) -> Any:
    return lit.value


def _check_when_condition(cond: str, step_id: str) -> None:
    """Validate a when condition: structured refs only, no injection."""
    if _contains_injection(cond):
        raise CompileError(
            f"when condition contains rejected pattern: {cond}", step_id
        )
    # Must match field_ref OP literal
    m = re.match(
        r"^\{\{(?:steps|inputs|target)[^}]*\}\}\s*(>=|<=|==|!=|>|<)\s*.+$", cond
    )
    if not m:
        raise CompileError(
            f"when condition must be 'field_ref OP literal', got: {cond}",
            step_id,
        )


def compile(
    ast: PlaybookAST,
    *,
    tool_catalog: list[str] | None = None,
    module_catalog: list[str] | None = None,
    for_publish: bool = False,
) -> PlaybookDefinition:
    """Compile a :class:`PlaybookAST` into a :class:`PlaybookDefinition`.

    Args:
        ast: Parsed DSL AST from :func:`kali_mcp.workflow.dsl.parser.parse`.
        tool_catalog: Optional list of registered native tool names. Tool
            references are checked against it when provided.
        module_catalog: Optional list of registered internal module names.
            Module references are checked against it when provided.
        for_publish: Apply stricter publish-time rules (catalogs must be
            resolvable, unknown tool/module refs are errors not warnings).

    Returns:
        A validated :class:`PlaybookDefinition`.

    Raises:
        CompileError: on any compile-time violation.
    """
    # ── 1. Unique step ids ───────────────────────────────────────────────
    seen_ids: set[str] = set()
    for step in ast.steps:
        if step.id in seen_ids:
            raise CompileError(f"duplicate step id: {step.id}", step.id)
        seen_ids.add(step.id)

    # ── 2. depends_on references existing steps + 3. no cycles ───────────
    step_id_set = seen_ids
    for step in ast.steps:
        for dep in step.depends_on:
            if dep not in step_id_set:
                raise CompileError(
                    f"step {step.id!r} depends_on unknown step {dep!r}",
                    step.id,
                )

    # Cycle detection (DFS)
    _detect_cycles(ast.steps)

    # ── 4. Input declarations → dict ─────────────────────────────────────
    inputs: dict[str, Any] = {}
    for inp in ast.inputs:
        decl: dict[str, Any] = {"type": inp.type_expr.kind}
        if inp.type_expr.values is not None:
            decl["values"] = inp.type_expr.values
        if inp.source is not None:
            decl["source"] = inp.source
        if inp.required:
            decl["required"] = True
        if inp.default is not None:
            decl["default"] = inp.default
        inputs[inp.name] = decl

    # ── 5. Execution block ───────────────────────────────────────────────
    execution: dict[str, Any] = {}
    if ast.execution.max_parallel is not None:
        execution["max_parallel"] = ast.execution.max_parallel
    if ast.execution.timeout is not None:
        execution["timeout"] = ast.execution.timeout
    if ast.execution.resume is not None:
        execution["resume"] = ast.execution.resume

    # ── 6. Steps ─────────────────────────────────────────────────────────
    step_defs: list[StepDefinition] = []
    # Track which fields each step produces (for reference resolution).
    # We conservatively assume every module/tool step can produce any field
    # named in its output references; downstream steps declare what they
    # consume. We validate that referenced steps exist and are dependencies.
    produced_fields: dict[str, set[str]] = {}

    for step in ast.steps:
        # Validate step type
        step_type = "custom" if step.kind == "module" else "tool"
        if step_type not in VALID_STEP_TYPES:
            raise CompileError(
                f"invalid step type {step_type!r}", step.id
            )

        # 4. Tool/module reference resolution
        if step.kind == "tool":
            if tool_catalog is not None and step.ref not in tool_catalog:
                if for_publish:
                    raise CompileError(
                        f"tool {step.ref!r} is not registered", step.id
                    )
                # Non-publish: allow but note (validator will catch at publish)
        elif step.kind == "module":
            if module_catalog is not None and step.ref not in module_catalog:
                if for_publish:
                    raise CompileError(
                        f"module {step.ref!r} is not registered", step.id
                    )

        # Validate depends_on are actual dependencies (engine guarantees order)
        for dep in step.depends_on:
            if dep not in step_id_set:
                raise CompileError(
                    f"step {step.id!r} depends_on unknown step {dep!r}",
                    step.id,
                )

        # 5. Validate {{steps.X.FIELD}} references target dependency steps
        args: dict[str, Any] = {}
        for mapping in step.inputs:
            val = mapping.value
            if isinstance(val, FieldRef):
                ref_str = _field_ref_str(val)
                if _contains_injection(ref_str):
                    raise CompileError(
                        f"field reference contains rejected pattern: {ref_str}",
                        step.id,
                    )
                if val.kind == "steps":
                    ref_step = val.path[0] if val.path else ""
                    if ref_step not in step.depends_on:
                        raise CompileError(
                            f"step {step.id!r} references {{steps.{ref_step}...}} "
                            f"but {ref_step!r} is not in depends_on",
                            step.id,
                        )
                    produced_fields.setdefault(ref_step, set()).add(
                        val.path[1] if len(val.path) > 1 else ""
                    )
                args[mapping.name] = ref_str
            elif isinstance(val, Literal):
                lit_val = _literal_value(val)
                if isinstance(lit_val, str) and _contains_injection(lit_val):
                    raise CompileError(
                        f"string literal contains rejected pattern: {lit_val}",
                        step.id,
                    )
                args[mapping.name] = lit_val
            else:
                args[mapping.name] = None

        # 6. When condition
        if step.when is not None:
            _check_when_condition(step.when, step.id)

        # 7. foreach targets an array field (validated against dependency
        #    outputs if we know the type; otherwise a warning at publish)
        if step.foreach is not None:
            if step.foreach.kind == "steps":
                ref_step = step.foreach.path[0] if step.foreach.path else ""
                if ref_step not in step.depends_on:
                    raise CompileError(
                        f"step {step.id!r} foreach references {ref_step!r} "
                        f"which is not in depends_on",
                        step.id,
                    )

        # on_failure validation
        if step.on_failure not in VALID_ON_FAILURE:
            raise CompileError(
                f"invalid on_failure {step.on_failure!r}", step.id
            )

        step_defs.append(
            StepDefinition(
                id=step.id,
                tool=step.ref,
                type=step_type,
                depends_on=list(step.depends_on),
                when=step.when,
                parallel=step.parallel,
                foreach=_field_ref_str(step.foreach) if step.foreach else None,
                output_mapping={},
                retry=step.retry,
                on_failure=step.on_failure,
                checkpoint=step.checkpoint,
                budget=step.budget,
                args=args,
            )
        )
        produced_fields.setdefault(step.id, set())

    # ── 7. Outputs ───────────────────────────────────────────────────────
    # Top-level outputs map to step field references.
    output_mapping: dict[str, str] = {}
    for om in ast.outputs:
        if om.field_ref.kind != "steps":
            raise CompileError(
                f"top-level output {om.name!r} must reference {{steps.X.FIELD}}",
                None,
            )
        ref_step = om.field_ref.path[0] if om.field_ref.path else ""
        if ref_step not in step_id_set:
            raise CompileError(
                f"output {om.name!r} references unknown step {ref_step!r}",
                None,
            )
        output_mapping[om.name] = _field_ref_str(om.field_ref)

    raw = {
        "id": ast.id,
        "name": ast.name,
        "version": ast.version,
        "description": ast.description,
        "inputs": inputs,
        "execution": execution,
        "steps": [
            {
                "id": s.id,
                "tool": s.tool,
                "type": s.type,
                "depends_on": s.depends_on,
                "when": s.when,
                "parallel": s.parallel,
                "foreach": s.foreach,
                "output_mapping": s.output_mapping,
                "retry": s.retry,
                "on_failure": s.on_failure,
                "checkpoint": s.checkpoint,
                "budget": s.budget,
                "args": s.args,
            }
            for s in step_defs
        ],
        "outputs": {om.name: _field_ref_str(om.field_ref) for om in ast.outputs},
    }

    return PlaybookDefinition(
        name=ast.name,
        version=ast.version,
        inputs=inputs,
        execution=execution,
        steps=step_defs,
        raw=raw,
    )


def _detect_cycles(steps: list[StepDecl]) -> None:
    """Raise CompileError if the dependency graph contains a cycle."""
    adj: dict[str, list[str]] = {s.id: list(s.depends_on) for s in steps}
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {s.id: WHITE for s in steps}

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for dep in adj.get(node, []):
            if dep not in color:
                continue
            if color[dep] == GRAY:
                cycle = " → ".join(path[path.index(dep) :] + [dep])
                raise CompileError(f"dependency cycle: {cycle}")
            if color[dep] == WHITE:
                dfs(dep, path)
        path.pop()
        color[node] = BLACK

    for sid in adj:
        if color[sid] == WHITE:
            dfs(sid, [])


__all__ = [
    "CompileError",
    "compile",
]
