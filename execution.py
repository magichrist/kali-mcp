"""Single execution engine — hardened for resilience.

3-layer defense:
  1. asyncio.wait_for with enforced timeout (tool can't hang server)
  2. Watchdog thread kills stuck executions
  3. Semaphore prevents resource exhaustion from concurrent calls
"""

from __future__ import annotations

import asyncio
import gc
import logging
import resource
import threading
import time
import uuid
from typing import Any

from config import config
from models import ExecutionResult, utc_now_iso
from security import sanitize_command_parts
from logging_utils import log_execution
from utils.process import kill_process_tree

logger = logging.getLogger("kali_mcp.execution")

MAX_OUTPUT = 100_000  # 100KB per stream


class ExecutionEngine:
    """Runs subprocess commands with timeout, captures output, returns structured results.

    Hardened against:
    - Tool subprocess hangs (asyncio.wait_for timeout)
    - Tool subprocess zombies (kill_process_tree)
    - Event loop starvation (semaphore with max_concurrent)
    - Stuck executions (watchdog thread)
    """

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._active: dict[str, str] = {}  # request_id → tool
        self._request_times: dict[str, float] = {}  # request_id → start monotonic
        self._watchdog_running = False
        self._request_count = 0
        self._error_count = 0
        self._lock = threading.Lock()

    def _start_watchdog(self) -> None:
        """Start background watchdog that kills stuck executions."""
        if self._watchdog_running:
            return
        self._watchdog_running = True

        def _watchdog():
            while self._watchdog_running:
                time.sleep(5)
                now = time.monotonic()
                stuck = [
                    (rid, self._active.get(rid, "unknown"), t)
                    for rid, t in list(self._request_times.items())
                    if now - t > config.max_timeout + 30
                ]
                for rid, tool, t in stuck:
                    logger.warning(
                        "watchdog: request=%s tool=%s stuck for %.0fs — force cleaning",
                        rid, tool, now - t,
                    )
                    self._active.pop(rid, None)
                    self._request_times.pop(rid, None)

        t = threading.Thread(target=_watchdog, daemon=True, name="exec-watchdog")
        t.start()

    def _cleanup_request(self, req_id: str) -> None:
        self._active.pop(req_id, None)
        self._request_times.pop(req_id, None)

    async def execute(
        self,
        command: list[str],
        tool: str = "generic_command",
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        request_id: str | None = None,
    ) -> ExecutionResult:
        """Execute a command and return structured result. Never raises."""
        self._start_watchdog()
        req_id = request_id or uuid.uuid4().hex[:12]
        effective_timeout = min(timeout or config.default_timeout, config.max_timeout)
        command = sanitize_command_parts(command)
        command_str = " ".join(command)

        logger.info(
            "request=%s executing tool=%s command=%s timeout=%d",
            req_id, tool, command_str, effective_timeout,
        )

        start_time = utc_now_iso()
        start_monotonic = time.monotonic()

        try:
            async with self._semaphore:
                self._active[req_id] = tool
                self._request_times[req_id] = start_monotonic

                try:
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            *command,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=cwd,
                            env=env,
                        )
                    except FileNotFoundError as e:
                        binary = command[0] if command else "unknown"
                        elapsed = time.monotonic() - start_monotonic
                        logger.warning(
                            "request=%s tool=%s binary not found: %s",
                            req_id, tool, binary,
                        )
                        result = ExecutionResult(
                            tool=tool, command=command_str, stdout="",
                            stderr=f"Binary not found: {binary} — install it with 'apt install {binary}' or check PATH",
                            exit_code=-1, success=False, timed_out=False,
                            duration=round(elapsed, 3),
                            start_time=start_time, end_time=utc_now_iso(),
                        )
                        log_execution(result)
                        return result

                    try:
                        stdout_bytes, stderr_bytes = await asyncio.wait_for(
                            proc.communicate(),
                            timeout=effective_timeout,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "request=%s tool=%s timed out after %ds, killing process",
                            req_id, tool, effective_timeout,
                        )
                        # Kill without waiting — communicate() was cancelled,
                        # transport state is inconsistent, proc.wait() would hang
                        try:
                            proc.kill()
                        except (ProcessLookupError, OSError):
                            pass
                        stdout_bytes, stderr_bytes = b"", b""

                        elapsed = time.monotonic() - start_monotonic
                        result = ExecutionResult(
                            tool=tool,
                            command=command_str,
                            stdout="",
                            stderr=f"Timed out after {effective_timeout}s",
                            exit_code=-1,
                            success=False,
                            timed_out=True,
                            duration=round(elapsed, 3),
                            start_time=start_time,
                            end_time=utc_now_iso(),
                        )
                        log_execution(result)
                        logger.info(
                            "request=%s tool=%s TIMED OUT duration=%.3fs",
                            req_id, tool, result.duration,
                        )
                        return result

                    elapsed = time.monotonic() - start_monotonic
                    stdout_str = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT]
                    stderr_str = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT]

                    result = ExecutionResult(
                        tool=tool,
                        command=command_str,
                        stdout=stdout_str,
                        stderr=stderr_str,
                        exit_code=proc.returncode or 0,
                        success=(proc.returncode == 0),
                        timed_out=False,
                        duration=round(elapsed, 3),
                        start_time=start_time,
                        end_time=utc_now_iso(),
                    )

                    log_execution(result)
                    logger.info(
                        "request=%s tool=%s exit_code=%d success=%s duration=%.3fs",
                        req_id, tool, result.exit_code, result.success, result.duration,
                    )
                    return result

                finally:
                    self._cleanup_request(req_id)

        except asyncio.CancelledError:
            logger.warning("request=%s execution cancelled", req_id)
            elapsed = time.monotonic() - start_monotonic
            with self._lock:
                self._error_count += 1
            return ExecutionResult(
                tool=tool, command=command_str, stdout="",
                stderr="Execution cancelled",
                exit_code=-1, success=False, timed_out=False,
                duration=round(elapsed, 3),
                start_time=start_time, end_time=utc_now_iso(),
            )
        except Exception as e:
            elapsed = time.monotonic() - start_monotonic
            logger.exception("request=%s unexpected execution error", req_id)
            with self._lock:
                self._error_count += 1
            return ExecutionResult(
                tool=tool, command=command_str, stdout="",
                stderr=f"Internal error: {type(e).__name__}",
                exit_code=-1, success=False, timed_out=False,
                duration=round(elapsed, 3),
                start_time=start_time, end_time=utc_now_iso(),
            )
        finally:
            self._cleanup_request(req_id)
            with self._lock:
                self._request_count += 1

    @property
    def active_count(self) -> int:
        return len(self._active)

    def get_stuck_executions(self) -> list[dict]:
        """Return list of potentially stuck executions."""
        now = time.monotonic()
        stuck = []
        for req_id, tool in list(self._active.items()):
            start_t = self._request_times.get(req_id, now)
            elapsed = now - start_t
            if elapsed > config.default_timeout:
                stuck.append({
                    "request_id": req_id,
                    "tool": tool,
                    "elapsed_seconds": round(elapsed, 1),
                })
        return stuck

    def force_cleanup(self) -> int:
        """Force cleanup of all tracked requests. Returns count cleaned."""
        count = len(self._active)
        self._active.clear()
        self._request_times.clear()
        gc.collect()
        return count

    def get_stats(self) -> dict:
        """Get engine statistics."""
        with self._lock:
            return {
                "active_executions": self.active_count,
                "total_requests": self._request_count,
                "total_errors": self._error_count,
                "max_concurrent": config.max_concurrent,
            }


engine = ExecutionEngine()
