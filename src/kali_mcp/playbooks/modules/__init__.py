"""Internal workflow modules used by DAG playbook ``custom`` steps.

Each subpackage exports a ``register()`` hook that binds its handler(s) into
:mod:`kali_mcp.workflow.modules_runtime`. Subpackages are imported lazily by
the runtime wiring layer; importing this package has no side effects.
"""
