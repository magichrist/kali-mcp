"""SQLite data manager for Kali MCP.

Provides a lightweight, thread-safe interface to store targets, scans,
findings, and credentials discovered by AI agents.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from kali_mcp.config import config


class DBManager:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.row_factory = sqlite3.Row

    def ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL UNIQUE,
                target_type TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'in-scope',
                tags TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_targets_scope ON targets(scope);
            CREATE INDEX IF NOT EXISTS idx_targets_type ON targets(target_type);

            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER NOT NULL,
                tool TEXT NOT NULL,
                command TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                duration REAL,
                success INTEGER DEFAULT 0,
                findings_count INTEGER DEFAULT 0,
                artifact_uri TEXT,
                FOREIGN KEY (target_id) REFERENCES targets(id)
            );
            CREATE INDEX IF NOT EXISTS idx_scans_target ON scans(target_id);
            CREATE INDEX IF NOT EXISTS idx_scans_tool ON scans(tool);

            CREATE TABLE IF NOT EXISTS findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER NOT NULL,
                scan_id INTEGER,
                tool TEXT NOT NULL,
                finding_type TEXT NOT NULL,
                severity TEXT,
                title TEXT NOT NULL,
                description TEXT,
                evidence TEXT,
                port INTEGER,
                service TEXT,
                url TEXT,
                status TEXT DEFAULT 'open',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (target_id) REFERENCES targets(id),
                FOREIGN KEY (scan_id) REFERENCES scans(id)
            );
            CREATE INDEX IF NOT EXISTS idx_findings_target ON findings(target_id);
            CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
            CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);

            CREATE TABLE IF NOT EXISTS credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_id INTEGER NOT NULL,
                service TEXT NOT NULL,
                username TEXT NOT NULL,
                password TEXT,
                hash TEXT,
                source_tool TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                notes TEXT,
                FOREIGN KEY (target_id) REFERENCES targets(id)
            );
            CREATE INDEX IF NOT EXISTS idx_credentials_target ON credentials(target_id);
            CREATE INDEX IF NOT EXISTS idx_credentials_service ON credentials(service);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # Convenience helpers for common operations
    def upsert_target(
        self,
        target: str,
        target_type: str = "host",
        scope: str = "in-scope",
        tags: str = "",
        notes: str = "",
    ) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM targets WHERE target = ?", (target,))
        row = cur.fetchone()
        now = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        if row:
            tid = int(row[0])
            cur.execute(
                "UPDATE targets SET target_type=?, scope=?, tags=?, notes=?, updated_at=? WHERE id=?",
                (target_type, scope, tags, notes, now, tid),
            )
        else:
            cur.execute(
                "INSERT INTO targets (target, target_type, scope, tags, notes, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (target, target_type, scope, tags, notes, now, now),
            )
            tid = cur.lastrowid
        self.conn.commit()
        return int(tid)

    def add_scan(
        self,
        target_id: int,
        tool: str,
        command: str,
        started_at: str,
        completed_at: str,
        duration: float,
        success: int,
        findings_count: int,
        artifact_uri: str | None,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO scans (target_id, tool, command, started_at, completed_at, duration, success, findings_count, artifact_uri) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                target_id,
                tool,
                command,
                started_at,
                completed_at,
                duration,
                int(bool(success)),
                int(findings_count),
                artifact_uri,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_finding(
        self,
        target_id: int,
        scan_id: int | None,
        tool: str,
        finding_type: str,
        severity: str,
        title: str,
        description: str,
        evidence: str,
        port: int | None = None,
        service: str | None = None,
        url: str | None = None,
        status: str = "open",
    ) -> int:
        cur = self.conn.cursor()
        now = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        cur.execute(
            "INSERT INTO findings (target_id, scan_id, tool, finding_type, severity, title, description, evidence, port, service, url, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                target_id,
                scan_id,
                tool,
                finding_type,
                severity,
                title,
                description,
                evidence,
                port,
                service,
                url,
                status,
                now,
                now,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_credential(
        self,
        target_id: int,
        service: str,
        username: str,
        password: str | None = None,
        hash_value: str | None = None,
        source_tool: str = "",
        notes: str = "",
    ) -> int:
        cur = self.conn.cursor()
        now = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        cur.execute(
            "INSERT INTO credentials (target_id, service, username, password, hash, source_tool, captured_at, notes) VALUES (?,?,?,?,?,?,?,?)",
            (
                target_id,
                service,
                username,
                password,
                hash_value,
                source_tool,
                now,
                notes,
            ),
        )
        self.conn.commit()
        return cur.lastrowid


_db_singleton: DBManager | None = None


def get_db() -> DBManager | None:
    global _db_singleton
    if _db_singleton is None:
        try:
            if getattr(config, "db_enabled", True):
                _db_singleton = DBManager(config.db_path)
                _db_singleton.ensure_schema()
        except Exception:
            _db_singleton = None
    return _db_singleton


def _now():
    import datetime

    return datetime.datetime.utcnow().isoformat() + "Z"
