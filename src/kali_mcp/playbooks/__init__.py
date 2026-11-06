"""Internal playbook engine (black-box to agents).

Agents never import from this package directly. It is used exclusively by
playbook_run to execute assessments internally.
"""

from kali_mcp.playbooks.registry import (
    get_playbook,
    list_playbooks,
    register_playbook,
    register_module,
    get_module,
    PlaybookNotFound,
    ModuleNotFound,
)
from kali_mcp.playbooks.engine import PlaybookEngine

__all__ = [
    "get_playbook",
    "list_playbooks",
    "register_playbook",
    "register_module",
    "get_module",
    "PlaybookEngine",
    "PlaybookNotFound",
    "ModuleNotFound",
]
