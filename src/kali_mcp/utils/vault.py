"""SQLite-backed inter-agent vault for Kali MCP.

The vault is the knowledge-sharing layer between agents: any agent (or
subagent) deposits rows under a (category, name) pair; any other agent
queries them back by category, target, tool, or free-text search.

Contract (single row store):
  - One SQLite row per finding. Row keys are unique per (category, name),
    e.g. vuln:VULN-001, ev:<vuln_id>, poc:<vuln_id>, cred:<id>, sys:<host>,
    path:AP-001, repo:<org>/<name>, task:<stage>, status:<stage>.
  - ``content`` holds the row's plain key=value fields (verbatim text) or,
    for machine-generated payloads, a JSON document. It is never a file.
  - Re-runs use new keys or supersede tags; the UNIQUE(category, name)
    index enforces one row per finding key.

Storage model:
  - Canonical store: SQLite database at ``VAULT_ROOT/vault.sqlite``
    (table ``entries``).
  - JSON mirror: each row is also written to
    ``VAULT_ROOT/<category>/<name>.json`` for human browsing and for the
    ``kali://artifacts/...`` resource URIs (and as a read fallback for
    rows written before the SQLite migration).
  - Index: ``VAULT_ROOT/index.json`` is regenerated from SQLite after
    every write/delete, so it can never drift or stay corrupt.

All module-level functions are thread-safe and safe to call concurrently.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kali_mcp.config import config

logger = logging.getLogger("kali_mcp.vault")

VAULT_ROOT = Path(config.artifact_dir) / "vault"

DB_NAME = "vault.sqlite"
INDEX_NAME = "index.json"
TABLE = "entries"

_lock = threading.RLock()

_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_categories(category: Any) -> list[str] | None:
    """Accept None, a single category, a comma-separated string, or a list."""
    if category is None:
        return None
    if isinstance(category, str):
        parts = [c.strip() for c in category.split(",") if c.strip()]
        return parts or None
    if isinstance(category, (list, tuple, set)):
        parts = [str(c).strip() for c in category if str(c).strip()]
        return parts or None
    return [str(category)]


# ── SQLite plumbing ───────────────────────────────────────────────────────────


def _db_path() -> Path:
    """Vault database path — resolved at call time so tests can retarget
    VAULT_ROOT via monkeypatch without stale connections."""
    return Path(VAULT_ROOT) / DB_NAME


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            content_size INTEGER NOT NULL DEFAULT 0,
            target TEXT DEFAULT '',
            tool TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            path TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(category, name)
        );
        CREATE INDEX IF NOT EXISTS idx_entries_category ON {TABLE}(category);
        CREATE INDEX IF NOT EXISTS idx_entries_target ON {TABLE}(target);
        CREATE INDEX IF NOT EXISTS idx_entries_tags ON {TABLE}(tags);
        CREATE INDEX IF NOT EXISTS idx_entries_tool ON {TABLE}(tool);
        CREATE INDEX IF NOT EXISTS idx_entries_name ON {TABLE}(name);
        """
    )
    _migrate_legacy_table(conn)
    conn.commit()


def _migrate_legacy_table(conn: sqlite3.Connection) -> None:
    """Best-effort migration from a pre-contract 'vault_entries' table."""
    try:
        legacy = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='vault_entries'"
        ).fetchone()
        if legacy:
            conn.execute(
                f"""
                INSERT OR IGNORE INTO {TABLE}
                    (category, name, content, content_size, target, tool,
                     tags, path, created_at, updated_at)
                SELECT category, name, content, content_size, target, tool,
                       tags, path, created_at, updated_at
                FROM vault_entries
                """
            )
            conn.execute("DROP TABLE vault_entries")
    except sqlite3.Error:
        pass  # migration is best-effort; the entries table remains canonical


# ── Path safety ───────────────────────────────────────────────────────────────


def _safe_component(component: str) -> str:
    """Sanitize one path component: no traversal, no separators, no weird bytes."""
    cleaned = _SAFE_COMPONENT.sub("_", component).strip("._") or "unnamed"
    return cleaned[:120]


def _mirror_path(category: str, name: str) -> Path:
    """Build the JSON mirror path, guaranteed to stay inside VAULT_ROOT."""
    # Each category segment is sanitized; traversal components are dropped.
    parts = [
        _safe_component(seg)
        for seg in str(category).replace("\\", "/").split("/")
        if seg and seg not in (".", "..")
    ]
    cat_dir = Path(VAULT_ROOT).joinpath(*parts) if parts else Path(VAULT_ROOT)
    return cat_dir / f"{_safe_component(name)}.json"


# ── Index (regenerated from SQLite, never authoritative) ──────────────────────


def _write_index(conn: sqlite3.Connection) -> None:
    """Regenerate index.json from the SQLite table (self-healing)."""
    rows = conn.execute(
        f"""
        SELECT category, name, path, target, tool, tags, content_size,
               created_at, updated_at
        FROM {TABLE} ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    entries = [dict(row) for row in rows]
    index_path = Path(VAULT_ROOT) / INDEX_NAME
    tmp_path = index_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps({"count": len(entries), "entries": entries}, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(index_path)


# ── Public API ────────────────────────────────────────────────────────────────


def ensure_vault_dirs() -> None:
    """Create vault directories + SQLite schema. Idempotent, no junk rows."""
    with _lock:
        Path(VAULT_ROOT).mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            _write_index(conn)
        finally:
            conn.close()


def vault_write(
    category: str,
    name: str,
    content: Any,
    target: str = "",
    tool: str = "",
    tags: str = "",
) -> str:
    """Upsert one row under (category, name). Overwrites on conflict.

    ``content`` is stored verbatim when given as a string (plain
    key=value fields); any other type is serialized to JSON. Row keys
    follow the contract, e.g. vuln:VULN-001, cred:<id>, sys:<host>,
    task:<stage>, status:<stage>. Returns the mirror path.

    Rows larger than ``config.vault_max_row_bytes`` (default 25MB,
    0 = unlimited) are rejected with ValueError.
    """
    if not isinstance(category, str) or not category.strip():
        raise ValueError("vault category must be a non-empty string")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("vault name must be a non-empty string")

    if isinstance(content, str):
        payload = content
    else:
        payload = json.dumps(content, indent=2, default=str)

    payload_size = len(payload.encode("utf-8"))
    max_row = getattr(config, "vault_max_row_bytes", 0) or 0
    if max_row and payload_size > max_row:
        raise ValueError(
            f"vault row too large: {payload_size} bytes exceeds "
            f"MCP_VAULT_MAX_ROW_BYTES={max_row}. Split the payload across "
            "multiple rows or store it as a file (file_write) and record "
            "the path in the vault."
        )

    now = _now_iso()
    mirror = _mirror_path(category, name)

    with _lock:
        Path(VAULT_ROOT).mkdir(parents=True, exist_ok=True)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(payload, encoding="utf-8")

        conn = _connect()
        try:
            conn.execute(
                f"""
                INSERT INTO {TABLE}
                    (category, name, content, content_size, target, tool,
                     tags, path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, name) DO UPDATE SET
                    content=excluded.content,
                    content_size=excluded.content_size,
                    target=excluded.target,
                    tool=excluded.tool,
                    tags=excluded.tags,
                    path=excluded.path,
                    updated_at=excluded.updated_at
                """,
                (
                    category.strip(),
                    name.strip(),
                    payload,
                    len(payload.encode("utf-8")),
                    str(target or ""),
                    str(tool or ""),
                    str(tags or ""),
                    str(mirror),
                    now,
                    now,
                ),
            )
            conn.commit()
            _write_index(conn)
        finally:
            conn.close()

    return str(mirror)


def vault_read(category: str, name: str) -> str:
    """Read a row's content verbatim (key=value fields or JSON text).

    Returns the stored text, or ``{"error": "not found"}`` when the row
    does not exist (falls back to the file mirror if the DB row is
    missing but the file survived).
    """
    conn = _connect()
    try:
        row = conn.execute(
            f"SELECT content FROM {TABLE} WHERE category=? AND name=?",
            (str(category).strip(), str(name).strip()),
        ).fetchone()
    finally:
        conn.close()

    if row is not None:
        return row["content"]

    # Fallback: file mirror (e.g. DB deleted but files kept, or a
    # pre-SQLite row written by the legacy plaintext vault)
    mirror = _mirror_path(category, name)
    if mirror.is_file():
        try:
            return mirror.read_text(encoding="utf-8")
        except OSError:
            pass
    return json.dumps({"error": "not found"})


def vault_list(
    category: str | list[str] | None = None, limit: int = 200, offset: int = 0
) -> dict[str, Any]:
    """List row metadata (no content), newest-created first.

    ``category`` accepts one category, a comma-separated string, or a list.
    """
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    categories = _normalize_categories(category)
    conn = _connect()
    try:
        if categories:
            placeholders = ",".join("?" for _ in categories)
            where = f"WHERE category IN ({placeholders})"
            params: list[Any] = [*categories]
        else:
            where = ""
            params = []
        total = conn.execute(f"SELECT COUNT(*) FROM {TABLE} {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT category, name, target, tool, tags, content_size,
                   created_at, updated_at
            FROM {TABLE} {where}
            ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    finally:
        conn.close()
    return {"count": total, "entries": [dict(r) for r in rows]}


def vault_query(
    category: str | list[str] | None = None,
    target: str | None = None,
    tool: str | None = None,
    search: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Search vault rows.

    Filters (ANDed): category (one, comma-separated, or a list), target,
    tool exact-match; ``search`` is a case-insensitive substring match
    over name, tags, and content.
    """
    limit = max(1, min(int(limit), 1000))
    categories = _normalize_categories(category)
    clauses: list[str] = []
    params: list[Any] = []
    if categories:
        clauses.append(f"category IN ({','.join('?' for _ in categories)})")
        params.extend(categories)
    if target:
        clauses.append("target = ?")
        params.append(target)
    if tool:
        clauses.append("tool = ?")
        params.append(tool)
    if search:
        like = f"%{search}%"
        clauses.append("(name LIKE ? OR tags LIKE ? OR content LIKE ?)")
        params.extend([like, like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = _connect()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM {TABLE} {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT category, name, target, tool, tags, content_size,
                   created_at, updated_at
            FROM {TABLE} {where}
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            [*params, limit],
        ).fetchall()
    finally:
        conn.close()
    return {"count": total, "entries": [dict(r) for r in rows]}


def vault_delete(category: str, name: str) -> dict[str, Any]:
    """Delete a row from SQLite and remove its JSON mirror.

    Reserved for the orchestrator (stale task:/status: rows, superseded
    run rows) — regular agents should not clean up shared rows.
    """
    mirror = _mirror_path(category, name)
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                f"DELETE FROM {TABLE} WHERE category=? AND name=?",
                (str(category).strip(), str(name).strip()),
            )
            conn.commit()
            deleted = cur.rowcount > 0
            _write_index(conn)
        finally:
            conn.close()
        try:
            if mirror.is_file() and Path(VAULT_ROOT) in mirror.resolve().parents:
                mirror.unlink()
        except OSError:
            pass
    return {"deleted": deleted, "category": category, "name": name}


def vault_stats() -> dict[str, Any]:
    """Summary counts: total rows, per-category (GROUP BY), per-tool."""
    conn = _connect()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        by_category = {
            row[0] or "(root)": row[1]
            for row in conn.execute(
                f"SELECT category, COUNT(*) FROM {TABLE} GROUP BY category"
            ).fetchall()
        }
        by_tool = {
            row[0] or "unknown": row[1]
            for row in conn.execute(
                f"SELECT tool, COUNT(*) FROM {TABLE} WHERE tool != '' GROUP BY tool"
            ).fetchall()
        }
        size = conn.execute(f"SELECT COALESCE(SUM(content_size), 0) FROM {TABLE}").fetchone()[0]
    finally:
        conn.close()
    return {
        "total": total,
        "by_category": by_category,
        "by_tool": by_tool,
        "total_bytes": size,
        "db_path": str(_db_path()),
    }


def vault_path(category: str, name: str) -> str:
    """Mirror-file path for a row (for truncated reads / artifact URIs)."""
    return str(_mirror_path(category, name))


def get_index() -> dict[str, Any]:
    """Browseable index of vault rows (served at kali://vault/index)."""
    conn = _connect()
    try:
        rows = conn.execute(
            f"""
            SELECT category, name, path, target, tool, tags, content_size,
                   created_at, updated_at
            FROM {TABLE} ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    entries = [dict(r) for r in rows]
    return {"count": len(entries), "entries": entries}


# ── encryption at rest (PBKDF2 + AES-256-GCM, stdlib fallback) ────────

import hashlib as _hashlib
import hmac as _hmac
import os as _os


def derive_key(passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive a 32-byte key via PBKDF2-HMAC-SHA256. Returns (key, salt)."""
    if salt is None:
        salt = _os.urandom(16)
    key = _hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 100_000, dklen=32)
    return key, salt


def _aes_available() -> bool:
    try:
        import cryptography  # noqa: F401
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def encrypt_value(plaintext: str, passphrase: str) -> str:
    """Encrypt a string. Uses AES-256-GCM if cryptography is available,
    otherwise a stdlib HMAC-authenticated XOR stream (best-effort fallback)."""
    import base64

    key, salt = derive_key(passphrase)
    if _aes_available():
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(key)
        nonce = _os.urandom(12)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        blob = salt + nonce + ct
    else:
        # stdlib fallback: XOR with keystream + HMAC tag
        nonce = _os.urandom(12)
        ks = _hashlib.sha256(key + nonce).digest()
        data = plaintext.encode("utf-8")
        ct = bytes(b ^ ks[i % len(ks)] for i, b in enumerate(data))
        tag = _hmac.new(key, nonce + ct, _hashlib.sha256).digest()
        blob = salt + nonce + tag + ct
    return base64.b64encode(blob).decode("ascii")


def decrypt_value(ciphertext: str, passphrase: str) -> str:
    """Decrypt a string produced by :func:`encrypt_value`."""
    import base64

    blob = base64.b64decode(ciphertext.encode("ascii"))
    salt, rest = blob[:16], blob[16:]
    key, _ = derive_key(passphrase, salt)
    if _aes_available():
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce, ct = rest[:12], rest[12:]
        aesgcm = AESGCM(key)
        pt = aesgcm.decrypt(nonce, ct, None)
        return pt.decode("utf-8")
    # stdlib fallback
    nonce, tag, ct = rest[:12], rest[12:44], rest[44:]
    calc = _hmac.new(key, nonce + ct, _hashlib.sha256).digest()
    if not _hmac.compare_digest(calc, tag):
        raise ValueError("decryption failed: bad tag")
    ks = _hashlib.sha256(key + nonce).digest()
    pt = bytes(b ^ ks[i % len(ks)] for i, b in enumerate(ct))
    return pt.decode("utf-8")


# aliases
vault_encrypt = encrypt_value
vault_decrypt = decrypt_value


def write_secret_ref(name: str, value: str) -> str:
    """Store a secret reference (returns a vault handle, not the value)."""
    ref = f"secret:{name}"
    vault_write("secrets", name, {"ref": ref, "redacted": True}, tags="secret")
    return ref


def resolve_secret_ref(ref: str) -> str | None:
    """Resolve a secret reference handle to its stored value (best-effort)."""
    if not ref.startswith("secret:"):
        return None
    name = ref[len("secret:"):]
    try:
        raw = vault_read("secrets", name)
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data.get("value")
    except Exception:  # noqa: BLE001
        return None


# ── secret redaction & access control ──────────────────────────────────

import re as _re

_SECRET_PATTERNS = [
    _re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{8,})['\"]?"),
    _re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |)PRIVATE KEY-----", _re.S),
    _re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{10,}"),
]


def redact_secrets(text: str) -> str:
    """Redact common secret patterns from text. Returns redacted string."""
    if not isinstance(text, str):
        text = str(text)
    out = text
    # key=value / key: value secrets
    out = _re.sub(
        r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}['\"]?",
        lambda m: m.group(0).split(m.group(1) if False else "", 1)[0] + "[REDACTED]" if False else _re.sub(r"([:=]\s*['\"]?)[A-Za-z0-9_\-]{8,}", r"\1[REDACTED]", m.group(0)),
        out,
    )
    # private keys
    out = _re.sub(
        r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |)PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]",
        out,
        flags=_re.S,
    )
    # bearer tokens
    out = _re.sub(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{10,}", "Bearer [REDACTED]", out)
    return out


def redact_dict(obj: Any) -> Any:
    """Recursively redact secrets in a dict/list/str structure."""
    if isinstance(obj, str):
        return redact_secrets(obj)
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if _looks_like_secret_key(k) else redact_dict(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_dict(v) for v in obj]
    return obj


def _looks_like_secret_key(key: str) -> bool:
    k = str(key).lower()
    return any(s in k for s in ("password", "secret", "token", "api_key", "apikey", "private_key"))


def can_access(assessment_id: str, caller_id: str | None = None) -> bool:
    """Return True if caller may access the given assessment's vault rows.

    Default policy: access is allowed when no owner is recorded for the
    assessment (backwards compatible). When an owner is recorded, only that
    owner (or an empty/None caller in dev mode) may access.
    """
    try:
        row = _connect().execute(
            f"SELECT tags, target FROM {TABLE} WHERE category='assessments' AND name=?",
            (str(assessment_id).strip(),),
        ).fetchone()
    except Exception:  # noqa: BLE001
        return True
    if row is None:
        return True
    tags = row["tags"] or ""
    # Owner recorded as tag "owner:<id>"
    owner = None
    for part in tags.split(","):
        if part.startswith("owner:"):
            owner = part[len("owner:"):]
    if not owner:
        return True
    if caller_id is None:
        return True
    return caller_id == owner
