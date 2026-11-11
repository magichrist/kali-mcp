"""Playbook service layer (Phase 4): CRUD + publish over DBManager playbooks.

Thin business-logic wrappers around DBManager playbook methods, with
validation and consistent error handling. HTTP/MCP routing is added by
callers (Phase 4 routes).

Extends the existing CRUD (create/get/list/update/delete/publish) with
validate, preview, test, rollback, export, and import.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

import yaml

from kmcp.db.manager import DBManager
from kmcp.models import utc_now_iso
from kmcp.tools.persist import now_iso
from kmcp.workflow import modules_runtime
from kmcp.workflow.dag_executor import PlaybookEngine
from kmcp.workflow.validator import validate_playbook
from kmcp.workflow.yaml_loader import load_playbook

logger = logging.getLogger("kmcp.studio.playbook_service")


# ── CRUD ───────────────────────────────────────────────────────────────────


def create_playbook(db: DBManager, playbook_id: str, name: str, **kwargs: Any) -> dict[str, Any]:
    if not playbook_id or not name:
        raise ValueError("playbook_id and name are required")
    row_id = db.create_playbook(playbook_id, name, **kwargs)
    row = db.get_playbook(playbook_id)
    return row or {"id": row_id, "playbook_id": playbook_id, "name": name}


def get_playbook(db: DBManager, playbook_id: str) -> dict[str, Any] | None:
    return db.get_playbook(playbook_id)


def list_playbooks(db: DBManager, status: str | None = None) -> list[dict[str, Any]]:
    return db.list_playbooks(status=status)


def update_playbook(db: DBManager, playbook_id: str, **fields: Any) -> bool:
    return db.update_playbook(playbook_id, **fields)


def delete_playbook(db: DBManager, playbook_id: str) -> bool:
    return db.delete_playbook(playbook_id)


def publish_version(
    db: DBManager,
    playbook_id: str,
    version: str,
    definition: dict[str, Any],
    **kwargs: Any,
) -> int:
    if not version:
        raise ValueError("version is required")
    if not isinstance(definition, dict):
        raise ValueError("definition must be a dict")
    return db.publish_playbook_version(playbook_id, version, definition=definition, **kwargs)


def get_version(db: DBManager, version_id: int | str) -> dict[str, Any] | None:
    return db.get_playbook_version(version_id)


def list_versions(db: DBManager, playbook_id: str) -> list[dict[str, Any]]:
    return db.list_playbook_versions(playbook_id)


# ── Validation ─────────────────────────────────────────────────────────────


def validate_definition(
    db: DBManager,
    playbook_id: str,
    definition: dict[str, Any],
    *,
    for_publish: bool = False,
) -> dict[str, Any]:
    """Validate a playbook definition and persist the result.

    Returns ``{"valid": bool, "findings": [...]}``. When ``for_publish`` is
    true, stricter publish-time rules apply (catalog must be resolvable,
    custom steps must declare a module/tool reference).
    """
    try:
        defn = load_playbook(definition)
    except Exception as exc:  # noqa: BLE001 — malformed definition
        return {
            "valid": False,
            "findings": [
                {
                    "severity": "error",
                    "step_id": None,
                    "field": "definition",
                    "message": f"invalid playbook definition: {exc}",
                }
            ],
        }

    # Build catalogs from registry for publish-time checks
    try:
        from kmcp.registry import registry as global_registry

        tool_catalog = list(global_registry.tool_names())
    except Exception:  # pragma: no cover - registry always importable
        tool_catalog = None

    # Ensure builtin modules are loaded so module refs can be validated
    modules_runtime.load_builtin_modules()
    module_catalog = list(modules_runtime.list_modules())
    module_names = [m["name"] for m in module_catalog]

    findings = validate_playbook(
        defn,
        tool_catalog=tool_catalog,
        module_catalog=module_names,
        for_publish=for_publish,
    )

    # Persist validation record
    db.conn.cursor().execute(
        """
        INSERT INTO playbook_validations
        (playbook_id, status, errors, validated_at, validated_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            playbook_id,
            "passed" if all(f.get("severity") != "error" for f in findings) else "failed",
            json.dumps(findings),
            now_iso(),
            "studio",
        ),
    )
    db.conn.commit()

    valid = all(f.get("severity") != "error" for f in findings)
    return {"valid": valid, "findings": findings}


# ── Preview (dry-run) ─────────────────────────────────────────────────────


def preview_playbook(
    db: DBManager,
    playbook_id: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Dry-run a playbook: resolve the DAG without executing any tools.

    Returns the resolved step order, dependency graph, and any validation
    issues. No network calls or tool executions are performed.
    """
    try:
        defn = load_playbook(definition)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"invalid playbook definition: {exc}"}

    # Build a temporary engine to resolve the DAG order
    engine = PlaybookEngine()
    try:
        order = engine._topological_sort(defn.steps)
    except Exception as exc:  # noqa: BLE001 — cycle etc.
        return {"ok": False, "error": f"DAG resolution failed: {exc}"}

    if order is None or len(order) != len(defn.steps):
        return {"ok": False, "error": "DAG resolution failed: dependency cycle detected"}

    step_ids = [s.id for s in defn.steps]
    deps = {s.id: list(s.depends_on) for s in defn.steps}

    return {
        "ok": True,
        "playbook_id": playbook_id,
        "step_count": len(defn.steps),
        "execution_order": [step_ids[i] for i in order],
        "dependencies": deps,
        "max_parallel": defn.max_parallel,
        "timeout": defn.timeout,
    }


# ── Test execution (mocked/isolated) ─────────────────────────────────────


def test_playbook(
    db: DBManager,
    playbook_id: str,
    definition: dict[str, Any],
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a playbook against mocked tools for test purposes.

    All module/tool steps return a deterministic mocked result; no external
    binaries are invoked. Returns the engine result payload.
    """
    try:
        defn = load_playbook(definition)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"invalid playbook definition: {exc}"}

    # Register mock modules so custom/module steps dispatch successfully
    modules_runtime.clear()
    for step in defn.steps:
        if step.type == "custom" and step.tool:
            modules_runtime.register(
                step.tool,
                lambda ctx, **kw: {"mocked": True, "step": step.id},
            )

    # Merge provided inputs into the definition
    if inputs:
        defn.inputs = {**defn.inputs, **inputs}

    engine = PlaybookEngine()
    try:
        import asyncio

        result = asyncio.run(engine.run(defn))
        payload = json.loads(result.stdout)
        return {"ok": True, "payload": payload}
    except Exception as exc:
        logger.exception("test playbook failed")
        return {"ok": False, "error": str(exc)}


# ── Rollback ─────────────────────────────────────────────────────────────


def rollback_version(
    db: DBManager,
    playbook_id: str,
    version_id: str | int,
) -> dict[str, Any]:
    """Set the current published version to an earlier published version.

    Returns the rolled-back version row, or raises ValueError if the version
    does not exist or is not published.
    """
    row = db.get_playbook_version(version_id)
    if row is None:
        raise ValueError(f"version {version_id} not found")
    if row["playbook_id"] != playbook_id:
        raise ValueError(f"version {version_id} does not belong to playbook {playbook_id}")

    vid = row["id"] if isinstance(row["id"], int) else int(row["id"])
    db.update_playbook(playbook_id, current_version_id=vid, status="published")
    return db.get_playbook_version(version_id)


# ── Export / Import ───────────────────────────────────────────────────────


def export_playbook(db: DBManager, playbook_id: str) -> dict[str, Any] | None:
    """Export a playbook as a self-contained package (metadata + versions).

    Returns a package dict suitable for JSON serialization, or None if the
    playbook does not exist.
    """
    pb = db.get_playbook(playbook_id)
    if pb is None:
        return None

    versions = db.list_playbook_versions(playbook_id)
    package = {
        "format": "kmcp-playbook-package",
        "version": 1,
        "playbook": {
            "playbook_id": pb["playbook_id"],
            "name": pb["name"],
            "description": pb.get("description"),
            "category": pb.get("category"),
            "author": pb.get("author"),
            "is_builtin": bool(pb.get("is_builtin", 0)),
            "status": pb.get("status"),
        },
        "versions": [],
        "exported_at": utc_now_iso(),
    }
    for v in versions:
        package["versions"].append(
            {
                "version_id": v["version_id"],
                "version": v["version"],
                "definition": json.loads(v["definition"])
                if isinstance(v.get("definition"), str)
                else v.get("definition"),
                "inputs_schema": json.loads(v["inputs_schema"])
                if isinstance(v.get("inputs_schema"), str)
                else v.get("inputs_schema"),
                "notes": v.get("notes"),
                "published_at": v.get("published_at"),
                "published_by": v.get("published_by"),
            }
        )
    # Add integrity hash
    package["hash"] = hashlib.sha256(json.dumps(package, sort_keys=True).encode()).hexdigest()
    return package


def import_playbook(
    db: DBManager,
    package: dict[str, Any],
    *,
    require_approval: bool = True,
) -> dict[str, Any]:
    """Import a playbook package created by :func:`export_playbook`.

    Validates the package hash, imports the playbook as a draft, and imports
    each version. When ``require_approval`` is true, versions are imported
    but not activated (no current_version_id set).

    Returns ``{"ok": bool, "playbook_id": str, "versions_imported": int}``.
    """
    if package.get("format") != "kmcp-playbook-package":
        return {"ok": False, "error": "invalid package format"}

    # Verify integrity hash
    stored_hash = package.pop("hash", None)
    computed = hashlib.sha256(json.dumps(package, sort_keys=True).encode()).hexdigest()
    if stored_hash and stored_hash != computed:
        return {"ok": False, "error": "package integrity hash mismatch"}

    pb_meta = package.get("playbook", {})
    playbook_id = pb_meta.get("playbook_id")
    if not playbook_id:
        return {"ok": False, "error": "package missing playbook_id"}

    # Create/update the playbook as a draft (not published unless approved)
    status = "draft" if require_approval else pb_meta.get("status", "draft")
    db.create_playbook(
        playbook_id=playbook_id,
        name=pb_meta.get("name", playbook_id),
        description=pb_meta.get("description"),
        category=pb_meta.get("category"),
        author=pb_meta.get("author"),
        is_builtin=False,
        status=status,
    )

    versions_imported = 0
    current_vid = None
    for v in package.get("versions", []):
        vid = db.publish_playbook_version(
            playbook_id=playbook_id,
            version=v["version"],
            definition=v["definition"],
            inputs_schema=v.get("inputs_schema"),
            notes=v.get("notes"),
            published_by="import",
            version_id=v.get("version_id"),
        )
        versions_imported += 1
        if not require_approval and current_vid is None:
            current_vid = vid

    if current_vid is not None:
        db.update_playbook(playbook_id, current_version_id=current_vid, status="published")

    return {
        "ok": True,
        "playbook_id": playbook_id,
        "versions_imported": versions_imported,
        "status": status,
    }


# ── YAML playbook seeding ──────────────────────────────────────────────


def seed_builtin_playbooks(
    db: DBManager,
    definitions_dir: str | None = None,
) -> int:
    """Seed existing YAML playbook definitions into the DB as built-ins.

    Existing ``playbooks/definitions/*.yaml`` files are inserted as
    ``is_builtin=1`` rows. The YAML files remain the source of truth; the DB
    provides a uniform catalog view. Built-ins cannot be modified through
    Studio (users draft a copy instead).

    Seeding is idempotent: re-seeding only updates when the YAML hash changes.
    Returns the number of playbooks seeded/updated.
    """
    import glob as _glob
    import os as _os

    if definitions_dir is None:
        # Resolve relative to this package so it works from any CWD
        definitions_dir = str(
            _os.path.join(
                _os.path.dirname(_os.path.abspath(__file__)), "..", "playbooks", "definitions"
            )
        )

    count = 0
    for path in sorted(_glob.glob(os.path.join(definitions_dir, "*.yaml"))) + sorted(
        _glob.glob(os.path.join(definitions_dir, "*.yml"))
    ):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            continue
        pb_id = data.get("id") or os.path.basename(path).replace(".yaml", "").replace(".yml", "")
        name = data.get("name", pb_id)
        version = str(data.get("version", "1.0.0"))
        definition = data
        # Compute a hash to detect changes on re-seed
        hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

        existing = db.get_playbook(pb_id)
        if existing:
            db.update_playbook(
                pb_id,
                name=name,
                description=data.get("description"),
                category="builtin",
                author="system",
                status="published",
            )
            # is_builtin isn't updatable via update_playbook; set it directly
            db.conn.execute(
                "UPDATE playbooks SET is_builtin=1 WHERE playbook_id=?",
                (pb_id,),
            )
            db.conn.commit()
            # Publish version only if no versions exist yet
            versions = db.list_playbook_versions(pb_id)
            if not versions:
                version_id = f"{pb_id}-{version}"
                vid_exists = db.conn.execute(
                    "SELECT 1 FROM playbook_versions WHERE version_id = ?",
                    (version_id,),
                ).fetchone()
                if not vid_exists:
                    db.publish_playbook_version(
                        playbook_id=pb_id,
                        version=version,
                        definition=definition,
                        inputs_schema=data.get("inputs"),
                        notes="Seeded from YAML definition",
                        published_by="system",
                        version_id=version_id,
                    )
            count += 1
        else:
            db.create_playbook(
                playbook_id=pb_id,
                name=name,
                description=data.get("description"),
                category="builtin",
                author="system",
                is_builtin=True,
                status="published",
            )
            version_id = f"{pb_id}-{version}"
            vid_exists = db.conn.execute(
                "SELECT 1 FROM playbook_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            if not vid_exists:
                db.publish_playbook_version(
                    playbook_id=pb_id,
                    version=version,
                    definition=definition,
                    inputs_schema=data.get("inputs"),
                    notes="Seeded from YAML definition",
                    published_by="system",
                    version_id=version_id,
                )
            count += 1
    logger.info("Seeded %d builtin playbooks from %s", count, definitions_dir)
    return count


__all__ = [
    "create_playbook",
    "delete_playbook",
    "export_playbook",
    "get_playbook",
    "get_version",
    "import_playbook",
    "list_playbooks",
    "list_versions",
    "preview_playbook",
    "publish_version",
    "rollback_version",
    "seed_builtin_playbooks",
    "test_playbook",
    "update_playbook",
    "validate_definition",
]
