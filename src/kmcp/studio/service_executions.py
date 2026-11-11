"""Execution monitoring service (Phase 7).

Reads from ``workflow_executions`` / ``workflow_step_executions`` plus the
legacy ``scans`` table to give operators a live view of running playbooks:
list, detail, per-step state, artifacts, cancel, resume.

Pure business logic — no HTTP routing. Routes land in ``studio/api.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from kmcp.db.manager import DBManager

logger = logging.getLogger("kmcp.studio.service_executions")


def list_executions(
    db: DBManager,
    *,
    status: str | None = None,
    playbook_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List workflow executions, newest first."""
    cur = db.conn.cursor()
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if playbook_id:
        clauses.append("playbook_id = ?")
        params.append(playbook_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = cur.execute(
        f"SELECT * FROM workflow_executions {where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["inputs"] = _loads_if_str(r.get("inputs"))
        r["outputs"] = _loads_if_str(r.get("outputs"))
        out.append(r)
    return out


def _loads_if_str(val: Any) -> Any:
    """Parse a JSON string back into an object; leave non-strings untouched."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return val
    return val


def get_execution(db: DBManager, execution_id: str) -> dict[str, Any] | None:
    cur = db.conn.cursor()
    row = cur.execute(
        "SELECT * FROM workflow_executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    # Drop internal plumbing columns from the API surface — keep the response
    # compact and context-friendly (execution_id, playbook_id, status, inputs,
    # outputs, trigger, debug, timestamps only).
    for key in ("id", "job_id", "assessment_id", "profile_id", "started_at"):
        data.pop(key, None)
    # inputs/outputs are stored as JSON strings in SQLite; parse them back so
    # the API returns real objects instead of double-encoded strings.
    data["inputs"] = _loads_if_str(data.get("inputs"))
    data["outputs"] = _loads_if_str(data.get("outputs"))
    steps = []
    for s in list_steps(db, execution_id):
        s = dict(s)
        for key in ("id", "execution_id", "step_type", "inputs"):
            s.pop(key, None)
        s["outputs"] = _loads_if_str(s.get("outputs"))
        steps.append(s)
    data["steps"] = steps
    data["artifacts"] = list_artifacts(db, execution_id)
    return data


def list_steps(db: DBManager, execution_id: str) -> list[dict[str, Any]]:
    cur = db.conn.cursor()
    rows = cur.execute(
        "SELECT * FROM workflow_step_executions WHERE execution_id = ? ORDER BY id ASC",
        (execution_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_step(db: DBManager, execution_id: str, step_id: str) -> dict[str, Any] | None:
    cur = db.conn.cursor()
    row = cur.execute(
        "SELECT * FROM workflow_step_executions WHERE execution_id = ? AND step_id = ?",
        (execution_id, step_id),
    ).fetchone()
    return dict(row) if row else None


def list_artifacts(db: DBManager, execution_id: str) -> list[dict[str, Any]]:
    cur = db.conn.cursor()
    rows = cur.execute(
        "SELECT * FROM evidence_artifacts WHERE assessment_id = ? OR job_id = ?",
        (execution_id, execution_id),
    ).fetchall()
    return [dict(r) for r in rows]


def cancel_execution(db: DBManager, execution_id: str) -> bool:
    cur = db.conn.cursor()
    cur.execute(
        "UPDATE workflow_executions SET status='cancelled', completed_at=? "
        "WHERE execution_id=? AND status IN ('running','pending')",
        (db._now_utc(), execution_id),
    )
    db.conn.commit()
    updated = cur.rowcount > 0
    if updated:
        logger.info("Cancelled execution %s", execution_id)
    return updated


def resume_execution(db: DBManager, execution_id: str) -> dict[str, Any] | None:
    """Return the persisted run so the engine can resume from checkpoint."""
    run = db.load_workflow_run(execution_id)
    if run is None:
        return None
    exec_row = get_execution(db, execution_id)
    if exec_row is None:
        return None
    return {"execution": exec_row, "checkpoint": run}


# ── Start execution (Phase 7 / 08_FILE_PLAN: "start (delegates to engine)") ─


def _extract_step_outputs(step_res: dict[str, Any]) -> dict[str, Any] | None:
    """Pull useful output data out of a step result for storage and UI display.

    Step results from the DAG engine don't carry a top-level ``outputs`` key,
    so ``step_res.get("outputs")`` is always ``None``. This extracts the
    meaningful fields per step type:

    * shell — ``stdout``, ``stderr``, ``exit_code``, plus any filter-named
      capture groups
    * tool / module — MCP ``content[0].text`` which is a JSON-serialized
      ``ExecutionResult`` (stdout/stderr/exit_code/etc.)
    * scope_check / finding_correlation / assessment_report / custom — the
      step result dict minus internal metadata keys
    """
    if not isinstance(step_res, dict):
        return None

    # Explicit outputs field (future-proof)
    if "outputs" in step_res and step_res["outputs"] is not None:
        return step_res["outputs"]

    # Shell step: stdout/stderr/exit_code are the outputs
    if step_res.get("type") == "shell" or "stdout" in step_res:
        out: dict[str, Any] = {}
        for key in ("stdout", "stderr", "exit_code", "duration", "started_at"):
            if key in step_res:
                out[key] = step_res[key]
        meta = {
            "step",
            "type",
            "tool",
            "command",
            "stdout",
            "stderr",
            "exit_code",
            "duration",
            "started_at",
            "error",
        }
        for key, val in step_res.items():
            if key not in meta:
                out[key] = val
        return out if out else None

    # Tool / module step: MCP response — content[0].text is JSON of ExecutionResult
    content = step_res.get("content")
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = content[0].get("text", "")
        if text:
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                pass

    # Fallback: return the step result minus internal metadata
    meta = {"step", "error", "skipped", "reason", "scope_violation", "timed_out"}
    out = {k: v for k, v in step_res.items() if k not in meta}
    return out if out else None


def _merge_required_inputs(defn: Any, supplied: dict[str, Any]) -> None:
    """Raise ValueError when declared required inputs are missing.

    Declared inputs may be supplied directly; the single ``target`` input is
    mirrored as ``targets`` so the DAG engine's ``{{target}}`` substitution
    applies to step args (same contract as the MCP ``playbook_run`` path).
    """
    merged = supplied or {}
    for key, val in merged.items():
        defn.inputs[key] = val
    target_value = defn.inputs.get("target")
    if target_value and "targets" not in merged:
        defn.inputs["targets"] = target_value
    missing = sorted(
        name
        for name, spec in (defn.inputs or {}).items()
        if isinstance(spec, dict) and spec.get("required") and name not in merged
    )
    if missing:
        raise ValueError(f"missing required playbook inputs: {', '.join(missing)}")


async def start_execution(
    db: DBManager,
    playbook_id: str,
    inputs: dict[str, Any] | None = None,
    profile_id: str | None = None,
    version_id: int | str | None = None,
    trigger: str | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    """Start (and await) a run of a published Studio playbook.

    Loads the current published version (or ``version_id``), validates the
    declared required inputs, creates a durable ``workflow_executions`` row,
    runs the playbook through the DAG engine, records per-step executions,
    and finalizes the row status. Raises ``LookupError`` for unknown
    playbooks/versions and ``ValueError`` for invalid input.

    ``trigger`` records where the run came from (e.g. ``studio``, ``api``)
    and ``debug`` marks manual/test runs so they can be distinguished from
    AI/agent-initiated runs in the UI.
    """
    row = db.get_playbook(playbook_id)
    if row is None:
        raise LookupError(f"playbook {playbook_id!r} not found")
    if row.get("status") != "published":
        raise ValueError(f"playbook {playbook_id!r} is not published (status: {row.get('status')})")

    if version_id is not None:
        version = db.get_playbook_version(version_id)
        if version is None or version.get("playbook_id") != playbook_id:
            raise LookupError(f"version {version_id!r} not found for {playbook_id!r}")
    else:
        current = row.get("current_version_id")
        if current is None:
            raise ValueError(f"playbook {playbook_id!r} is published but has no current version")
        version = db.get_playbook_version(current)

    definition = version.get("definition")
    if isinstance(definition, str):
        import json as _json

        try:
            definition = _json.loads(definition)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"invalid stored definition: {exc}") from exc

    from kmcp.workflow.yaml_loader import load_playbook

    try:
        defn = load_playbook(definition)
    except Exception as exc:
        raise ValueError(f"invalid playbook definition: {exc}") from exc

    _merge_required_inputs(defn, inputs)

    import uuid as _uuid

    execution_id = f"wexec_{_uuid.uuid4().hex[:12]}"
    job_id = f"job_{_uuid.uuid4().hex[:12]}"
    assessment_id = f"assessment_{_uuid.uuid4().hex[:12]}"

    db.create_workflow_execution(
        execution_id,
        playbook_id,
        int(version["id"]) if isinstance(version.get("id"), int) else 0,
        job_id=job_id,
        assessment_id=assessment_id,
        profile_id=profile_id,
        inputs=inputs or {},
        status="running",
        started_at=db._now_utc(),
        trigger=trigger,
        debug=debug,
    )

    from kmcp.workflow.dag_executor import run_playbook_async
    from kmcp.workflow.scope_gate import ScopeViolationError

    try:
        res = await run_playbook_async(defn)
    except ScopeViolationError as exc:
        db.update_workflow_execution(
            execution_id,
            status="failed",
            error=str(exc),
            completed_at=db._now_utc(),
        )
        raise ValueError(f"scope violation: {exc}") from exc
    except Exception as exc:
        db.update_workflow_execution(
            execution_id,
            status="failed",
            error=str(exc),
            completed_at=db._now_utc(),
        )
        raise

    import json as _json2

    try:
        payload = _json2.loads(res.stdout or "{}") or {}
    except _json2.JSONDecodeError:
        payload = {
            "status": "completed" if res.success else "failed",
            "results": [],
            "step_results": {},
        }
    status = payload.get("status") or ("completed" if res.success else "failed")
    payload.setdefault("status", status)
    payload["summary"] = payload.get("summary") or {
        "steps": payload.get("steps", []),
        "completed_steps": payload.get("completed_steps", 0),
    }

    db.update_workflow_execution(
        execution_id,
        status=status,
        outputs={
            "results": payload.get("results"),
            "summary": payload.get("summary"),
        },
        completed_at=db._now_utc(),
    )
    for step_id, step_res in (payload.get("step_results") or {}).items():
        if isinstance(step_res, dict):
            step_error = step_res.get("error")
            try:
                db.record_step_execution(
                    execution_id,
                    step_id,
                    tool_id=str(step_res.get("tool")) if step_res.get("tool") else None,
                    status="failed" if step_error else "completed",
                    error=str(step_error) if step_error else None,
                    outputs=_extract_step_outputs(step_res),
                    started_at=db._now_utc(),
                    completed_at=db._now_utc(),
                )
            except Exception:
                logger.exception("step record failed for %s", step_id)

    exec_row = get_execution(db, execution_id)
    return {
        "execution": exec_row,
        "job_id": job_id,
        "assessment_id": assessment_id,
        "status": status,
        "payload": payload,
    }


__all__ = [
    "cancel_execution",
    "get_execution",
    "get_step",
    "list_artifacts",
    "list_executions",
    "list_steps",
    "resume_execution",
    "start_execution",
]
