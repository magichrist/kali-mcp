"""Execution isolation helpers for kali-mcp (best-effort).

Provides per-step resource caps (POSIX rlimits where available; graceful
no-op on platforms without rlimit support, e.g. macOS partial) and a
``spawn_isolated`` stub for future out-of-process step execution.

All helpers are best-effort: failures are swallowed so isolation never
breaks tool execution.
"""

from __future__ import annotations

import os
import resource
import subprocess
import sys
from typing import Any


def apply_resource_caps(
    cpu_seconds: int | None = None,
    memory_bytes: int | None = None,
    open_files: int | None = None,
) -> None:
    """Apply best-effort rlimit caps to the current process."""
    try:
        if cpu_seconds is not None:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    except (ValueError, OSError, AttributeError):
        pass
    try:
        if memory_bytes is not None and hasattr(resource, "RLIMIT_AS"):
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    except (ValueError, OSError, AttributeError):
        pass
    try:
        if open_files is not None and hasattr(resource, "RLIMIT_NOFILE"):
            resource.setrlimit(resource.RLIMIT_NOFILE, (open_files, open_files))
    except (ValueError, OSError, AttributeError):
        pass


def spawn_isolated(
    command: list[str],
    timeout: int = 300,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess:
    """Stub: run a command in a subprocess with timeout.

    Full isolation (containers/namespaces) is not implemented; this is a
    best-effort subprocess wrapper used as a placeholder for future
    out-of-process step execution.
    """
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    try:
        return subprocess.run(
            command,
            timeout=timeout,
            env=merged_env,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=command, returncode=124, stdout=e.stdout or "", stderr="timeout"
        )


__all__ = ["apply_resource_caps", "spawn_isolated"]
