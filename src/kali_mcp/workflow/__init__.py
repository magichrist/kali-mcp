"""DAG-based workflow engine for kali-mcp v2.0.

Upgrades the existing sequential playbook engine into a Directed Acyclic Graph
executor with conditional execution, parallel steps, foreach iteration,
output mapping, checkpoints, resume, retry, and failure handling.

All conditions evaluate against structured outputs — never arbitrary shell
expressions.
"""

from kali_mcp.workflow.dag_executor import (
    MAX_ITERATIONS,
    RUN_STATUS,
    PlaybookEngine,
    run_playbook,
    run_playbook_async,
)
from kali_mcp.workflow.modules_runtime import (
    ModuleContext,
    ModuleError,
    load_builtin_modules,
)
from kali_mcp.workflow.modules_runtime import (
    list_modules as list_internal_modules,
)
from kali_mcp.workflow.scope_gate import ScopeViolationError, assert_target_allowed
from kali_mcp.workflow.yaml_loader import PlaybookDefinition, load_playbook

__all__ = [
    "MAX_ITERATIONS",
    "RUN_STATUS",
    "ModuleContext",
    "ModuleError",
    "PlaybookDefinition",
    "PlaybookEngine",
    "ScopeViolationError",
    "assert_target_allowed",
    "list_internal_modules",
    "load_builtin_modules",
    "load_playbook",
    "run_playbook",
    "run_playbook_async",
]
