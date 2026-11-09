"""Best-effort in-process execution isolation for kali-mcp v2.0 (Phase 5).

This module provides :func:`spawn_isolated`, a thin guard around subprocess
execution that applies per-step resource caps where the platform allows them.

Design goals
------------
* Cross-platform: works on Linux (rlimits via ``preexec_fn``), macOS
  (rlimits skipped gracefully — ``RLIMIT_AS``/``RLIMIT_DATA`` are not
  reliably settable there), and falls back to timeout-only on other platforms.
* Best-effort: a failed rlimit never prevents the command from running; it
  only degrades the isolation guarantee.
* Never raises for the caller: timeouts and rlimit violations surface as a
  non-zero exit / timed-out result, not an exception.

What is NOT implemented
-----------------------
* Container isolation (Docker, Podman, firecracker, ...). That requires a
  container runtime and host privileges and is explicitly out of scope for
  v2.0.0. See ``docs/v2_security_and_infrastructure.md`` ("Container isolation
  where practical" is listed as aspirational, not implemented).
* Dedicated execution workers / non-root execution / restricted mounts /
  network egress policies. These are deployment/ops concerns, not in-process
  guards.

The guard is intentionally modest: it bounds wall-clock time and, on Linux,
address-space / CPU / file-descriptor usage per step. It is a defense-in-depth
layer, not a sandbox.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import resource
import shlex
import shutil
from dataclasses import dataclass

logger = logging.getLogger("kali_mcp.isolation")

_SYSTEM = platform.system()


@dataclass
class StepLimits:
    """Resource caps applied to one isolated step execution.

    All fields are optional; unset fields are not enforced.
    """

    timeout: float | None = None  # wall-clock seconds (enforced everywhere)
    max_memory_bytes: int | None = None  # RLIMIT_AS (Linux only)
    max_cpu_seconds: float | None = None  # RLIMIT_CPU (POSIX)
    max_open_files: int | None = None  # RLIMIT_NOFILE (POSIX)
    max_processes: int | None = None  # RLIMIT_NPROC (POSIX)
    cwd: str | None = None
    env: dict[str, str] | None = None


def _posix_rlimit_preexec(limits: StepLimits):
    """Build a ``preexec_fn`` that applies POSIX rlimits in the child.

    Only applied on Linux; on macOS rlimits are skipped gracefully because
    ``RLIMIT_AS`` is not reliably enforceable there. Any rlimit failure is
    logged and ignored so the command still runs.
    """

    def _apply() -> None:
        if _SYSTEM != "Linux":
            return
        try:
            if limits.max_memory_bytes is not None:
                resource.setrlimit(
                    resource.RLIMIT_AS, (limits.max_memory_bytes, limits.max_memory_bytes)
                )
        except (ValueError, OSError) as exc:
            logger.debug("isolation: RLIMIT_AS not applied: %s", exc)
        try:
            if limits.max_cpu_seconds is not None:
                resource.setrlimit(
                    resource.RLIMIT_CPU,
                    (int(limits.max_cpu_seconds), int(limits.max_cpu_seconds)),
                )
        except (ValueError, OSError) as exc:
            logger.debug("isolation: RLIMIT_CPU not applied: %s", exc)
        try:
            if limits.max_open_files is not None:
                resource.setrlimit(
                    resource.RLIMIT_NOFILE,
                    (limits.max_open_files, limits.max_open_files),
                )
        except (ValueError, OSError) as exc:
            logger.debug("isolation: RLIMIT_NOFILE not applied: %s", exc)
        try:
            if limits.max_processes is not None:
                resource.setrlimit(
                    resource.RLIMIT_NPROC,
                    (limits.max_processes, limits.max_processes),
                )
        except (ValueError, OSError) as exc:
            logger.debug("isolation: RLIMIT_NPROC not applied: %s", exc)

    return _apply


async def spawn_isolated(
    cmd: list[str] | str,
    limits: StepLimits | None = None,
) -> tuple[int, str, str, float]:
    """Run ``cmd`` with best-effort per-step resource caps.

    Returns ``(exit_code, stdout, stderr, duration_seconds)``.

    On Linux the child process gets ``preexec_fn`` rlimits (address space,
    CPU, open files, processes). On macOS rlimits are skipped and only the
    wall-clock timeout is enforced. The timeout is enforced via
    ``asyncio.wait_for`` around ``proc.communicate()``; on expiry the process
    tree is killed.

    This is an in-process guard, not a container. Container isolation is out
    of scope for v2.0.0.
    """
    limits = limits or StepLimits()
    import time

    start = time.monotonic()

    if isinstance(cmd, str):
        argv = shlex.split(cmd)
        use_shell = False
    else:
        argv = list(cmd)
        use_shell = False

    # Resolve the binary so a missing binary is reported cleanly.
    binary = argv[0] if argv else "unknown"
    if not use_shell and not shutil.which(binary):
        return (
            -1,
            "",
            f"Binary not found: {binary}",
            round(time.monotonic() - start, 3),
        )

    try:
        if use_shell:
            proc = await asyncio.create_subprocess_exec(
                "/bin/bash",
                "-c",
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=limits.cwd,
                env=limits.env,
                start_new_session=True,
                preexec_fn=_posix_rlimit_preexec(limits) if _SYSTEM == "Linux" else None,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=limits.cwd,
                env=limits.env,
                start_new_session=True,
                preexec_fn=_posix_rlimit_preexec(limits) if _SYSTEM == "Linux" else None,
            )
    except FileNotFoundError:
        return (
            -1,
            "",
            f"Binary not found: {binary}",
            round(time.monotonic() - start, 3),
        )
    except Exception as exc:
        logger.exception("isolation: failed to spawn %s", binary)
        return -1, "", f"Internal error: {type(exc).__name__}", round(time.monotonic() - start, 3)

    timeout = limits.timeout
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        exit_code = proc.returncode or 0
    except asyncio.TimeoutError:
        # Kill the whole process tree (the child runs in its own session, so
        # this cannot reach the server process itself).
        from kali_mcp.utils.process import kill_process_tree

        try:
            await kill_process_tree(proc)
        except Exception:  # noqa: BLE001
            pass
        try:
            stdout_bytes, stderr_bytes = await proc.communicate()
        except Exception:  # noqa: BLE001
            stdout_bytes, stderr_bytes = b"", b""
        exit_code = -1
        stderr_text = stderr_bytes.decode("utf-8", "replace") if stderr_bytes else ""
        stderr_text = (
            f"Timed out after {timeout}s\n{stderr_text}".strip()
            if stderr_text
            else f"Timed out after {timeout}s"
        )
        duration = round(time.monotonic() - start, 3)
        return exit_code, "", stderr_text, duration

    duration = round(time.monotonic() - start, 3)
    stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
    return exit_code, stdout, stderr, duration


def isolation_available() -> bool:
    """Return True when rlimit-based isolation is enforceable (Linux)."""
    return _SYSTEM == "Linux"
