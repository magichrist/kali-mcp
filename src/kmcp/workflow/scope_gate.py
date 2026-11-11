"""Per-step scope gate for the DAG workflow engine (Playbook Studio).

Thin wrapper over :mod:`kmcp.scope` that the engine applies before *every*
step (native tool, internal module, and foreach item), so dynamically
discovered targets (DNS-resolved IPs, crawled URLs) are re-validated against
the authorization scope at execution time — not only at invocation time.

This module never duplicates ``scope.py`` logic: it delegates to
``check_scope`` and re-raises violations as :class:`ScopeViolationError`
(a :class:`PlaybookError` subclass) so the engine's failure handling applies
uniformly.

Pass-through semantics: when no scope constraints are configured (the
permissive default of ``scope.py``), the gate allows everything and logs a
debug line — existing unscoped executions keep working.
"""

from __future__ import annotations

import logging
from typing import Any

from kmcp.scope import Scope, check_scope, is_target_allowed, load_scope
from kmcp.workflow.yaml_loader import PlaybookError

logger = logging.getLogger(__name__)

#: arg keys carrying potentially sensitive targets that must be scope-checked.
TARGET_ARG_KEYS = frozenset(
    {"target", "targets", "host", "hosts", "urls", "url", "ip", "ips", "cidr", "domain", "domains"}
)


class ScopeViolationError(PlaybookError):
    """Raised when a target violates the active scope policy."""


def assert_target_allowed(
    target: str,
    *,
    scope: Scope | None = None,
    tool_name: str | None = None,
) -> None:
    """Enforce the authorization scope on one target string.

    Raises:
        ScopeViolationError: when ``target`` is out of scope or excluded.
    """
    if scope is None:
        scope = load_scope()
    try:
        check_scope(target, tool_name, scope)
    except ValueError as exc:
        raise ScopeViolationError(str(exc)) from exc


def extract_targets(args: dict[str, Any]) -> list[str]:
    """Extract concrete target values from step arguments.

    Looks at the well-known target-carrying keys (``TARGET_ARG_KEYS``) and
    returns every string value, flattened and de-duplicated. Unresolved
    template references (``{{...}}``) are skipped — they are checked when the
    engine has substituted/allocated their concrete values (e.g. per foreach
    item), or rejected later by the tool-level scope check in ``execution.py``.
    """
    targets: list[str] = []
    for key, value in args.items():
        if str(key).lower() not in TARGET_ARG_KEYS:
            continue
        values: list[Any]
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, (list, tuple)):
            values = [v for v in value if isinstance(v, (str, int))]
        else:
            continue
        for item in values:
            text = str(item).strip()
            if text and not (text.startswith("{{") and text.endswith("}}")):
                targets.append(text)
    seen: set[str] = set()
    unique = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def gate_step_args(
    args: dict[str, Any],
    *,
    step_id: str,
    tool_name: str | None = None,
    scope: Scope | None = None,
) -> None:
    """Scope-check every target-looking argument of a step before execution.

    Never blocks when the scope configuration is permissive (no env vars set):
    the underlying ``scope.py`` check is a no-op in that case.
    """
    if scope is None:
        scope = load_scope()
    if scope.is_empty():
        logger.debug("step %s: no scope configured, gate pass-through", step_id)
        return
    if scope.is_expired():
        raise ScopeViolationError("scope has expired")
    for target in extract_targets(args):
        if not is_target_allowed(target, scope):
            raise ScopeViolationError(
                f"[step {step_id}] target '{target}' is not allowed by the "
                "active scope (excluded or outside allowed targets)"
            )


__all__ = [
    "TARGET_ARG_KEYS",
    "ScopeViolationError",
    "assert_target_allowed",
    "extract_targets",
    "gate_step_args",
    "load_scope",
]
