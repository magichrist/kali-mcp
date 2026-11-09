"""Internal-module binding registry for the DAG workflow engine (Playbook Studio).

Internal modules are reusable workflow operations implemented in Python under
``src/kali_mcp/playbooks/modules/`` (e.g. ``dns.resolve``, ``target.validate``).
The DAG engine executes ``type="custom"`` steps that declare a module reference
through this registry — this is the same execution infrastructure used by
native ``type="tool"`` steps, not a second engine.

Module contract
----------------

A module package exposes:

- ``register()`` — called once by :func:`load_builtin_modules`; the package
  body registers its operations here via :func:`register`.
- Operations are plain async-compatible callables with signature
  ``run(ctx, **inputs) -> dict`` returning structured, JSON-serialisable
  output only.

Optional module context
------------------------

``run`` receives a :class:`ModuleContext` with execution identifiers. Modules
must never execute outside this contract (no ambient shell, no arbitrary code).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kali_mcp.workflow.yaml_loader import PlaybookError

logger = logging.getLogger(__name__)


class ModuleError(PlaybookError):
    """Raised when a module lookup or execution fails in the registry."""


@dataclass(frozen=True)
class ModuleContext:
    """Execution context handed to every module invocation."""

    assessment_id: str | None = None
    job_id: str | None = None
    playbook_name: str | None = None
    scope_check: Callable[[str], None] | None = None
    """Optional callable that raises when a target violates the scope."""


@dataclass(frozen=True)
class ModuleSpec:
    """One registered internal-module operation."""

    name: str
    fn: Callable[..., dict[str, Any]]
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


_REGISTRY: dict[str, ModuleSpec] = {}


def register(
    name: str,
    fn: Callable[..., dict[str, Any]],
    *,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> None:
    """Register a module operation.

    Re-registering the same ``name`` with the *same* callable is tolerated
    (idempotent importing); registering a *different* callable under an
    existing name raises :class:`ModuleError` to protect execution semantics.
    """
    if not name or not isinstance(name, str):
        raise ModuleError("module name must be a non-empty string")
    if not callable(fn):
        raise ModuleError(f"module {name!r} fn must be callable")

    existing = _REGISTRY.get(name)
    if existing is not None and existing.fn is not fn:
        raise ModuleError(f"module {name!r} is already registered with a different implementation")

    schemas_are_valid = (input_schema is None or isinstance(input_schema, dict)) and (
        output_schema is None or isinstance(output_schema, dict)
    )
    if not schemas_are_valid:
        raise ModuleError(f"module {name!r} schemas must be dicts or None")

    _REGISTRY[name] = ModuleSpec(
        name=name, fn=fn, input_schema=input_schema, output_schema=output_schema
    )


def has(name: str) -> bool:
    """Return ``True`` when ``name`` is registered."""
    return name in _REGISTRY


def execute(
    name: str,
    ctx: ModuleContext,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Run a registered module operation synchronously (async-aware).

    Sync modules run inline; coroutine functions are executed on a fresh
    event loop via :func:`asyncio.run` when none is already running.
    """
    spec = _REGISTRY.get(name)
    if spec is None:
        raise ModuleError(f"module not registered: {name}")

    if not isinstance(inputs, dict):
        raise ModuleError(f"module {name!r} inputs must be a mapping")
    if spec.input_schema:
        _check_required(spec.name, spec.input_schema, inputs)

    result = spec.fn(ctx, **inputs)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    if not isinstance(result, dict):
        raise ModuleError(f"module {name!r} must return a dict, got {type(result).__name__}")
    return result


async def execute_async(
    name: str,
    ctx: ModuleContext,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Async variant of :func:`execute` designed for engine dispatch."""
    spec = _REGISTRY.get(name)
    if spec is None:
        raise ModuleError(f"module not registered: {name}")
    if not isinstance(inputs, dict):
        raise ModuleError(f"module {name!r} inputs must be a mapping")
    if spec.input_schema:
        _check_required(spec.name, spec.input_schema, inputs)

    result = spec.fn(ctx, **inputs)
    if asyncio.iscoroutine(result):
        result = await result
    if not isinstance(result, dict):
        raise ModuleError(f"module {name!r} must return a dict, got {type(result).__name__}")
    return result


def _check_required(name: str, schema: dict[str, Any], inputs: dict[str, Any]) -> None:
    """Minimal required-input validation from a JSON-schema-ish spec."""
    required = schema.get("required")
    if not isinstance(required, (list, tuple)):
        return
    missing = [k for k in required if k not in inputs or inputs.get(k) in (None, "")]
    if missing:
        raise ModuleError(f"module {name!r} missing required input(s): {', '.join(missing)}")


def list_modules() -> list[dict[str, Any]]:
    """List registered modules (name + schema availability)."""
    return [
        {
            "name": spec.name,
            "has_input_schema": spec.input_schema is not None,
            "has_output_schema": spec.output_schema is not None,
        }
        for spec in sorted(_REGISTRY.values(), key=lambda s: s.name)
    ]


def clear() -> None:
    """Drop all registrations (test helper)."""
    _REGISTRY.clear()
    global _BUILTIN_LOADED
    _BUILTIN_LOADED = False


_BUILTIN_LOADED = False


def load_builtin_modules(*, reload: bool = False) -> list[str]:
    """Import module packages under ``kali_mcp.playbooks.modules`` and call
    their ``register()`` hooks.

    Tolerates packages that do not exist or fail to import (log-only skip) so
    partial module implementations never break engine startup. Returns the
    list of packages that registered successfully.
    """
    global _BUILTIN_LOADED
    if _BUILTIN_LOADED and not reload:
        return []

    _BUILTIN_LOADED = True
    registered: list[str] = []
    try:
        from kali_mcp.playbooks import modules as modules_pkg
    except ImportError as exc:  # pragma: no cover - package is always present
        logger.warning("modules package unavailable: %s", exc)
        return registered

    pkg_path = getattr(modules_pkg, "__path__", None)
    if pkg_path is None:
        return registered

    import pkgutil

    for mod_info in pkgutil.iter_modules(list(pkg_path)):
        if not mod_info.ispkg:
            continue
        full_name = f"kali_mcp.playbooks.modules.{mod_info.name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:  # noqa: BLE001 - tolerate partial modules
            logger.warning("skip module package %s: %s", full_name, exc)
            continue
        register_fn = getattr(module, "register", None)
        if register_fn is None:
            continue
        try:
            register_fn()
            registered.append(mod_info.name)
        except Exception as exc:  # noqa: BLE001 - tolerate partial modules
            logger.warning("skip module %s registration: %s", full_name, exc)
    return registered


__all__ = [
    "ModuleContext",
    "ModuleError",
    "ModuleSpec",
    "clear",
    "execute",
    "execute_async",
    "has",
    "list_modules",
    "load_builtin_modules",
    "register",
]
