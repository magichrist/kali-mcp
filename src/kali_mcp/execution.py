"""Single execution engine — hardened for resilience.

3-layer defense:
  1. asyncio.wait_for with enforced timeout (tool can't hang server)
  2. Watchdog thread kills stuck executions
  3. Semaphore prevents resource exhaustion from concurrent calls
"""

from __future__ import annotations

import asyncio
import contextvars
import gc
import inspect
import logging
import os
import threading
import time
import uuid

from kali_mcp.config import config
from kali_mcp.logging_utils import log_execution
from kali_mcp.models import ExecutionResult, utc_now_iso
from kali_mcp.security import sanitize_command_parts
from kali_mcp.utils.process import kill_process_tree

logger = logging.getLogger("kali_mcp.execution")

MAX_OUTPUT = 100_000  # 100KB per stream

# Per-request progress callback, set by the MCP handler so tool executions
# report progress without each tool needing to thread the callback through.
_progress_ctx: contextvars.ContextVar = contextvars.ContextVar("kali_mcp_progress", default=None)


def set_progress_cb(cb) -> contextvars.Token | None:
    """Set the current task's progress callback; returns a token to reset."""
    if cb is None:
        return None
    return _progress_ctx.set(cb)


def reset_progress_cb(token) -> None:
    if token is not None:
        _progress_ctx.reset(token)


async def _call_progress(progress_cb, completed: int, total: int) -> None:
    """Invoke a progress callback, supporting sync and async callables."""
    result = progress_cb(completed, total)
    if inspect.isawaitable(result):
        await result


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
        self._procs: dict[str, asyncio.subprocess.Process] = {}  # request_id → process
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
                        rid,
                        tool,
                        now - t,
                    )
                    self._active.pop(rid, None)
                    self._request_times.pop(rid, None)

        t = threading.Thread(target=_watchdog, daemon=True, name="exec-watchdog")
        t.start()

    def _cleanup_request(self, req_id: str) -> None:
        self._active.pop(req_id, None)
        self._request_times.pop(req_id, None)
        self._procs.pop(req_id, None)

    async def execute(
        self,
        command: list[str] | str,
        tool: str = "generic_command",
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        request_id: str | None = None,
        progress_cb: object | None = None,
    ) -> ExecutionResult:
        """Execute a command and return structured result. Never raises.
        If command is a str, runs via create_subprocess_shell (for shell commands).
        If command is a list, runs via create_subprocess_exec (for direct binary exec).
        progress_cb, if given, is called as progress_cb(completed, total) over time.
        """
        self._start_watchdog()
        req_id = request_id or uuid.uuid4().hex[:12]
        try:
            effective_timeout = min(int(timeout or config.default_timeout), config.max_timeout)
        except (ValueError, TypeError):
            effective_timeout = config.default_timeout

        use_shell = isinstance(command, str)
        command_str = command if use_shell else " ".join(command)
        if not use_shell:
            command = sanitize_command_parts(command)

        if cwd is not None and not cwd.strip():
            cwd = None

        logger.info(
            "request=%s executing tool=%s command=%s timeout=%d shell=%s",
            req_id,
            tool,
            command_str,
            effective_timeout,
            use_shell,
        )

        start_time = utc_now_iso()
        start_monotonic = time.monotonic()
        if progress_cb is None:
            progress_cb = _progress_ctx.get()
        if progress_cb is not None:
            try:
                await _call_progress(progress_cb, 0, 100)
            except Exception:
                progress_cb = None

        try:
            async with self._semaphore:
                self._active[req_id] = tool
                self._request_times[req_id] = start_monotonic

                try:
                    exec_env = env if env is not None else os.environ.copy()
                    system_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/games:/usr/games"
                    existing = exec_env.get("PATH", "")
                    exec_env["PATH"] = f"{existing}:{system_path}" if existing else system_path

                    try:
                        if use_shell:
                            proc = await asyncio.create_subprocess_exec(
                                "/bin/bash",
                                "-c",
                                command,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                cwd=cwd,
                                env=exec_env,
                                start_new_session=True,
                            )
                        else:
                            proc = await asyncio.create_subprocess_exec(
                                *command,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                                cwd=cwd,
                                env=exec_env,
                                start_new_session=True,
                            )
                        self._procs[req_id] = proc
                    except FileNotFoundError:
                        elapsed = time.monotonic() - start_monotonic
                        if use_shell:
                            binary = "/bin/bash"
                            hint = "install it with 'apt install bash'"
                        else:
                            binary = command[0] if command else "unknown"
                            hint = f"install it with 'apt install {binary}' or check PATH"
                            logger.warning(
                                "request=%s tool=%s binary not found: %s",
                                req_id,
                                tool,
                                binary,
                            )
                            result = ExecutionResult(
                                tool=tool,
                                command=command_str,
                                stdout="",
                                stderr=f"Binary not found: {binary} — {hint}",
                                exit_code=-1,
                                success=False,
                                timed_out=False,
                                duration=round(elapsed, 3),
                                start_time=start_time,
                                end_time=utc_now_iso(),
                            )
                            log_execution(result)
                            return result

                    heartbeat_task = None
                    if progress_cb is not None:

                        async def _heartbeat():
                            try:
                                interval = max(min(effective_timeout / 20.0, 5.0), 0.25)
                                for step in range(1, 20):
                                    await asyncio.sleep(interval)
                                    await _call_progress(progress_cb, min(step * 5, 95), 100)
                            except Exception:
                                pass

                        heartbeat_task = asyncio.create_task(_heartbeat())

                    try:
                        stdout_bytes, stderr_bytes = await asyncio.wait_for(
                            proc.communicate(),
                            timeout=effective_timeout,
                        )
                    except (TimeoutError, asyncio.TimeoutError):
                        logger.warning(
                            "request=%s tool=%s timed out after %ds, killing process",
                            req_id,
                            tool,
                            effective_timeout,
                        )
                        # Kill the entire process tree — the subprocess runs in
                        # its own session, so this cannot hit the server itself
                        from kali_mcp.utils.process import kill_process_tree

                        await kill_process_tree(proc)
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
                            req_id,
                            tool,
                            result.duration,
                        )
                        return result
                    finally:
                        if heartbeat_task is not None:
                            heartbeat_task.cancel()
                            try:
                                await heartbeat_task
                            except (asyncio.CancelledError, Exception):
                                pass
                        if progress_cb is not None:
                            try:
                                await _call_progress(progress_cb, 100, 100)
                            except Exception:
                                pass

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
                        req_id,
                        tool,
                        result.exit_code,
                        result.success,
                        result.duration,
                    )
                    if heartbeat_task is not None:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    return result

                finally:
                    self._cleanup_request(req_id)

        except asyncio.CancelledError:
            logger.warning("request=%s execution cancelled", req_id)
            elapsed = time.monotonic() - start_monotonic
            with self._lock:
                self._error_count += 1
            return ExecutionResult(
                tool=tool,
                command=command_str,
                stdout="",
                stderr="Execution cancelled",
                exit_code=-1,
                success=False,
                timed_out=False,
                duration=round(elapsed, 3),
                start_time=start_time,
                end_time=utc_now_iso(),
            )
        except Exception as e:
            elapsed = time.monotonic() - start_monotonic
            logger.exception("request=%s unexpected execution error", req_id)
            with self._lock:
                self._error_count += 1
            return ExecutionResult(
                tool=tool,
                command=command_str,
                stdout="",
                stderr=f"Internal error: {type(e).__name__}",
                exit_code=-1,
                success=False,
                timed_out=False,
                duration=round(elapsed, 3),
                start_time=start_time,
                end_time=utc_now_iso(),
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
                stuck.append(
                    {
                        "request_id": req_id,
                        "tool": tool,
                        "elapsed_seconds": round(elapsed, 1),
                    }
                )
        return stuck

    def get_active_jobs(self) -> list[dict]:
        """Return a list of currently active tool executions.

        Each entry: {"request_id": str, "tool": str, "elapsed_seconds": float}.
        """
        now = time.monotonic()
        with self._lock:
            return [
                {
                    "request_id": req_id,
                    "tool": tool,
                    "elapsed_seconds": round(now - self._request_times.get(req_id, now), 3),
                }
                for req_id, tool in self._active.items()
            ]

    async def kill_job(self, request_id: str) -> bool:
        """Kill a specific active execution by request ID.

        Terminates the subprocess (process tree) and removes it from tracking.
        Returns True if the job was found and killed, False if unknown.
        """
        proc = None
        with self._lock:
            if request_id not in self._active:
                return False
            proc = self._procs.pop(request_id, None)
            self._active.pop(request_id, None)
            self._request_times.pop(request_id, None)

        if proc is not None:
            try:
                await kill_process_tree(proc)
            except Exception:
                logger.warning("monitor: failed to kill job %s", request_id, exc_info=True)
        return True

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
