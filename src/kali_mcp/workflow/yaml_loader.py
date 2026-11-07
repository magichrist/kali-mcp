"""YAML playbook definition parser and validator for kali-mcp v2.0.

Loads playbook definitions from YAML (or dict) and validates the step schema.
Conditions are validated to ensure they reference structured outputs only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Allowed step types
VALID_STEP_TYPES = {
    "tool",
    "shell",
    "scope_check",
    "finding_correlation",
    "assessment_report",
    "custom",
}

# Allowed on_failure values
VALID_ON_FAILURE = {"continue", "skip_dependents", "abort"}

# Structured-output field references allowed in `when` conditions.
# These are dotted paths into prior step results, e.g. "resolve.http_services_count"
# (matched anywhere inside the condition, so operator forms like
# "httpx.http_services_count > 0" validate too)
_WHEN_FIELD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


class PlaybookError(ValueError):
    """Raised when a playbook definition is invalid."""


@dataclass
class StepDefinition:
    id: str
    tool: str | None = None
    module: str | None = None
    type: str = "tool"
    depends_on: list[str] = field(default_factory=list)
    when: str | None = None
    parallel: bool = False
    foreach: str | None = None
    output_mapping: dict[str, Any] = field(default_factory=dict)
    retry: int = 0
    on_failure: str = "abort"
    checkpoint: bool = False
    budget: dict[str, Any] = field(default_factory=dict)
    args: dict[str, Any] = field(default_factory=dict)
    # Shell-node fields (type="shell"):
    #   command — shell template, ``{name}`` placeholders filled from ``inputs``
    #   inputs  — placeholder name → literal, playbook input name (``{{target}}``
    #             or bare name), or upstream output ref (``step.field``)
    #   filter  — output extraction: {"type": "grep", "pattern": ...,
    #             "first_only": bool}; extracted fields land in the step result
    #             so downstream refs (``step.field``) and output_mapping work
    command: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    filter: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in VALID_STEP_TYPES:
            raise PlaybookError(f"Invalid step type: {self.type}")
        if self.on_failure not in VALID_ON_FAILURE:
            raise PlaybookError(f"Invalid on_failure: {self.on_failure}")
        if self.retry < 0:
            raise PlaybookError("retry must be >= 0")
        if self.when is not None and not _is_structured_condition(self.when):
            raise PlaybookError(
                f"when condition must reference structured outputs only: {self.when}"
            )


def _is_structured_condition(condition: str) -> bool:
    """Return True if the condition references structured output fields only.

    Allowed: dotted field paths like "resolve.http_services_count > 0"
    Rejected: anything resembling shell execution, backticks, $(), etc.
    """
    # Reject shell-ish constructs
    dangerous = ["$", "`", "(", ")", "exec", "eval", "import", "__", "subprocess",
                 "os.", "sys.", "open(", "write(", "rm ", "curl ", "wget "]
    lower = condition.lower()
    for d in dangerous:
        if d in lower:
            return False
    # Must contain at least one dotted field reference
    return bool(_WHEN_FIELD_RE.search(condition))


@dataclass
class PlaybookDefinition:
    name: str
    version: str
    inputs: dict[str, Any]
    execution: dict[str, Any]
    steps: list[StepDefinition]
    raw: dict[str, Any]

    @property
    def max_parallel(self) -> int:
        return int(self.execution.get("max_parallel", 4))

    @property
    def timeout(self) -> int:
        return int(self.execution.get("timeout", 900))

    @property
    def resume(self) -> bool:
        return bool(self.execution.get("resume", True))


def load_playbook(source: str | dict[str, Any]) -> PlaybookDefinition:
    """Load a playbook from a YAML string, file path, or dict.

    Returns a validated PlaybookDefinition.
    """
    if isinstance(source, dict):
        data = source
    elif source.endswith((".yaml", ".yml")):
        with open(source, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    else:
        data = yaml.safe_load(source)

    if not isinstance(data, dict):
        raise PlaybookError("Playbook must be a mapping")

    name = data.get("name", "playbook")
    version = str(data.get("version", "1.0"))
    inputs = data.get("inputs", {}) or {}
    execution = data.get("execution", {}) or {}
    steps_raw = data.get("steps", []) or []

    steps: list[StepDefinition] = []
    seen_ids: set[str] = set()
    for step_raw in steps_raw:
        step_id = step_raw.get("id")
        if not step_id:
            raise PlaybookError("Every step must have an id")
        if step_id in seen_ids:
            raise PlaybookError(f"Duplicate step id: {step_id}")
        seen_ids.add(step_id)

        # Validate depends_on references exist
        deps = step_raw.get("depends_on", []) or []
        for dep in deps:
            if dep not in seen_ids and dep not in {s.id for s in steps}:
                # Allow forward references; validated in DAG executor
                pass

        # Backward-compatible: legacy playbooks use {"tools": [{tool, args}, ...]};
        # canonical format uses {"tool": ..., "args": ...} per step.
        tool = step_raw.get("tool")
        args = step_raw.get("args", {}) or {}
        if tool is None:
            tools = step_raw.get("tools")
            if isinstance(tools, (list, tuple)) and tools:
                first = tools[0]
                if isinstance(first, Mapping):
                    tool = first.get("tool")
                    args = first.get("args", {}) or {}

        step = StepDefinition(
            id=step_id,
            tool=tool,
            module=step_raw.get("module"),
            type=step_raw.get("type", "tool"),
            depends_on=list(deps),
            when=step_raw.get("when"),
            parallel=bool(step_raw.get("parallel", False)),
            foreach=step_raw.get("foreach"),
            output_mapping=step_raw.get("output_mapping", {}) or {},
            retry=int(step_raw.get("retry", 0)),
            on_failure=step_raw.get("on_failure", "abort"),
            checkpoint=bool(step_raw.get("checkpoint", False)),
            budget=step_raw.get("budget", {}) or {},
            args=step_raw.get("args", {}) or {},
            command=step_raw.get("command"),
            inputs=step_raw.get("inputs", {}) or {},
            filter=step_raw.get("filter", {}) or {},
        )

        steps.append(step)

    return PlaybookDefinition(
        name=name,
        version=version,
        inputs=inputs,
        execution=execution,
        steps=steps,
        raw=data,
    )


# ── internal module resolution ─────────────────────────────────────────

MODULES_DIR = Path(__file__).resolve().parent.parent / "playbooks" / "modules"


def load_module(module_id: str) -> dict[str, Any] | None:
    """Locate and load an internal module definition YAML by id.

    Module definitions live under ``playbooks/modules/<category>/<id>.yaml``
    and declare (among other fields) the native ``tool`` that implements the
    module, plus default ``inputs`` and ``outputs``. Returns the parsed
    mapping, or ``None`` when no module definition exists for ``module_id``.
    """
    if not module_id:
        return None
    candidates = list(MODULES_DIR.glob(f"*/{module_id}.yaml")) + list(
        MODULES_DIR.glob(f"*/{module_id}.yml")
    )
    if not candidates:
        return None
    with open(candidates[0], "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else None
