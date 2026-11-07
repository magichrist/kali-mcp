"""Execution monitoring service (Phase 7).

Reads from ``workflow_executions`` / ``workflow_step_executions`` plus the
legacy ``scans`` table to give operators a live view of running playbooks:
list, detail, per-step state, artifacts, cancel, resume.

Pure business logic — no HTTP routing. Routes land in ``studio/api.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from kali_mcp.db.manager import DBManager

logger = logging.getLogger("kali_mcp.studio.service_executions")


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
        f"SELECT * FROM workflow_executions {where} "
        f"ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def get_execution(db: DBManager, execution_id: str) -> dict[str, Any] | None:
    cur = db.conn.cursor()
    row = cur.execute(
        "SELECT * FROM workflow_executions WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["steps"] = list_steps(db, execution_id)
    return data


def list_steps(db: DBManager, execution_id: str) -> list[dict[str, Any]]:
    cur = db.conn.cursor()
    rows = cur.execute(
        "SELECT * FROM workflow_step_executions WHERE execution_id = ? "
        "ORDER BY id ASC",
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
) -> dict[str, Any]:
    """Start (and await) a run of a published Studio playbook.

    Loads the current published version (or ``version_id``), validates the
    declared required inputs, creates a durable ``workflow_executions`` row,
    runs the playbook through the DAG engine, records per-step executions,
    and finalizes the row status. Raises ``LookupError`` for unknown
    playbooks/versions and ``ValueError`` for invalid input.
    """
    row = db.get_playbook(playbook_id)
    if row is None:
        raise LookupError(f"playbook {playbook_id!r} not found")
    if row.get("status") != "published":
        raise ValueError(
            f"playbook {playbook_id!r} is not published (status: {row.get('status')})"
        )

    if version_id is not None:
        version = db.get_playbook_version(version_id)
        if version is None or version.get("playbook_id") != playbook_id:
            raise LookupError(f"version {version_id!r} not found for {playbook_id!r}")
    else:
        current = row.get("current_version_id")
        if current is None:
            raise ValueError(
                f"playbook {playbook_id!r} is published but has no current version"
            )
        version = db.get_playbook_version(current)

    definition = version.get("definition")
    if isinstance(definition, str):
        import json as _json

        try:
            definition = _json.loads(definition)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"invalid stored definition: {exc}") from exc

    from kali_mcp.workflow.yaml_loader import load_playbook

    try:
        defn = load_playbook(definition)
    except Exception as exc:  # noqa: BLE001
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
    )

    from kali_mcp.workflow.dag_executor import run_playbook_async
    from kali_mcp.workflow.scope_gate import ScopeViolationError

    try:
        res = await run_playbook_async(defn)
    except ScopeViolationError as exc:
        db.update_workflow_execution(
            execution_id, status="failed", error=str(exc),
            completed_at=db._now_utc(),
        )
        raise ValueError(f"scope violation: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        db.update_workflow_execution(
            execution_id, status="failed", error=str(exc),
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
                    started_at=db._now_utc(),
                    completed_at=db._now_utc(),
                )
            except Exception:  # noqa: BLE001
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
    "start_execution",
    "list_executions",
    "get_execution",
    "list_steps",
    "get_step",
    "list_artifacts",
    "cancel_execution",
    "resume_execution",
]
