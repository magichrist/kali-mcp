"""Scope enforcement for kali-mcp v2.0.

Provides server-side authorization scoping so that tool execution is
bounded by an explicit policy, not by agent claims.

Scope configuration is loaded from environment variables:

  MCP_SCOPE_ALLOWED_TARGETS  — comma-separated list of allowed target patterns
  MCP_SCOPE_EXCLUDED_TARGETS — comma-separated list of excluded target patterns
  MCP_SCOPE_ALLOWED_OPERATIONS — comma-separated list of allowed tool names
  MCP_SCOPE_POLICY             — safe_active | aggressive | passive (default safe_active)
  MCP_SCOPE_EXPIRATION         — ISO timestamp after which scope is invalid

When no scope is configured, all targets and operations are allowed
(permissive default).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch


@dataclass(frozen=True)
class Scope:
    """Authorization scope for tool execution."""

    allowed_targets: tuple[str, ...] = field(default_factory=tuple)
    excluded_targets: tuple[str, ...] = field(default_factory=tuple)
    allowed_operations: tuple[str, ...] = field(default_factory=tuple)
    policy: str = "safe_active"  # safe_active | aggressive | passive
    expiration: str | None = None

    def is_empty(self) -> bool:
        """True if no constraints are configured (permissive mode)."""
        return (
            not self.allowed_targets
            and not self.excluded_targets
            and not self.allowed_operations
            and self.expiration is None
        )

    def is_expired(self) -> bool:
        """True if the scope has expired."""
        if not self.expiration:
            return False
        try:
            exp = datetime.fromisoformat(self.expiration.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > exp
        except ValueError:
            return False


def load_scope() -> Scope:
    """Load the authorization scope from environment variables.

    Returns a permissive Scope (all allowed) when no scope env vars are set.
    """
    allowed_raw = os.getenv("MCP_SCOPE_ALLOWED_TARGETS", "").strip()
    excluded_raw = os.getenv("MCP_SCOPE_EXCLUDED_TARGETS", "").strip()
    ops_raw = os.getenv("MCP_SCOPE_ALLOWED_OPERATIONS", "").strip()
    policy = os.getenv("MCP_SCOPE_POLICY", "safe_active").strip()
    expiration = os.getenv("MCP_SCOPE_EXPIRATION", "").strip() or None

    allowed_targets = (
        tuple(t.strip() for t in allowed_raw.split(",") if t.strip()) if allowed_raw else ()
    )
    excluded_targets = (
        tuple(t.strip() for t in excluded_raw.split(",") if t.strip()) if excluded_raw else ()
    )
    allowed_operations = (
        tuple(o.strip() for o in ops_raw.split(",") if o.strip()) if ops_raw else ()
    )

    return Scope(
        allowed_targets=allowed_targets,
        excluded_targets=excluded_targets,
        allowed_operations=allowed_operations,
        policy=policy,
        expiration=expiration,
    )


def _matches_pattern(target: str, pattern: str) -> bool:
    """Check if a target matches a glob/CIDR-ish pattern."""
    # Simple glob matching for now (supports *, ?)
    return fnmatch(target, pattern)


def check_scope(
    target: str | None,
    tool_name: str | None = None,
    scope: Scope | None = None,
) -> None:
    """Enforce the authorization scope on a tool call.

    Raises ValueError if the target or operation is out of scope.
    Does nothing (passes) when scope is permissive/empty.

    Args:
        target: The target being operated on (IP, domain, URL, etc.)
        tool_name: The name of the tool being called.
        scope: The Scope to enforce. Loads from env if not provided.

    Raises:
        ValueError: If the target or operation violates the scope.
    """
    if scope is None:
        scope = load_scope()

    # Permissive mode: no constraints configured
    if scope.is_empty():
        return

    # Check expiration
    if scope.is_expired():
        raise ValueError("scope has expired")

    # Check excluded targets first
    if target:
        for pattern in scope.excluded_targets:
            if _matches_pattern(target, pattern):
                raise ValueError(f"target '{target}' is excluded by scope pattern '{pattern}'")

    # Check allowed targets (if any are configured, target must match one)
    if scope.allowed_targets and target:
        if not any(_matches_pattern(target, p) for p in scope.allowed_targets):
            raise ValueError(
                f"target '{target}' is not in allowed scope targets: "
                f"{', '.join(scope.allowed_targets)}"
            )

    # Check allowed operations (if any are configured, tool must be in list)
    if scope.allowed_operations and tool_name and tool_name not in scope.allowed_operations:
        raise ValueError(
            f"operation '{tool_name}' is not in allowed scope operations: "
            f"{', '.join(scope.allowed_operations)}"
        )


def is_target_allowed(target: str | None, scope: Scope | None = None) -> bool:
    """Return True if ``target`` is permitted by ``scope``."""
    if scope is None:
        scope = load_scope()
    if not target:
        return True
    if scope.is_expired():
        return False
    for pattern in scope.excluded_targets:
        if _matches_pattern(target, pattern):
            return False
    if not scope.allowed_targets:
        return True
    return any(_matches_pattern(target, p) for p in scope.allowed_targets)


def is_operation_allowed(tool_name: str | None, scope: Scope | None = None) -> bool:
    """Return True if ``tool_name`` is permitted by ``scope``."""
    if scope is None:
        scope = load_scope()
    if not tool_name:
        return True
    if not scope.allowed_operations:
        return True
    return tool_name in scope.allowed_operations


__all__ = [
    "Scope",
    "check_scope",
    "is_operation_allowed",
    "is_target_allowed",
    "load_scope",
]
