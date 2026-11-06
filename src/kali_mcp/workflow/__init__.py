"""DAG-based workflow engine for kali-mcp v2.0.

Upgrades the existing sequential playbook engine into a Directed Acyclic Graph
executor with conditional execution, parallel steps, foreach iteration,
output mapping, checkpoints, resume, retry, and failure handling.

All conditions evaluate against structured outputs — never arbitrary shell
expressions.
"""

from kali_mcp.workflow.dag_executor import (
    PlaybookEngine,
    run_playbook,
    run_playbook_async,
    RUN_STATUS,
    MAX_ITERATIONS,
)
from kali_mcp.workflow.yaml_loader import load_playbook, PlaybookDefinition
from kali_mcp.workflow.modules_runtime import (
    ModuleContext,
    ModuleError,
    list_modules as list_internal_modules,
    load_builtin_modules,
)
from kali_mcp.workflow.scope_gate import ScopeViolationError, assert_target_allowed

__all__ = [
    "PlaybookEngine",
    "run_playbook",
    "run_playbook_async",
    "load_playbook",
    "PlaybookDefinition",
    "RUN_STATUS",
    "MAX_ITERATIONS",
    "ModuleContext",
    "ModuleError",
    "list_internal_modules",
    "load_builtin_modules",
    "ScopeViolationError",
    "assert_target_allowed",
]
