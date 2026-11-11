"""Playbook DSL authoring guide for AI agents.

This module is the single source of truth for the playbook DSL documentation
consumed by:

- ``tools/playbook_authoring.py``  (tool descriptions / validation hints)
- ``prompts.py``                   (``playbook_authoring`` prompt template)
- ``resources.py``                 (``kali://playbook/dsl`` resource)

The canonical *parser* is ``kmcp.workflow.yaml_loader`` and the canonical
*executor* is ``kmcp.workflow.dag_executor`` — keep this guide in sync with
both when the DSL evolves.
"""

from __future__ import annotations

PLAYBOOK_DSL_GUIDE = """\
# Playbook DSL — agent authoring guide

A playbook is a DAG of steps the kmcp workflow engine executes with
depends_on ordering, conditional execution, retry, per-step budget, and
resume support. Definitions are the same whether you run one inline via
``playbook_engine`` or save one to the Studio catalog.

## Lifecycle (author → validate → publish → run)

1. ``playbook_create`` — create a draft row in the Studio catalog
   (playbook_id, name, description/category/author). Drafts are invisible
   to ``playbook_run`` until published.
2. ``playbook_validate`` — check a definition. Pass ``for_publish: true``
   to apply the stricter publish-time rules (every tool must exist in the
   server tool catalog; every ``type: custom`` step must declare a module).
   Fix every `error` finding; `warning` findings are advisory.
3. ``playbook_publish`` — publish an immutable version (semantic version
   string, e.g. ``1.0``). Publishing runs a final ``for_publish``
   validation and fails if it does not pass.
4. ``playbook_run`` — run the published playbook against a target
   (``playbook: <playbook_id>``). Agents can also run any definition
   ad-hoc, without a catalog entry, via ``playbook_engine``.

## Top-level structure

```yaml
name: quick_http_probe          # human-readable name
version: "1.0"
inputs:                          # playbook parameters
  target:                        # rich spec (recommended)
    type: string
    required: true
    description: Target to assess
    source: agent                # who supplies it: agent | operator | static
  ports:                         # ... or a plain description string
    description: "optional, default top1000"
execution:                       # optional engine tuning
  max_parallel: 4                # concurrency cap (default 4)
  timeout: 900                   # whole-playbook budget in seconds (default 900)
  resume: true                   # allow resuming interrupted runs (default true)
  max_iterations: 200            # foreach/loop safety cap
steps:
  - id: resolve                  # REQUIRED, unique within the playbook
    ...
```

## Step types (``type`` field)

| type | purpose |
|------|---------|
| ``tool`` (default) | call a registered server tool (nmap, httpx, nuclei, ...) |
| ``shell`` | run a shell command template (no registered tool required) |
| ``scope_check`` | scope boundary check |
| ``finding_correlation`` | correlate results into findings |
| ``assessment_report`` | generate the assessment report |
| ``custom`` | call an internal module (Python-backed reusable operation) |

``tool`` steps need ``tool`` + ``args``. ``custom``-style steps declare
``module`` (e.g. ``module: host_enumeration``) — the engine resolves the
module through the internal module registry (YAML definitions under
``playbooks/modules/<category>/<id>.yaml`` declaring the underlying native
``tool``, default ``inputs``, and ``outputs``). Step ``args`` are merged
over the module's declared input defaults; step args take precedence.

## Shell steps (``type: "shell"``)

```yaml
- id: probe
  type: shell
  command: "nmap -Pn -p {ports} {target} -oG -"
  inputs:
    target: "{{target}}"       # playbook input -> or a literal "10.0.0.1"
    ports: "80,443"            # or an upstream ref "resolve.http_services"
  filter:                      # optional output extraction
    type: grep                 # currently: grep
    pattern: "(?P<host>\\\\S+) \\\\(\\\\d+\\\\)/open"
    first_only: true
```

- ``command`` placeholders (``{name}``) are filled from ``inputs``.
- ``inputs`` values may be: a literal, a playbook input (``{{target}}`` or
  the bare input name), or an upstream output ref (``step.field``).
- ``filter`` extracts fields from stdout into the step result so downstream
  ``step.field`` references and ``output_mapping`` work. The step fails if
  any placeholder is left unfilled.

## Substitution and references

- ``{{target}}`` — in ``args`` (all step types) and shell ``inputs``, the
  target the playbook run was launched with. Never shell-interpolated
  inside commands yourself — pass inputs instead.
- ``step.field`` / ``step.nested.path`` — dotted reference into a prior
  step's structured output (works in ``args`` values, shell ``inputs``,
  ``foreach``, and ``when``).

## Step fields reference

| field | type | default | meaning |
|-------|------|---------|---------|
| id | str | required | unique step id, referenced by depends_on/when/foreach |
| type | str | ``tool`` | one of the six types above |
| tool | str | — | server tool name for ``type: tool`` |
| module | str | — | internal module name for ``type: custom`` |
| depends_on | list[str] | [] | steps that must finish first |
| when | str | — | condition; skip the step when it evaluates false |
| args | dict | {} | tool/module arguments (supports ``{{target}}`` and refs) |
| command / inputs / filter | — | — | shell-step fields (see above) |
| parallel | bool | false | hint that this step may run concurrently with others |
| foreach | str | — | iterate the step over an upstream output array |
| output_mapping | dict | {} | map step-result fields into playbook outputs |
| retry | int | 0 | retries on failure (>= 0) |
| on_failure | str | ``abort`` | ``continue`` / ``skip_dependents`` / ``abort`` |
| checkpoint | bool | false | persist result so an interrupted run can resume |
| budget | dict | — | per-step limits, e.g. ``budget: {timeout: 120}`` seconds. Default step budget: ``max(30, execution.timeout / step_count)`` |

## ``when`` conditions (structured only)

String like ``<dotted.field> <op> <value>`` evaluated against prior step
results — e.g. ``httpx.http_services_count > 0``. Operators: ``>``, ``<``,
``>=``, ``<=``, ``==``, ``!=``. The parser *rejects* any condition
containing shell-ish characters or code-ish substrings (``$``, backticks,
parens, ``exec``, ``eval``, ``import``, ``os.``, ``sys.``, ...) — keep
conditions strictly to field references, operators, and literal values.

## foreach (fan-out)

``foreach`` iterates the step once per element of an upstream output array,
with a hard iteration cap to prevent runaway loops. The reference may be a
dotted field ref (``resolve.http_services``) or a playbook input ref
(``{{inputs.custom_modules}}``). Combine with ``parallel: true`` for
concurrent iteration.

## Legacy format

Old playbooks may use ``steps: [{id, tools: [{tool, args}, ...]}]``; the
loader accepts it and lifts the single tool entry into step ``tool``/``args``
fields. Always author in the canonical per-step ``tool``/``args`` format.

## Minimal working example

```yaml
name: quick_http_probe
version: "1.0"
inputs:
  target:
    type: string
    required: true
    description: Host or domain to probe
steps:
  - id: scope
    type: scope_check                # builtin step — no tool args needed
    checkpoint: true
  - id: httpx
    tool: httpx                      # a registered server tool
    depends_on: [scope]
    args:
      target: "{{target}}"
      status_code: true
    budget:
      timeout: 120
    checkpoint: true
  - id: correlate
    type: finding_correlation        # builtin step
    depends_on: [httpx]
    checkpoint: true
  - id: report
    type: assessment_report          # builtin step — produces the report
    depends_on: [correlate]
```

Then: ``playbook_create`` → ``playbook_validate`` (definition above) →
``playbook_publish`` (version ``1.0``) → ``playbook_run`` with
``playbook: quick_http_probe`` and ``target: <the target>``.
"""
