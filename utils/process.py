"""Process cleanup utilities."""

from __future__ import annotations

import asyncio
import os
import signal


async def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill a process and its entire process group."""
    try:
        if proc.returncode is not None:
            return

        # Try to kill the process group
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            # Fallback to killing just the process
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass

        if proc.returncode is None:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass

            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
    except Exception:
        pass
