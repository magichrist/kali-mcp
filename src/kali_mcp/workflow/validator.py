"""Full validation subsystem for workflow playbooks.

Implements the compile-time validation rules from
``docs/visual/03_DSL_SPECIFICATION.md`` §10 and emits the finding contract used
by the Studio API, visual editor, and publish path::

    {"severity": "error" | "warning", "step_id": str | None,
     "field": str | None, "message": str}

The public entry point is :func:`validate_playbook`; :func:`is_valid` reduces a
finding list to a boolean. The validator is side-effect free and performs no I/O
beyond an optional lazy import of the live tool registry when the caller does
not inject a ``tool_catalog``.

Design notes:

* Step results without a declared output schema are treated as *unverifiable*,
  which produces a warning instead of an error. Once a schema is known (raw
  step ``outputs`` / ``output_schema`` or a built-in step type), unknown fields
  are hard errors.
* Step output references must point at a step that is an ancestor in the
  ``depends_on`` graph (direct or transitive), mirroring the DSL rule that a
  referenced step must be a dependency.
* ``when`` conditions follow the DSL grammar ``field_ref OPERATOR literal`` and
  are additionally screened for shell / code-injection tokens.
"""

from __future__ import annotations

import difflib
import re
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from kali_mcp.workflow.yaml_loader import (
    VALID_ON_FAILURE,
    VALID_STEP_TYPES,
    PlaybookDefinition,
    StepDefinition,
    load_module,
)

Severity = Literal["error", "warning"]
Finding = dict[str, Any]

#: Input types allowed by ``03_DSL_SPECIFICATION.md`` §8.
INPUT_TYPES = frozenset(
    {
        "string",
        "integer",
        "float",
        "boolean",
        "enum",
        "domain",
        "ip",
        "cidr",
        "url",
        "port",
        "port_range",
        "array",
        "object",
        "secret",
        "scope_reference",
    }
)

#: Input value sources allowed by the DSL.
INPUT_SOURCES = frozenset({"agent", "operator", "static"})

#: Execution-block keys understood by the engine (bounds are enforced there).
_EXECUTION_KEYS = frozenset({"max_parallel", "timeout", "resume", "max_iterations"})

#: Budget keys that must be positive integers when present.
_POSITIVE_BUDGET_KEYS = frozenset({"timeout", "max_output_bytes", "max_iterations", "max_parallel"})

#: Output fields produced by engine-native step types (see dag_executor.py).
_BUILTIN_OUTPUT_SCHEMAS: dict[str, dict[str, str]] = {
    "scope_check": {
        "step": "string",
        "target": "string",
        "allowed": "boolean",
        "scope_ok": "boolean",
    },
    "finding_correlation": {
        "step": "string",
        "correlated_findings": "array",
        "total_observations": "integer",
        "total_correlated": "integer",
    },
    "assessment_report": {
        "step": "string",
        "report": "object",
    },
}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REF_RE = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_REF_BODY_RE = re.compile(
    r"^(?:"
    r"(?P<target>target)"
    r"|inputs\.(?P<input>[A-Za-z_][A-Za-z0-9_]*)"
    r"|options\.(?P<option>[A-Za-z_][A-Za-z0-9_]*)(?P<ofields>(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
    r"|steps\.(?P<step>[A-Za-z_][A-Za-z0-9_]*)(?P<fields>(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
    r")$"
)
_BARE_STEP_REF_RE = re.compile(
    r"^(?P<step>[A-Za-z_][A-Za-z0-9_]*)(?P<fields>(?:\.[A-Za-z_][A-Za-z0-9_]*)+)$"
)
_WHEN_RE = re.compile(
    r"^(?P<ref>\{\{(?P<braced>[^{}]+)\}\}|(?P<bare>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*))"
    r"\s*(?P<op>>=|<=|==|!=|>|<)\s*(?P<literal>.+)$"
)
_LITERAL_RE = re.compile(
    r"^(?:"
    r'"[^"\\\n\r]*"'
    r"|'[^'\\\n\r]*'"
    r"|-?\d+(?:\.\d+)?"
    r"|true|false|null"
    r"|[A-Za-z_][A-Za-z0-9_.-]*"
    r")$",
    re.IGNORECASE,
)
_ARRAY_TYPE_RE = re.compile(r"^array\s*(?:\[\s*(.+?)\s*\])?$", re.IGNORECASE)
_OBJECT_TYPE_RE = re.compile(r"^object\s*(?:\{\s*\})?$", re.IGNORECASE)

#: Shell / code-injection substrings rejected in ``when`` expressions.
_DANGEROUS_SUBSTRINGS = ("&&", "||", "$(", ";", "$", "`", "(", ")", "|", "\n", "\r", "\\")

#: Identifier-shaped injection tokens rejected in ``when`` expressions.
_DANGEROUS_WORDS_RE = re.compile(
    r"\b(?:exec|eval|compile|import|__import__|globals|locals|getattr|setattr|system|popen|subprocess)\b"
    r"|os\.|sys\.|__",
    re.IGNORECASE,
)


# ── internal data carriers ──────────────────────────────────────────────


@dataclass(frozen=True)
class _InputSpec:
    """Normalised view of one playbook input declaration."""

    name: str
    type: str | None
    source: str | None
    required: bool
    has_default: bool
    default: Any
    enum_values: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class _OutputSchema:
    """Declared output fields (and, when known, their DSL types)."""

    fields: dict[str, str | None]
    source: str


@dataclass
class _ValidationContext:
    """Bundle of derived lookups shared by the reference checkers."""

    input_specs: dict[str, _InputSpec]
    output_schemas: dict[str, _OutputSchema | None]
    ancestors: dict[str, set[str]]
    step_ids: set[str]


# ── public API ──────────────────────────────────────────────────────────


def validate_playbook(
    defn: PlaybookDefinition,
    *,
    tool_catalog: Iterable[str] | None = None,
    for_publish: bool = False,
    module_catalog: Iterable[str] | None = None,
) -> list[Finding]:
    """Validate a playbook definition and return structured findings.

    Args:
        defn: Canonical playbook object from ``yaml_loader`` (or the DSL compiler).
        tool_catalog: Iterable of registered native tool names. When ``None`` the
            live registry is imported lazily, falling back to ``ALL_TOOLS``; if
            no catalog can be resolved, tool resolution is skipped with a
            warning (an error when ``for_publish`` is true).
        for_publish: Apply the stricter publish-time rules required by the DSL
            spec (a tool catalog must be resolvable, custom steps must declare a
            module/tool reference, and unverified module availability is reported).
        module_catalog: Optional iterable of internal module identifiers. When
            supplied, ``type="custom"`` step references are resolved against it.

    Returns:
        Ordered list of ``{"severity", "step_id", "field", "message"}`` dicts.
        Errors sort before warnings; duplicate findings are collapsed.
    """
    if not isinstance(defn, PlaybookDefinition):
        return [
            _finding(
                "error",
                None,
                None,
                "validate_playbook expects a PlaybookDefinition instance",
            )
        ]

    findings: list[Finding] = []
    raw_index = _index_raw_steps(defn.raw)
    input_specs = _validate_inputs(defn, findings)
    _validate_header(defn, findings)
    _validate_execution(defn, findings)

    steps = _validate_steps(defn, raw_index, input_specs, findings, module_catalog)
    step_ids = {step.id for step in steps if isinstance(step.id, str) and step.id}
    predecessors = _build_predecessors(steps, step_ids, findings)
    ancestors = _collect_ancestors(predecessors, step_ids)
    output_schemas = _build_output_schemas(steps, raw_index, step_ids)
    context = _ValidationContext(
        input_specs=input_specs,
        output_schemas=output_schemas,
        ancestors=ancestors,
        step_ids=step_ids,
    )

    _validate_graph(steps, predecessors, findings)
    _validate_references(steps, raw_index, context, findings)
    _validate_playbook_outputs(defn, context, findings)
    _validate_limits(steps, raw_index, findings)
    _resolve_tools(defn, steps, raw_index, tool_catalog, module_catalog, for_publish, findings)

    return _finalise(findings, steps)


def is_valid(findings: Iterable[Finding]) -> bool:
    """Return ``True`` when a finding list contains no errors."""
    return not any(finding.get("severity") == "error" for finding in findings)


def format_findings(findings: Iterable[Finding]) -> str:
    """Render findings in the error-report style from DSL spec §11.

    Example::

        Error: step "web" field "args.targets": ...
        Warning: step "dns" field "args.hosts": ...
    """
    lines: list[str] = []
    for finding in findings:
        severity = str(finding.get("severity", "error")).capitalize()
        location = ""
        step_id = finding.get("step_id")
        field = finding.get("field")
        if step_id:
            location = f'step "{step_id}"'
        if field:
            location = f'{location} field "{field}":' if location else f'field "{field}":'
        message = finding.get("message", "")
        lines.append(f"{severity}: {location} {message}".replace(" :", ":"))
    return "\n".join(lines)


# ── header / execution ──────────────────────────────────────────────────


def _validate_header(defn: PlaybookDefinition, findings: list[Finding]) -> None:
    """Check playbook-level identity fields."""
    if not isinstance(defn.name, str) or not defn.name.strip():
        findings.append(_finding("error", None, "name", "playbook name must be a non-empty string"))
    if not isinstance(defn.version, str) or not defn.version.strip():
        findings.append(
            _finding("warning", None, "version", "playbook version should be a non-empty string")
        )
    if defn.raw is not None and not isinstance(defn.raw, Mapping):
        findings.append(_finding("warning", None, "raw", "playbook raw payload must be a mapping"))


def _validate_execution(defn: PlaybookDefinition, findings: list[Finding]) -> None:
    """Validate the execution block: bounds and known keys."""
    execution = defn.execution
    if not isinstance(execution, Mapping):
        findings.append(_finding("error", None, "execution", "execution block must be a mapping"))
        return

    for key in ("max_parallel", "timeout", "max_iterations"):
        if key in execution and not _is_positive_int(execution[key]):
            findings.append(
                _finding(
                    "error",
                    None,
                    f"execution.{key}",
                    f"{key} must be a positive integer, got {execution[key]!r}",
                )
            )
    if "resume" in execution and not isinstance(execution["resume"], bool):
        findings.append(
            _finding(
                "warning",
                None,
                "execution.resume",
                f"resume should be a boolean, got {execution['resume']!r}",
            )
        )
    for key in execution:
        if key not in _EXECUTION_KEYS:
            findings.append(
                _finding(
                    "warning",
                    None,
                    f"execution.{key}",
                    f"unknown execution key {key!r}",
                )
            )


# ── inputs ──────────────────────────────────────────────────────────────


def _validate_inputs(defn: PlaybookDefinition, findings: list[Finding]) -> dict[str, _InputSpec]:
    """Normalise and validate every declared playbook input."""
    raw_inputs = defn.inputs
    specs: dict[str, _InputSpec] = {}

    if raw_inputs is None:
        return specs
    if isinstance(raw_inputs, Mapping):
        items: Iterable[tuple[Any, Any]] = raw_inputs.items()
    elif isinstance(raw_inputs, (list, tuple)):
        items = ((entry.get("name"), entry) for entry in raw_inputs if isinstance(entry, Mapping))
    else:
        findings.append(_finding("error", None, "inputs", "inputs must be a mapping"))
        return specs

    for name, declaration in items:
        if not isinstance(name, str) or not _IDENT_RE.match(name):
            findings.append(_finding("error", None, "inputs", f"invalid input name {name!r}"))
            continue

        spec_map: Mapping[str, Any]
        if declaration is None:
            spec_map = {}
        elif isinstance(declaration, str):
            spec_map = {"type": declaration}
        elif isinstance(declaration, Mapping):
            spec_map = declaration
        else:
            findings.append(
                _finding(
                    "error",
                    None,
                    f"inputs.{name}",
                    "input declaration must be a mapping or type string",
                )
            )
            continue

        specs[name] = _validate_input_spec(name, spec_map, findings)

    return specs


def _validate_input_spec(name: str, spec: Mapping[str, Any], findings: list[Finding]) -> _InputSpec:
    """Validate a single input declaration and return its normalised spec."""
    field = f"inputs.{name}"
    declared_type = spec.get("type")
    base_type: str | None = None

    if declared_type is None:
        findings.append(_finding("warning", None, field, f"input {name!r} does not declare a type"))
    elif not isinstance(declared_type, str) or not declared_type.strip():
        findings.append(_finding("error", None, field, "input type must be a non-empty string"))
    else:
        parsed = _parse_type(declared_type)
        if parsed is None:
            findings.append(
                _finding(
                    "error",
                    None,
                    field,
                    f"input {name!r} has unsupported type {declared_type!r} (allowed: "
                    f"{', '.join(sorted(INPUT_TYPES))})",
                )
            )
        else:
            base_type = parsed[0]

    source = spec.get("source")
    source_value: str | None = None
    if source is not None:
        if not isinstance(source, str) or source not in INPUT_SOURCES:
            findings.append(
                _finding(
                    "error",
                    None,
                    field,
                    f"input {name!r} source must be one of {sorted(INPUT_SOURCES)}, got {source!r}",
                )
            )
        else:
            source_value = source

    required = bool(spec.get("required", False))
    has_default = "default" in spec
    default = spec.get("default")

    if required and not has_default and source_value not in ("agent", "operator"):
        findings.append(
            _finding(
                "error",
                None,
                field,
                f"required input {name!r} has no default and must declare "
                "source: agent or source: operator",
            )
        )

    enum_values: tuple[Any, ...] | None = None
    if base_type == "enum":
        raw_values = spec.get("values", spec.get("enum", spec.get("choices")))
        if not isinstance(raw_values, (list, tuple)) or not raw_values:
            findings.append(
                _finding(
                    "error",
                    None,
                    field,
                    f"enum input {name!r} must declare a non-empty values list",
                )
            )
        else:
            enum_values = tuple(raw_values)
            if has_default and default not in enum_values:
                findings.append(
                    _finding(
                        "error",
                        None,
                        field,
                        f"default {default!r} is not one of the enum values {list(enum_values)!r}",
                    )
                )

    if (
        base_type in ("secret", "scope_reference")
        and source_value == "agent"
        and not spec.get("redact", False)
    ):
        findings.append(
            _finding(
                "warning",
                None,
                field,
                f"input {name!r} is agent-sourced and typed {base_type!r}; it must be "
                "redacted from agent-facing schemas",
            )
        )

    if (
        has_default
        and base_type is not None
        and not _default_matches_type(default, base_type, enum_values)
    ):
        findings.append(
            _finding(
                "warning",
                None,
                field,
                f"default {default!r} does not match declared type {base_type!r}",
            )
        )

    return _InputSpec(
        name=name,
        type=base_type,
        source=source_value,
        required=required,
        has_default=has_default,
        default=default,
        enum_values=enum_values,
    )


# ── steps ───────────────────────────────────────────────────────────────


def _validate_steps(
    defn: PlaybookDefinition,
    raw_index: dict[str, Mapping[str, Any]],
    input_specs: dict[str, _InputSpec],
    findings: list[Finding],
    module_catalog: Iterable[str] | None,
) -> list[StepDefinition]:
    """Validate step structure (ids, types, tool refs, args, when, foreach)."""
    raw_steps = defn.steps
    if not isinstance(raw_steps, (list, tuple)):
        findings.append(_finding("error", None, "steps", "steps must be a list"))
        return []
    if not raw_steps:
        findings.append(_finding("error", None, "steps", "playbook defines no steps"))
        return []

    steps: list[StepDefinition] = []
    seen: set[str] = set()
    modules = _normalise_catalog(module_catalog) if module_catalog is not None else None

    for index, step in enumerate(raw_steps):
        if not isinstance(step, StepDefinition):
            findings.append(
                _finding("error", None, f"steps[{index}]", "step must be a StepDefinition")
            )
            continue
        steps.append(step)

        step_id = step.id
        if not isinstance(step_id, str) or not step_id:
            findings.append(
                _finding("error", None, "id", f"step at index {index} must have a non-empty id")
            )
            continue
        if not _IDENT_RE.match(step_id):
            findings.append(_finding("error", step_id, "id", f"invalid step id {step_id!r}"))
        if step_id in seen:
            findings.append(_finding("error", step_id, "id", f"duplicate step id {step_id!r}"))
        seen.add(step_id)

        _validate_step_type(step, raw_index, findings)
        _validate_tool_reference(step, raw_index, modules, findings)
        _validate_foreach(step, input_specs, findings)
        _validate_when(step, findings)

        if not isinstance(step.args, Mapping):
            findings.append(_finding("error", step_id, "args", "args must be a mapping"))
        if not isinstance(step.output_mapping, Mapping):
            findings.append(
                _finding("error", step_id, "output_mapping", "output_mapping must be a mapping")
            )
        else:
            for key, value in step.output_mapping.items():
                if not isinstance(key, str):
                    findings.append(
                        _finding("error", step_id, "output_mapping", "output keys must be strings")
                    )
                if not isinstance(value, str):
                    findings.append(
                        _finding(
                            "error",
                            step_id,
                            f"output_mapping.{key}",
                            "output_mapping values must be reference strings",
                        )
                    )
        if not isinstance(step.retry, int) or isinstance(step.retry, bool) or step.retry < 0:
            findings.append(_finding("error", step_id, "retry", "retry must be an integer >= 0"))
        if step.on_failure not in VALID_ON_FAILURE:
            findings.append(
                _finding(
                    "error",
                    step_id,
                    "on_failure",
                    f"on_failure must be one of {sorted(VALID_ON_FAILURE)}",
                )
            )
        if not isinstance(step.parallel, bool):
            findings.append(
                _finding("warning", step_id, "parallel", "parallel should be a boolean")
            )
        if not isinstance(step.checkpoint, bool):
            findings.append(
                _finding("warning", step_id, "checkpoint", "checkpoint should be a boolean")
            )
        _validate_budget(step, findings)

    return steps


def _validate_step_type(
    step: StepDefinition,
    raw_index: dict[str, Mapping[str, Any]],
    findings: list[Finding],
) -> None:
    """Check the declared step type."""
    if step.type not in VALID_STEP_TYPES:
        findings.append(
            _finding(
                "error",
                step.id,
                "type",
                f"unknown step type {step.type!r} (allowed: {', '.join(sorted(VALID_STEP_TYPES))})",
            )
        )
        return
    if step.type == "custom" and not step.tool:
        raw_step = raw_index.get(step.id, {})
        if raw_step.get("module") is None:
            findings.append(
                _finding(
                    "warning",
                    step.id,
                    "tool",
                    "custom step does not declare a module reference",
                )
            )
    if step.type == "shell":
        if not isinstance(step.command, str) or not step.command.strip():
            findings.append(
                _finding(
                    "error",
                    step.id,
                    "command",
                    "shell step must declare a non-empty command",
                )
            )
        flt = step.filter if isinstance(step.filter, Mapping) else None
        if flt:
            ftype = str(flt.get("type") or "grep")
            if ftype not in ("", "none", "raw", "grep", "regex"):
                findings.append(
                    _finding(
                        "error",
                        step.id,
                        "filter.type",
                        f"unknown filter type {ftype!r} (allowed: grep, regex, none)",
                    )
                )
            elif ftype in ("grep", "regex"):
                pattern = flt.get("pattern")
                if not isinstance(pattern, str):
                    findings.append(
                        _finding(
                            "error",
                            step.id,
                            "filter.pattern",
                            "filter pattern must be a string",
                        )
                    )
                elif pattern.strip():
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        findings.append(
                            _finding(
                                "error",
                                step.id,
                                "filter.pattern",
                                f"invalid filter pattern: {exc}",
                            )
                        )


def _validate_tool_reference(
    step: StepDefinition,
    raw_index: dict[str, Mapping[str, Any]],
    modules: set[str] | None,
    findings: list[Finding],
) -> None:
    """Check that a step declares the capability reference its type requires."""
    tool = step.tool
    if tool is not None and (not isinstance(tool, str) or not tool.strip()):
        findings.append(
            _finding("error", step.id, "tool", "tool reference must be a non-empty string")
        )
        return

    if step.type == "tool" and not tool:
        raw_module = raw_index.get(step.id, {}).get("module")
        if isinstance(raw_module, str) and raw_module:
            # Legacy YAML definitions use ``module:`` even when the loader maps
            # them to type="tool"; report module availability instead.
            _check_module_available(step.id, raw_module, modules, findings)
            return
        findings.append(
            _finding("error", step.id, "tool", "tool step must declare a tool reference")
        )
    elif step.type == "custom" and tool:
        _check_module_available(step.id, tool, modules, findings)


def _check_module_available(
    step_id: str,
    module_name: str,
    modules: set[str] | None,
    findings: list[Finding],
) -> None:
    """Resolve a module reference when a module catalog is available.

    Falls back to YAML module definitions (``playbooks/modules/<cat>/<id>.yaml``)
    when the module is not registered in the Python module registry, so legacy
    YAML playbooks that reference short module names (e.g. ``module: nmap``)
    still validate.
    """
    if modules is None:
        return
    if module_name not in modules:
        # Fall back to YAML module definition lookup
        if load_module(module_name) is not None:
            return
        hint = _suggestion(module_name, modules)
        findings.append(
            _finding(
                "error",
                step_id,
                "tool",
                f"step {step_id!r} module {module_name!r} is not registered{hint}",
            )
        )


def _validate_budget(step: StepDefinition, findings: list[Finding]) -> None:
    """Validate per-step budget limits."""
    budget = step.budget
    if not budget:
        return
    if not isinstance(budget, Mapping):
        findings.append(_finding("error", step.id, "budget", "budget must be a mapping"))
        return
    for key in _POSITIVE_BUDGET_KEYS:
        if key in budget and not _is_positive_int(budget[key]):
            findings.append(
                _finding(
                    "error",
                    step.id,
                    f"budget.{key}",
                    f"budget.{key} must be a positive integer, got {budget[key]!r}",
                )
            )


# ── graph ───────────────────────────────────────────────────────────────


def _build_predecessors(
    steps: list[StepDefinition], step_ids: set[str], findings: list[Finding]
) -> dict[str, set[str]]:
    """Validate ``depends_on`` entries and build the predecessor graph."""
    predecessors: dict[str, set[str]] = {}

    for step in steps:
        if not isinstance(step.id, str) or not step.id:
            continue
        predecessors.setdefault(step.id, set())
        deps = step.depends_on
        if not isinstance(deps, (list, tuple)):
            findings.append(
                _finding("error", step.id, "depends_on", "depends_on must be a list of step ids")
            )
            continue

        seen_deps: set[str] = set()
        for dep in deps:
            if not isinstance(dep, str) or not dep:
                findings.append(
                    _finding("error", step.id, "depends_on", "depends_on entries must be step ids")
                )
                continue
            if dep == step.id:
                findings.append(
                    _finding(
                        "error",
                        step.id,
                        "depends_on",
                        f"step {step.id!r} cannot depend on itself",
                    )
                )
                continue
            if dep in seen_deps:
                findings.append(
                    _finding(
                        "warning",
                        step.id,
                        "depends_on",
                        f"duplicate dependency {dep!r}",
                    )
                )
                continue
            seen_deps.add(dep)
            if dep not in step_ids:
                hint = _suggestion(dep, step_ids)
                findings.append(
                    _finding(
                        "error",
                        step.id,
                        "depends_on",
                        f"depends_on references unknown step {dep!r}{hint}",
                    )
                )
                continue
            predecessors[step.id].add(dep)

    return predecessors


def _collect_ancestors(
    predecessors: dict[str, set[str]], step_ids: set[str]
) -> dict[str, set[str]]:
    """Return the transitive-dependency set for every step (cycle safe)."""
    memo: dict[str, set[str]] = {}

    def visit(node: str, stack: set[str]) -> set[str]:
        if node in memo:
            return memo[node]
        if node in stack:
            return set()
        stack.add(node)
        collected: set[str] = set()
        for parent in predecessors.get(node, ()):
            if parent not in step_ids:
                continue
            collected.add(parent)
            collected |= visit(parent, stack)
        stack.discard(node)
        memo[node] = collected
        return collected

    for step_id in step_ids:
        visit(step_id, set())
    return memo


def _validate_graph(
    steps: list[StepDefinition], predecessors: dict[str, set[str]], findings: list[Finding]
) -> None:
    """Detect dependency cycles (Kahn) and unreachable steps."""
    nodes = [step.id for step in steps if isinstance(step.id, str) and step.id]
    unique_nodes = list(dict.fromkeys(nodes))

    dependents: dict[str, list[str]] = {node: [] for node in unique_nodes}
    in_degree: dict[str, int] = {node: 0 for node in unique_nodes}
    for node in unique_nodes:
        for parent in predecessors.get(node, ()):
            dependents[parent].append(node)
            in_degree[node] += 1

    queue: deque[str] = deque(sorted(node for node in unique_nodes if in_degree[node] == 0))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in dependents[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(unique_nodes):
        cycle_nodes = sorted(set(unique_nodes) - set(order))
        cycle = _find_cycle(cycle_nodes, dependents)
        path = " → ".join(cycle) if cycle else ", ".join(cycle_nodes)
        findings.append(
            _finding(
                "error",
                cycle[0] if cycle else cycle_nodes[0],
                "depends_on",
                f"playbook contains a dependency cycle: {path}",
            )
        )

    roots = {
        step.id for step in steps if isinstance(step.id, str) and step.id and not step.depends_on
    }
    reachable: set[str] = set(roots)
    queue = deque(sorted(roots))
    while queue:
        node = queue.popleft()
        for dependent in dependents.get(node, ()):
            if dependent not in reachable:
                reachable.add(dependent)
                queue.append(dependent)

    for step in steps:
        if not isinstance(step.id, str) or not step.id:
            continue
        if step.id not in reachable:
            findings.append(
                _finding(
                    "warning",
                    step.id,
                    "depends_on",
                    f"step {step.id!r} is unreachable from any root step",
                )
            )


def _find_cycle(nodes: list[str], dependents: dict[str, list[str]]) -> list[str]:
    """Return one concrete cycle path inside the remaining graph."""
    white, gray, black = 0, 1, 2
    color = {node: white for node in nodes}
    allowed = set(nodes)

    for start in nodes:
        if color[start] != white:
            continue
        path = [start]
        color[start] = gray
        stack: list[Iterator[str]] = [iter(dependents.get(start, ()))]
        while stack:
            try:
                nxt = next(stack[-1])
            except StopIteration:
                color[path[-1]] = black
                path.pop()
                stack.pop()
                continue
            if nxt not in allowed or color[nxt] == black:
                continue
            if color[nxt] == gray:
                index = path.index(nxt)
                return path[index:] + [nxt]
            color[nxt] = gray
            path.append(nxt)
            stack.append(iter(dependents.get(nxt, ())))
    return []


# ── references ──────────────────────────────────────────────────────────


def _validate_references(
    steps: list[StepDefinition],
    raw_index: dict[str, Mapping[str, Any]],
    context: _ValidationContext,
    findings: list[Finding],
) -> None:
    """Check every templated reference inside step args and output mappings."""
    for step in steps:
        if not isinstance(step.id, str) or not step.id:
            continue

        if isinstance(step.args, Mapping):
            for key, value in step.args.items():
                for path, body in _walk_string_refs(value, f"args.{key}"):
                    _check_reference(body, step.id, context, path, findings)

        if isinstance(step.output_mapping, Mapping):
            for key, value in step.output_mapping.items():
                if not isinstance(value, str):
                    continue
                for path, body in _walk_string_refs(value, f"output_mapping.{key}"):
                    _check_reference(body, step.id, context, path, findings)

        if isinstance(step.foreach, str):
            for path, body in _walk_string_refs(step.foreach, "foreach"):
                _check_reference(body, step.id, context, path, findings)

        raw_step = raw_index.get(step.id, {})
        declared_outputs = raw_step.get("outputs")
        if isinstance(declared_outputs, Mapping):
            for key, value in declared_outputs.items():
                if not isinstance(value, str):
                    continue
                for path, body in _walk_string_refs(value, f"outputs.{key}"):
                    _check_reference(body, step.id, context, path, findings)


def _validate_playbook_outputs(
    defn: PlaybookDefinition, context: _ValidationContext, findings: list[Finding]
) -> None:
    """Validate top-level output mappings (no dependency ordering applies)."""
    raw = defn.raw if isinstance(defn.raw, Mapping) else {}
    outputs = raw.get("outputs")
    if outputs is None:
        return
    if not isinstance(outputs, Mapping):
        findings.append(
            _finding(
                "warning",
                None,
                "outputs",
                "outputs should be a mapping of names to variable references",
            )
        )
        return
    for key, value in outputs.items():
        if not isinstance(value, str):
            findings.append(
                _finding(
                    "error",
                    None,
                    f"outputs.{key}",
                    "output value must be a variable reference string",
                )
            )
            continue
        for path, body in _walk_string_refs(value, f"outputs.{key}"):
            _check_reference(body, None, context, path, findings)


def _check_reference(
    body: str,
    consumer: str | None,
    context: _ValidationContext,
    field: str,
    findings: list[Finding],
    *,
    allow_bare: bool = False,
) -> None:
    """Validate one ``{{...}}`` expression body."""
    expression = body.strip()
    if not expression:
        findings.append(_finding("error", consumer, field, "empty variable reference"))
        return

    parsed = _parse_reference(expression)
    if parsed is None and allow_bare:
        parsed = _parse_bare_step_reference(expression, context.step_ids)
    if parsed is None:
        findings.append(
            _finding(
                "error",
                consumer,
                field,
                f"unsupported variable reference '{{{{{expression}}}}}' (use "
                "{{target}}, {{inputs.NAME}} or {{steps.STEP.FIELD}})",
            )
        )
        return

    kind = parsed[0]
    if kind == "target":
        if not {"target", "targets"} & set(context.input_specs):
            findings.append(
                _finding(
                    "warning",
                    consumer,
                    field,
                    "{{target}} is used but the playbook declares no 'target' input",
                )
            )
        return

    if kind == "inputs":
        name = parsed[1]
        if name not in context.input_specs:
            hint = _suggestion(name, set(context.input_specs))
            findings.append(
                _finding(
                    "error",
                    consumer,
                    field,
                    f"reference to undeclared input {name!r}{hint}",
                )
            )
        return

    if kind == "options":
        name = parsed[1]
        nested_fields = parsed[2:]
        spec = context.input_specs.get(name)
        if spec is None:
            hint = _suggestion(name, set(context.input_specs))
            findings.append(
                _finding(
                    "error",
                    consumer,
                    field,
                    f"reference to undeclared option input {name!r}{hint}",
                )
            )
            return
        if spec.type not in (None, "object"):
            findings.append(
                _finding(
                    "error",
                    consumer,
                    field,
                    f"option input {name!r} is declared as {spec.type!r}, expected object",
                )
            )
            return
        if nested_fields:
            findings.append(
                _finding(
                    "warning",
                    consumer,
                    field,
                    f"cannot verify nested option field {nested_fields[0]!r} on {name!r}: "
                    "input schema properties are not available for validation",
                )
            )
        return

    step_id = parsed[1]
    nested_fields = parsed[2:]
    if step_id not in context.step_ids:
        hint = _suggestion(step_id, context.step_ids)
        findings.append(
            _finding(
                "error",
                consumer,
                field,
                f"reference to unknown step {step_id!r}{hint}",
            )
        )
        return

    if consumer is not None and step_id not in context.ancestors.get(consumer, set()):
        findings.append(
            _finding(
                "error",
                consumer,
                field,
                f"references step {step_id!r}, which is not a dependency of {consumer!r}",
            )
        )

    if not nested_fields:
        return

    schema = context.output_schemas.get(step_id)
    first_field = nested_fields[0]
    if schema is None:
        findings.append(
            _finding(
                "warning",
                consumer,
                field,
                f"cannot verify field {first_field!r} on step {step_id!r}: "
                "the step declares no output schema",
            )
        )
        return
    if first_field not in schema.fields:
        hint = _suggestion(first_field, set(schema.fields))
        findings.append(
            _finding(
                "error",
                consumer,
                field,
                f"step {step_id!r} has no output field {first_field!r}{hint}",
            )
        )


def _parse_reference(body: str) -> tuple[str, ...] | None:
    """Parse a reference body into a normalised tuple, or ``None`` if invalid."""
    match = _REF_BODY_RE.match(body)
    if match is None:
        return None
    if match.group("target"):
        return ("target",)
    if match.group("input"):
        return ("inputs", match.group("input"))
    if match.group("option"):
        ofields = tuple(part for part in (match.group("ofields") or "").split(".") if part)
        return ("options", match.group("option"), *ofields)
    fields = tuple(part for part in match.group("fields").split(".") if part)
    step_id = match.group("step")
    return ("steps", step_id, *fields)


def _parse_bare_step_reference(body: str, step_ids: set[str]) -> tuple[str, ...] | None:
    """Accept engine-style ``step.field`` references (no ``steps.`` prefix)."""
    match = _BARE_STEP_REF_RE.match(body)
    if match is None or match.group("step") not in step_ids:
        return None
    fields = tuple(part for part in match.group("fields").split(".") if part)
    return ("steps", match.group("step"), *fields)


# ── when conditions ─────────────────────────────────────────────────────


def _validate_foreach(
    step: StepDefinition,
    input_specs: dict[str, _InputSpec],
    findings: list[Finding],
) -> None:
    """Validate a ``foreach`` target against the structured reference grammar.

    Per the DSL spec, ``foreach`` must reference a collection: typically
    ``{{steps.STEP.FIELD}}`` produced by a dependency step (dependency and
    field checks happen later in ``_validate_references``, alongside args and
    output mappings), or ``{{inputs.NAME}}`` where NAME is a declared input
    whose type resolves to ``array``.
    """
    foreach = step.foreach
    if foreach is None:
        return
    if not isinstance(foreach, str) or not (body := foreach.strip()):
        findings.append(
            _finding(
                "error",
                step.id,
                "foreach",
                "foreach must be a variable reference string",
            )
        )
        return
    if body.startswith("{{") and body.endswith("}}"):
        body = body[2:-2].strip()
    if not body:
        findings.append(_finding("error", step.id, "foreach", "empty foreach reference"))
        return
    parsed = _parse_reference(body)
    if parsed is None:
        findings.append(
            _finding(
                "error",
                step.id,
                "foreach",
                f"foreach must reference a collection field, got {foreach!r} "
                "(use {{steps.STEP.FIELD}} or {{inputs.NAME}})",
            )
        )
        return
    kind = parsed[0]
    if kind == "target":
        findings.append(
            _finding(
                "error",
                step.id,
                "foreach",
                "foreach must target an array field, not the target scalar",
            )
        )
        return
    if kind == "inputs":
        name = parsed[1]
        spec = input_specs.get(name)
        if spec is None:
            hint = _suggestion(name, set(input_specs))
            findings.append(
                _finding(
                    "error",
                    step.id,
                    "foreach",
                    f"foreach references undeclared input {name!r}{hint}",
                )
            )
            return
        if spec.type not in (None, "array"):
            findings.append(
                _finding(
                    "error",
                    step.id,
                    "foreach",
                    f"foreach must target an array input, but {name!r} is "
                    f"declared as {spec.type!r}",
                )
            )


def _validate_when(step: StepDefinition, findings: list[Finding]) -> None:
    """Validate a ``when`` condition against the structured-expression grammar."""
    condition = step.when
    if condition is None:
        return
    if not isinstance(condition, str):
        findings.append(_finding("error", step.id, "when", "when must be a string"))
        return

    unsafe = _find_unsafe_token(condition)
    if unsafe is not None:
        findings.append(
            _finding(
                "error",
                step.id,
                "when",
                f"when condition contains disallowed token {unsafe!r}; only structured "
                "field references and comparison operators are allowed",
            )
        )
        return

    match = _WHEN_RE.match(condition.strip())
    if match is None:
        findings.append(
            _finding(
                "error",
                step.id,
                "when",
                "when must have the form '{{steps.STEP.FIELD}} <op> <literal>' with "
                "one of > < >= <= == !=",
            )
        )
        return

    literal = match.group("literal").strip()
    if not _LITERAL_RE.match(literal):
        findings.append(
            _finding(
                "error",
                step.id,
                "when",
                f"invalid comparison literal {literal!r}",
            )
        )
        return

    expression = match.group("braced") or match.group("bare")
    # Bare step refs are validated below through the reference checker; the
    # grammar allows them for compatibility with the engine's condition style.
    body = expression.strip()
    if match.group("bare") and _parse_reference(body) is None:
        if _parse_bare_step_reference(body, set()) is None and body != "target":
            # Fall through to the reference checker, which reports the error
            # with a consistent message.
            pass


# The reference check for ``when`` needs the context, so it runs separately.

# ── limits ──────────────────────────────────────────────────────────────


def _validate_limits(
    steps: list[StepDefinition],
    raw_index: dict[str, Mapping[str, Any]],
    findings: list[Finding],
) -> None:
    """Warn about unbounded iteration and invalid explicit bounds."""
    for step in steps:
        if not isinstance(step.id, str) or not step.id:
            continue
        raw_step = raw_index.get(step.id, {})
        for key in ("max_iterations", "max_loops", "max_items"):
            if key in raw_step and not _is_positive_int(raw_step[key]):
                findings.append(
                    _finding(
                        "error",
                        step.id,
                        key,
                        f"{key} must be a positive integer, got {raw_step[key]!r}",
                    )
                )

        is_iterative = bool(step.foreach) or "while" in raw_step
        if not is_iterative:
            continue
        budget = step.budget if isinstance(step.budget, Mapping) else {}
        bounded = _is_positive_int(raw_step.get("max_iterations")) or _is_positive_int(
            budget.get("max_iterations")
        )
        if not bounded:
            findings.append(
                _finding(
                    "warning",
                    step.id,
                    "max_iterations",
                    "iterative step has no explicit max_iterations; the engine hard cap "
                    "applies but an author-defined bound is recommended",
                )
            )


# ── schema / catalog helpers ────────────────────────────────────────────


def _index_raw_steps(raw: Any) -> dict[str, Mapping[str, Any]]:
    """Index raw step payloads by id for schema/metadata lookups."""
    if not isinstance(raw, Mapping):
        return {}
    raw_steps = raw.get("steps")
    indexed: dict[str, Mapping[str, Any]] = {}
    if isinstance(raw_steps, Mapping):
        for key, value in raw_steps.items():
            if isinstance(value, Mapping):
                step_id = value.get("id", key)
                if isinstance(step_id, str):
                    indexed.setdefault(step_id, value)
    elif isinstance(raw_steps, (list, tuple)):
        for value in raw_steps:
            if not isinstance(value, Mapping):
                continue
            step_id = value.get("id")
            if isinstance(step_id, str):
                indexed.setdefault(step_id, value)
    return indexed


def _build_output_schemas(
    steps: list[StepDefinition],
    raw_index: dict[str, Mapping[str, Any]],
    step_ids: set[str],
) -> dict[str, _OutputSchema | None]:
    """Resolve declared output fields for every step (or ``None`` if unknown)."""
    schemas: dict[str, _OutputSchema | None] = {}
    for step in steps:
        if not isinstance(step.id, str) or not step.id:
            continue
        schema = _schema_from_raw(raw_index.get(step.id, {}))
        if schema is None:
            builtin = _BUILTIN_OUTPUT_SCHEMAS.get(step.type)
            if builtin is not None:
                schema = _OutputSchema(fields=dict(builtin), source=step.type)
        schemas[step.id] = schema
    for step_id in step_ids:
        schemas.setdefault(step_id, None)
    return schemas


def _schema_from_raw(raw_step: Mapping[str, Any]) -> _OutputSchema | None:
    """Extract declared output fields from a raw step payload."""
    declared = raw_step.get("outputs")
    if isinstance(declared, Mapping):
        fields: dict[str, str | None] = {}
        for name, spec in declared.items():
            if not isinstance(name, str):
                continue
            fields[name] = _declared_type(spec)
        if fields:
            return _OutputSchema(fields=fields, source="outputs")
    elif isinstance(declared, (list, tuple)):
        fields = {name: None for name in declared if isinstance(name, str)}
        if fields:
            return _OutputSchema(fields=fields, source="outputs")

    output_schema = raw_step.get("output_schema")
    if isinstance(output_schema, Mapping):
        properties = output_schema.get("properties")
        if isinstance(properties, Mapping):
            fields = {
                name: _declared_type(spec)
                for name, spec in properties.items()
                if isinstance(name, str)
            }
            if fields:
                return _OutputSchema(fields=fields, source="output_schema")
        elif not ({"type", "required", "items", "$schema"} & set(output_schema)):
            fields = {
                name: _declared_type(spec)
                for name, spec in output_schema.items()
                if isinstance(name, str)
            }
            if fields:
                return _OutputSchema(fields=fields, source="output_schema")
    return None


def _declared_type(spec: Any) -> str | None:
    """Best-effort declared type for one schema field."""
    if isinstance(spec, str):
        parsed = _parse_type(spec)
        return parsed[0] if parsed else None
    if isinstance(spec, Mapping):
        declared = spec.get("type")
        if isinstance(declared, str):
            parsed = _parse_type(declared)
            return parsed[0] if parsed else None
    return None


def _resolve_tools(
    defn: PlaybookDefinition,
    steps: list[StepDefinition],
    raw_index: dict[str, Mapping[str, Any]],
    tool_catalog: Iterable[str] | None,
    module_catalog: Iterable[str] | None,
    for_publish: bool,
    findings: list[Finding],
) -> None:
    """Resolve every native tool reference against the (injectable) catalog."""
    catalog: set[str] | None
    if tool_catalog is None:
        catalog, error = _resolve_tool_catalog()
    else:
        catalog, error = _normalise_catalog(tool_catalog), None

    if catalog is None:
        findings.append(
            _finding(
                "error" if for_publish else "warning",
                None,
                "tool_catalog",
                error or "tool catalog is unavailable; tool references were not verified",
            )
        )
        return

    for step in steps:
        if not isinstance(step.id, str) or not step.id:
            continue
        if step.type != "tool":
            continue
        if not step.tool:
            # Already reported by _validate_tool_reference; avoid duplicate noise.
            continue
        if step.tool not in catalog:
            hint = _suggestion(step.tool, catalog)
            findings.append(
                _finding(
                    "error",
                    step.id,
                    "tool",
                    f"tool {step.tool!r} is not registered{hint}",
                )
            )

    if for_publish:
        for step in steps:
            if not isinstance(step.id, str) or not step.id:
                continue
            if step.type == "custom" and step.tool and module_catalog is None:
                findings.append(
                    _finding(
                        "warning",
                        step.id,
                        "tool",
                        f"module {step.tool!r} availability could not be verified "
                        "(no module catalog supplied)",
                    )
                )


def _resolve_tool_catalog() -> tuple[set[str] | None, str | None]:
    """Best-effort resolution of the live tool catalog.

    Tries the global ``registry`` first, then the static ``ALL_TOOLS`` list.
    Import failures are tolerated so the validator remains usable standalone
    (for example in tooling that runs without the MCP dependency installed).
    """
    try:
        from kali_mcp.registry import registry

        names = _normalise_catalog(registry.tool_names())
        if names:
            return names, None
    except Exception:  # noqa: BLE001 - tolerant by design
        pass

    try:
        from kali_mcp.tools import ALL_TOOLS

        names = _normalise_catalog(
            getattr(tool, "name", None) for tool in ALL_TOOLS if getattr(tool, "name", None)
        )
        if names:
            return names, None
    except Exception:  # noqa: BLE001 - tolerant by design
        pass

    return None, "tool catalog is unavailable; tool references were not verified"


def _normalise_catalog(catalog: Iterable[str] | None) -> set[str]:
    """Coerce a catalog input into a set of non-empty tool-name strings."""
    if catalog is None:
        return set()
    if isinstance(catalog, str):
        return {catalog} if catalog else set()
    return {name for name in catalog if isinstance(name, str) and name}


# ── misc helpers ────────────────────────────────────────────────────────


def _walk_string_refs(value: Any, path: str) -> Iterator[tuple[str, str]]:
    """Yield ``(field_path, reference_body)`` for every ``{{...}}`` in a value."""
    if isinstance(value, str):
        for match in _REF_RE.finditer(value):
            yield path, match.group(1)
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            yield from _walk_string_refs(nested, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            yield from _walk_string_refs(nested, f"{path}[{index}]")


def _find_unsafe_token(condition: str) -> str | None:
    """Return the first disallowed injection token in a ``when`` condition."""
    for token in _DANGEROUS_SUBSTRINGS:
        if token in condition:
            return token
    match = _DANGEROUS_WORDS_RE.search(condition)
    if match:
        return match.group(0)
    return None


def _parse_type(type_name: str) -> tuple[str, str | None] | None:
    """Parse an input type expression into ``(base, item)`` or ``None``."""
    text = type_name.strip().lower()
    if not text:
        return None
    if text in INPUT_TYPES:
        return text, None
    array_match = _ARRAY_TYPE_RE.match(text)
    if array_match:
        item_text = array_match.group(1)
        if item_text is None:
            return "array", None
        parsed = _parse_type(item_text)
        if parsed is None or parsed[0] == "object":
            return None
        return "array", parsed[0]
    if _OBJECT_TYPE_RE.match(text):
        return "object", None
    return None


def _default_matches_type(value: Any, base_type: str, enum_values: tuple[Any, ...] | None) -> bool:
    """Return ``True`` when a default value is compatible with a declared type."""
    if value is None:
        return True
    if base_type == "string":
        return isinstance(value, str)
    if base_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if base_type == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if base_type == "boolean":
        return isinstance(value, bool)
    if base_type == "enum":
        return enum_values is None or value in enum_values
    if base_type == "array":
        return isinstance(value, (list, tuple))
    if base_type == "object":
        return isinstance(value, Mapping)
    return isinstance(value, str)


def _is_positive_int(value: Any) -> bool:
    """Return ``True`` for positive integers (booleans excluded)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _suggestion(value: str, candidates: Iterable[str]) -> str:
    """Build a 'did you mean' suffix from close matches."""
    options = sorted(candidate for candidate in candidates if isinstance(candidate, str))
    close = difflib.get_close_matches(value, options, n=1)
    return f" (did you mean {close[0]!r}?)" if close else ""


def _finding(severity: Severity, step_id: str | None, field: str | None, message: str) -> Finding:
    """Create one finding in the canonical contract shape."""
    return {
        "severity": severity,
        "step_id": step_id,
        "field": field,
        "message": message,
    }


def _finalise(findings: list[Finding], steps: list[StepDefinition]) -> list[Finding]:
    """Deduplicate and deterministically order findings (errors first)."""
    order = {
        step.id: index for index, step in enumerate(steps) if isinstance(step.id, str) and step.id
    }
    seen: set[tuple[Any, ...]] = set()
    unique: list[Finding] = []
    for finding in findings:
        key = (
            finding["severity"],
            finding["step_id"],
            finding["field"],
            finding["message"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    severity_rank = {"error": 0, "warning": 1}
    unique.sort(
        key=lambda item: (
            severity_rank.get(item["severity"], 2),
            order.get(item["step_id"], len(order)),
            item["field"] or "",
            item["message"],
        )
    )
    return unique
