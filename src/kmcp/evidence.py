"""Evidence artifact store for kmcp v2.0.

Stores raw stdout/stderr and other execution artifacts as files on disk,
with metadata tracked in the SQLite evidence_artifacts table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from kmcp.config import config

EVIDENCE_DIR = Path(config.artifact_dir) / "evidence"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _evidence_dir() -> Path:
    """Resolve the evidence directory from current config (call-time)."""
    return Path(config.artifact_dir) / "evidence"


def _sanitize_fs(name: str) -> str:
    """Sanitize a string for safe use as a filesystem path component."""
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "unnamed"
    return cleaned[:120]


def get_evidence(evidence_id: str) -> dict | None:
    """Look up an evidence row by evidence_id from SQLite.

    Returns the row dict or None if not found.
    """
    from kmcp.db import manager as dbm

    db = dbm.get_db()
    if db is None:
        return None
    try:
        row = db.get_evidence(evidence_id)
        return dict(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def store_evidence(
    tool: str,
    target: str,
    artifact_type: str = "stdout",
    content: str = "",
    assessment_id: str | None = None,
    job_id: str | None = None,
    content_path: str | None = None,
) -> str:
    """Store an evidence artifact and return its evidence_id.

    The raw content is written to a file under EVIDENCE_DIR.
    Metadata is recorded in the SQLite evidence_artifacts table via
    ``db_manager.add_evidence_artifact`` (called by persist.py).

    Returns the opaque evidence_id (e.g. ``evidence_<12-hex>``).
    """
    evidence_id = f"evidence_{uuid.uuid4().hex[:12]}"

    # Determine storage path
    if content_path is None:
        safe_target = _sanitize_fs(target)
        safe_tool = _sanitize_fs(tool)
        base_dir = _evidence_dir()
        rel_dir = base_dir / f"{assessment_id or 'no-assessment'}"
        rel_dir = rel_dir / f"{safe_tool}_{safe_target}"
        full_dir = rel_dir
        full_dir.mkdir(parents=True, exist_ok=True)
        content_path = str(full_dir / f"{evidence_id}_{artifact_type}.txt")

    # Write content to disk
    try:
        Path(content_path).parent.mkdir(parents=True, exist_ok=True)
        Path(content_path).write_text(content, encoding="utf-8")
    except OSError:
        pass

    # Record in SQLite
    try:
        from kmcp.db import manager as dbm

        db = dbm.get_db()
        if db is not None:
            content_bytes = content.encode("utf-8")
            db.add_evidence_artifact(
                evidence_id=evidence_id,
                tool=tool,
                target=target,
                artifact_type=artifact_type,
                content_path=content_path,
                content_size=len(content_bytes),
                assessment_id=assessment_id,
                job_id=job_id,
            )
    except Exception:
        pass

    # Also deposit to vault for cross-agent discovery
    try:
        from kmcp.utils.vault import vault_write

        vault_write(
            category=f"evidence/{_sanitize_fs(target)}",
            name=evidence_id,
            content={
                "evidence_id": evidence_id,
                "tool": tool,
                "target": target,
                "artifact_type": artifact_type,
                "content_path": content_path,
                "captured_at": _now_utc(),
                "assessment_id": assessment_id,
                "job_id": job_id,
            },
            target=target,
            tool=tool,
            tags=f"evidence:{artifact_type},tool:{tool}",
        )
    except Exception:
        pass

    return evidence_id


__all__ = ["EVIDENCE_DIR", "get_evidence", "store_evidence"]
