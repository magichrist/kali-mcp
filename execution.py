"""Single execution engine — all tools use this."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from config import config
from models import ExecutionResult, utc_now_iso
from security import sanitize_command_parts
from logging_utils import log_execution
from utils.process import kill_process_tree

logger = logging.getLogger("kali_mcp.execution")

MAX_OUTPUT = 100_000  # 100KB per stream to prevent memory blowup


class ExecutionEngine:
    """Runs subprocess commands with timeout, captures output, returns structured results."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(config.max_concurrent)

    async def execute(
        self,
        command: list[str],
        tool: str = "generic_command",
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute a command and return structured result. Never raises."""
        effective_timeout = min(timeout or config.default_timeout, config.max_timeout)
        command = sanitize_command_parts(command)
        command_str = " ".join(command)

        logger.info("executing tool=%s command=%s timeout=%d", tool, command_str, effective_timeout)

        start_time = utc_now_iso()
        start_monotonic = asyncio.get_event_loop().time()

        try:
            async with self._semaphore:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )

                timed_out = False
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=effective_timeout,
                    )
                except asyncio.TimeoutError:
                    timed_out = True
                    await kill_process_tree(proc.pid)
                    stdout_bytes = b""
                    stderr_bytes = f"Timed out after {effective_timeout} seconds".encode()

                end_time = utc_now_iso()
                duration = asyncio.get_event_loop().time() - start_monotonic

                # Truncate output to prevent memory blowup
                if stdout_bytes and len(stdout_bytes) > MAX_OUTPUT:
                    stdout_bytes = stdout_bytes[:MAX_OUTPUT] + b"\n... [truncated at 100KB]"
                if stderr_bytes and len(stderr_bytes) > MAX_OUTPUT:
                    stderr_bytes = stderr_bytes[:MAX_OUTPUT] + b"\n... [truncated at 100KB]"

                result = ExecutionResult(
                    tool=tool,
                    command=command_str,
                    stdout=stdout_bytes.decode("utf-8", errors="replace"),
                    stderr=stderr_bytes.decode("utf-8", errors="replace"),
                    exit_code=proc.returncode or 0,
                    success=(proc.returncode == 0),
                    timed_out=timed_out,
                    duration=duration,
                    start_time=start_time,
                    end_time=end_time,
                )

                log_execution(result)
                return result

        except Exception as e:
            # Last resort — never let an exception escape and crash the ASGI server
            logger.exception("CRITICAL: execution engine failed for tool=%s", tool)
            end_time = utc_now_iso()
            duration = asyncio.get_event_loop().time() - start_monotonic
            return ExecutionResult(
                tool=tool,
                command=command_str,
                stdout="",
                stderr=f"Internal error: {e}",
                exit_code=1,
                success=False,
                timed_out=False,
                duration=duration,
                start_time=start_time,
                end_time=end_time,
            )


engine = ExecutionEngine()
