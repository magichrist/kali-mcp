"""Shared pytest configuration for kali-mcp tests.

Adds the repository root to sys.path so `config`, `tools`, `execution`, etc.
import correctly regardless of where pytest is invoked from.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _register_all_tools() -> None:
    """Populate the global tool registry, mirroring server.py's startup wiring.

    Integration tests (playbook engine, parallel_execute) resolve tools via the
    global registry, which is normally populated only when server.py runs.
    """
    from registry import registry
    from tools import ALL_TOOLS

    for tool in ALL_TOOLS:
        registry.register(tool)


_register_all_tools()
