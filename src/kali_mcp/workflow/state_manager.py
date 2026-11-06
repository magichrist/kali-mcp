"""Playbook run-state persistence for checkpoint/resume.

Manages RUN_STATUS persistence across server restarts using SQLite and the
inter-agent vault, so playbooks can resume without repeating completed work.
"""

from __future__ import annotations

from typing import Any

from kali_mcp.db import manager as dbm
from kali_mcp.tools.persist import now_iso
from kali_mcp.utils.vault import vault_write


RUN_STATUS: dict[str, dict[str, Any]] = {}


def save_state(name: str, state: dict[str, Any]) -> None:
    """Persist playbook state to memory and vault (best-effort)."""
    RUN_STATUS[name] = dict(state)
    try:
        vault_write(
            category="playbook_state",
            name=name,
            content=state,
            tags="playbook:state",
        )
    except Exception:  # noqa: BLE001
        pass


def load_state(name: str) -> dict[str, Any] | None:
    """Load playbook state from memory or vault."""
    if name in RUN_STATUS:
        return RUN_STATUS[name]
    try:
        from kali_mcp.utils.vault import vault_read
        content = vault_read("playbook_state", name)
        if content and not content.startswith("{"):
            return None
        import json
        data = json.loads(content)
        RUN_STATUS[name] = data
        return data
    except Exception:  # noqa: BLE001
        return None


def clear_state(name: str) -> None:
    """Clear playbook state."""
    RUN_STATUS.pop(name, None)
