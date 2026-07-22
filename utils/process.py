"""Process cleanup utilities."""

from __future__ import annotations

import asyncio


async def kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill a process and its children."""
    try:
        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (ProcessLookupError, asyncio.TimeoutError):
                pass

            if proc.returncode is None:
                try:
                    proc.kill()
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except (ProcessLookupError, asyncio.TimeoutError):
                    pass
    except Exception:
        pass
