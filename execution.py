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
        """Execute a command and return structured result."""
        effective_timeout = min(timeout or config.default_timeout, config.max_timeout)
        command = sanitize_command_parts(command)
        command_str = " ".join(command)

        logger.info("executing tool=%s command=%s timeout=%d", tool, command_str, effective_timeout)

        start_time = utc_now_iso()
        start_monotonic = asyncio.get_event_loop().time()

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
                await kill_process_tree(proc)
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=5.0
                    )
                except Exception:
                    stdout_bytes = b""
                    stderr_bytes = b"Process killed after timeout"
                logger.warning("tool=%s timed_out after %ds", tool, effective_timeout)

        end_time = utc_now_iso()
        duration = round(asyncio.get_event_loop().time() - start_monotonic, 3)

        stdout = stdout_bytes.decode(config.default_encoding, errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode(config.default_encoding, errors="replace") if stderr_bytes else ""
        exit_code = proc.returncode if proc.returncode is not None else -1

        max_output = 1_000_000
        if len(stdout) > max_output:
            stdout = stdout[:max_output] + f"\n... [truncated at {max_output} chars]"
        if len(stderr) > max_output:
            stderr = stderr[:max_output] + f"\n... [truncated at {max_output} chars]"

        result = ExecutionResult(
            tool=tool,
            command=command_str,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            success=exit_code == 0 and not timed_out,
            timed_out=timed_out,
            duration=duration,
            start_time=start_time,
            end_time=end_time,
        )

        logger.info(
            "tool=%s exit_code=%d success=%s duration=%.3fs stdout_len=%d stderr_len=%d",
            tool, exit_code, result.success, duration, len(stdout), len(stderr),
        )

        log_execution(result)

        return result


engine = ExecutionEngine()
