"""Internal playbook engine (black-box to agents).

Agents never import from this package directly. It is used exclusively by
playbook_run to execute assessments internally.
"""

from kali_mcp.playbooks.engine import PlaybookEngine
from kali_mcp.playbooks.registry import (
    ModuleNotFound,
    PlaybookNotFound,
    get_module,
    get_playbook,
    list_playbooks,
    register_module,
    register_playbook,
)

__all__ = [
    "ModuleNotFound",
    "PlaybookEngine",
    "PlaybookNotFound",
    "get_module",
    "get_playbook",
    "list_playbooks",
    "register_module",
    "register_playbook",
]
