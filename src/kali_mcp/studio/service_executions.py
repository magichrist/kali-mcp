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


__all__ = [
    "list_executions",
    "get_execution",
    "list_steps",
    "get_step",
    "list_artifacts",
    "cancel_execution",
    "resume_execution",
]
