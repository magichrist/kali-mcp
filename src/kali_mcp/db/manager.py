"""SQLite data manager for Kali MCP v2.0.

Provides a lightweight, thread-safe interface to store targets, scans,
findings, credentials, assets, services, technologies, evidence artifacts,
and finding correlations discovered by AI agents.

Backward compatible with the v1 schema (targets, scans, findings,
credentials). New v2 tables and columns are added via idempotent
migrations so existing databases are upgraded in place.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
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

        # ── v1 tables (unchanged, created if missing) ─────────────────────
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

        # ── v1 → v2 column migrations (idempotent) ────────────────────────
        self._migrate_add_column(cur, "targets", "asset_id", "TEXT")
        self._migrate_add_column(cur, "targets", "domain", "TEXT")
        self._migrate_add_column(cur, "targets", "ip_address", "TEXT")
        self._migrate_add_column(cur, "targets", "first_seen", "TEXT")
        self._migrate_add_column(cur, "targets", "last_seen", "TEXT")

        self._migrate_add_column(cur, "scans", "assessment_id", "TEXT")
        self._migrate_add_column(cur, "scans", "job_id", "TEXT")
        self._migrate_add_column(cur, "scans", "workflow_name", "TEXT")

        self._migrate_add_column(cur, "findings", "confidence", "REAL DEFAULT 0.5")
        self._migrate_add_column(cur, "findings", "validation_status", "TEXT DEFAULT 'observed'")
        self._migrate_add_column(cur, "findings", "source_tools", "TEXT DEFAULT '[]'")
        self._migrate_add_column(cur, "findings", "evidence_refs", "TEXT DEFAULT '[]'")
        self._migrate_add_column(cur, "findings", "first_seen", "TEXT")
        self._migrate_add_column(cur, "findings", "last_seen", "TEXT")

        self._migrate_add_column(cur, "credentials", "asset_id", "TEXT")
        self._migrate_add_column(cur, "credentials", "service_id", "TEXT")

        # ── v2 tables (new) ───────────────────────────────────────────────
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL UNIQUE,
                asset_type TEXT NOT NULL,        -- domain | ip | subdomain | service | technology
                name TEXT NOT NULL,              -- human-readable identifier
                domain TEXT,                     -- parent domain if applicable
                ip_address TEXT,                 -- resolved IP if applicable
                target_id INTEGER,               -- link to v1 targets table
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'in-scope',
                tags TEXT,
                notes TEXT,
                FOREIGN KEY (target_id) REFERENCES targets(id)
            );
            CREATE INDEX IF NOT EXISTS idx_assets_asset_id ON assets(asset_id);
            CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(asset_type);
            CREATE INDEX IF NOT EXISTS idx_assets_target ON assets(target_id);

            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL UNIQUE,
                asset_id INTEGER NOT NULL,       -- parent asset (ip/host)
                port INTEGER NOT NULL,
                protocol TEXT NOT NULL,          -- tcp | udp
                service_name TEXT,
                version TEXT,
                banner TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                FOREIGN KEY (asset_id) REFERENCES assets(id)
            );
            CREATE INDEX IF NOT EXISTS idx_services_service_id ON services(service_id);
            CREATE INDEX IF NOT EXISTS idx_services_asset ON services(asset_id);
            CREATE INDEX IF NOT EXISTS idx_services_port ON services(port, protocol);

            CREATE TABLE IF NOT EXISTS technologies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tech_id TEXT NOT NULL UNIQUE,
                service_id INTEGER,              -- service this tech was found on
                name TEXT NOT NULL,              -- e.g. Apache, nginx, PHP
                version TEXT,
                category TEXT,                   -- web_server | framework | cms | language
                confidence REAL DEFAULT 0.5,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                FOREIGN KEY (service_id) REFERENCES services(id)
            );
            CREATE INDEX IF NOT EXISTS idx_technologies_tech_id ON technologies(tech_id);
            CREATE INDEX IF NOT EXISTS idx_technologies_service ON technologies(service_id);

            CREATE TABLE IF NOT EXISTS asset_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_asset_id INTEGER NOT NULL,
                target_asset_id INTEGER NOT NULL,
                relationship TEXT NOT NULL,      -- resolves_to | contains | uses_technology | shared_by | child_of | supports
                confidence REAL DEFAULT 0.5,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                source_tool TEXT,
                FOREIGN KEY (source_asset_id) REFERENCES assets(id),
                FOREIGN KEY (target_asset_id) REFERENCES assets(id)
            );
            CREATE INDEX IF NOT EXISTS idx_asset_rels_source ON asset_relationships(source_asset_id);
            CREATE INDEX IF NOT EXISTS idx_asset_rels_target ON asset_relationships(target_asset_id);
            CREATE INDEX IF NOT EXISTS idx_asset_rels_rel ON asset_relationships(relationship);

            CREATE TABLE IF NOT EXISTS evidence_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_id TEXT NOT NULL UNIQUE,
                assessment_id TEXT,
                job_id TEXT,
                tool TEXT NOT NULL,
                target TEXT NOT NULL,
                artifact_type TEXT NOT NULL,     -- stdout | stderr | file | screenshot
                content_path TEXT NOT NULL,      -- path to stored artifact file
                content_size INTEGER NOT NULL DEFAULT 0,
                captured_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_evidence_evidence_id ON evidence_artifacts(evidence_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_assessment ON evidence_artifacts(assessment_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_job ON evidence_artifacts(job_id);

            CREATE TABLE IF NOT EXISTS finding_correlation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_id TEXT NOT NULL UNIQUE,
                finding_id INTEGER NOT NULL,     -- canonical finding this group resolves to
                observation_id INTEGER NOT NULL, -- individual observation row
                tool TEXT NOT NULL,
                confidence_contribution REAL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                FOREIGN KEY (finding_id) REFERENCES findings(id),
                FOREIGN KEY (observation_id) REFERENCES findings(id)
            );
            CREATE INDEX IF NOT EXISTS idx_finding_corr_finding ON finding_correlation(finding_id);
            CREATE INDEX IF NOT EXISTS idx_finding_corr_observation ON finding_correlation(observation_id);
            """
        )

        # ── studio tables (new, additive only) ─────────────────────────────
        self._create_studio_tables(cur)

        self.conn.commit()

    def _create_studio_tables(self, cur: sqlite3.Cursor) -> None:
        """Create all Playbook Studio tables and indexes (idempotent, additive).

        Per docs/visual/02_DATA_MODEL.md §3. No existing tables are modified
        and no existing columns are dropped; JSON-flexible fields are stored
        as TEXT (JSON serialization happens in the helper layer).
        """
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS tool_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                provider TEXT NOT NULL,
                provider_ref TEXT,
                input_schema TEXT,
                output_schema TEXT,
                visibility TEXT NOT NULL DEFAULT 'internal',
                enabled INTEGER NOT NULL DEFAULT 1,
                requires_binary TEXT,
                default_timeout INTEGER NOT NULL DEFAULT 300,
                execution_policy TEXT,
                scope_required INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tool_defs_provider ON tool_definitions(provider);
            CREATE INDEX IF NOT EXISTS idx_tool_defs_visibility ON tool_definitions(visibility);
            CREATE INDEX IF NOT EXISTS idx_tool_defs_enabled ON tool_definitions(enabled);

            CREATE TABLE IF NOT EXISTS mcp_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connection_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                transport TEXT NOT NULL,
                endpoint_url TEXT,
                command TEXT,
                args TEXT,
                auth_type TEXT,
                auth_config TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_connected_at TEXT,
                health_status TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mcp_conn_health ON mcp_connections(health_status);

            CREATE TABLE IF NOT EXISTS agent_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                default_visibility TEXT NOT NULL DEFAULT 'internal',
                max_parallel_operations INTEGER NOT NULL DEFAULT 4,
                max_execution_seconds INTEGER NOT NULL DEFAULT 900,
                allowed_scopes TEXT,
                excluded_targets TEXT,
                allowed_operations TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_profiles_id ON agent_profiles(profile_id);

            CREATE TABLE IF NOT EXISTS agent_tool_permissions (
                profile_id TEXT NOT NULL,
                tool_id TEXT NOT NULL,
                granted INTEGER NOT NULL DEFAULT 1,
                granted_at TEXT NOT NULL,
                PRIMARY KEY (profile_id, tool_id)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_tool_perm_profile ON agent_tool_permissions(profile_id);

            CREATE TABLE IF NOT EXISTS agent_playbook_assignments (
                profile_id TEXT NOT NULL,
                playbook_id TEXT NOT NULL,
                granted INTEGER NOT NULL DEFAULT 1,
                granted_at TEXT NOT NULL,
                PRIMARY KEY (profile_id, playbook_id)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_playbook_assign_profile ON agent_playbook_assignments(profile_id);

            CREATE TABLE IF NOT EXISTS playbooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playbook_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                author TEXT,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                current_version_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_playbooks_status ON playbooks(status);
            CREATE INDEX IF NOT EXISTS idx_playbooks_builtin ON playbooks(is_builtin);

            CREATE TABLE IF NOT EXISTS playbook_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL UNIQUE,
                playbook_id TEXT NOT NULL,
                version TEXT NOT NULL,
                definition TEXT NOT NULL,
                inputs_schema TEXT,
                notes TEXT,
                published_at TEXT,
                published_by TEXT,
                FOREIGN KEY (playbook_id) REFERENCES playbooks(playbook_id)
            );
            CREATE INDEX IF NOT EXISTS idx_playbook_versions_playbook ON playbook_versions(playbook_id);
            CREATE INDEX IF NOT EXISTS idx_playbook_versions_version ON playbook_versions(version_id);

            CREATE TABLE IF NOT EXISTS workflow_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id INTEGER NOT NULL,
                node_id TEXT NOT NULL,
                node_type TEXT NOT NULL,
                tool_id TEXT,
                config TEXT,
                position_x REAL,
                position_y REAL,
                FOREIGN KEY (version_id) REFERENCES playbook_versions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_nodes_version ON workflow_nodes(version_id);

            CREATE TABLE IF NOT EXISTS workflow_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id INTEGER NOT NULL,
                source_node_id TEXT NOT NULL,
                target_node_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                condition TEXT,
                FOREIGN KEY (version_id) REFERENCES playbook_versions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_edges_version ON workflow_edges(version_id);

            CREATE TABLE IF NOT EXISTS workflow_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT NOT NULL UNIQUE,
                job_id TEXT,
                assessment_id TEXT,
                playbook_id TEXT NOT NULL,
                version_id INTEGER NOT NULL,
                profile_id TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                inputs TEXT,
                outputs TEXT,
                error TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (version_id) REFERENCES playbook_versions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_exec_status ON workflow_executions(status);
            CREATE INDEX IF NOT EXISTS idx_workflow_exec_playbook ON workflow_executions(playbook_id);
            CREATE INDEX IF NOT EXISTS idx_workflow_exec_job ON workflow_executions(job_id);

            CREATE TABLE IF NOT EXISTS workflow_step_executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                step_type TEXT,
                tool_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                inputs TEXT,
                outputs TEXT,
                error TEXT,
                started_at TEXT,
                completed_at TEXT,
                duration_ms INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_step_exec_execution ON workflow_step_executions(execution_id);

            CREATE TABLE IF NOT EXISTS workflow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                playbook_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                completed_steps TEXT,
                state_json TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_playbook ON workflow_runs(playbook_name);

            CREATE TABLE IF NOT EXISTS playbook_validations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id INTEGER,
                playbook_id TEXT,
                status TEXT NOT NULL,
                errors TEXT,
                validated_at TEXT NOT NULL,
                validated_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_playbook_validations_version ON playbook_validations(version_id);

            CREATE TABLE IF NOT EXISTS studio_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                actor TEXT,
                data TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gate TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_by TEXT,
                approved_by TEXT,
                requested_at TEXT,
                approved_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pending_approvals_gate ON pending_approvals(gate, resource_id);
            CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status);
            """
        )

        # Playbook drafts live on the row (published versions are immutable);
        # execution provenance records who/what started a run. These tables
        # are created in the v2 script above, so migrate after it.
        self._migrate_add_column(cur, "playbooks", "draft_definition", "TEXT")
        self._migrate_add_column(cur, "workflow_executions", "trigger", "TEXT")
        self._migrate_add_column(
            cur, "workflow_executions", "debug", "INTEGER DEFAULT 0"
        )

    # ── migration helpers ────────────────────────────────────────────────

    @staticmethod
    def _column_names(cur: sqlite3.Cursor, table: str) -> set[str]:
        rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}

    def _migrate_add_column(
        self, cur: sqlite3.Cursor, table: str, column: str, col_type: str
    ) -> None:
        """Add a column if it does not already exist (idempotent)."""
        existing = self._column_names(cur, table)
        if column not in existing:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                # Column may have been added by a concurrent migration; ignore.
                pass

    # ── v2 asset helpers ─────────────────────────────────────────────────

    def upsert_asset(
        self,
        asset_id: str,
        asset_type: str,
        name: str,
        domain: str | None = None,
        ip_address: str | None = None,
        target_id: int | None = None,
        scope: str = "in-scope",
        tags: str = "",
        notes: str = "",
    ) -> int:
        """Insert or update an asset node. Returns the asset row id."""
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM assets WHERE asset_id = ?", (asset_id,))
        row = cur.fetchone()
        if row:
            aid = int(row[0])
            cur.execute(
                """
                UPDATE assets
                SET asset_type=?, name=?, domain=?, ip_address=?, target_id=?,
                    scope=?, tags=?, notes=?, last_seen=?
                WHERE id=?
                """,
                (
                    asset_type, name, domain, ip_address, target_id,
                    scope, tags, notes, now, aid,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO assets
                (asset_id, asset_type, name, domain, ip_address, target_id,
                 first_seen, last_seen, scope, tags, notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    asset_id, asset_type, name, domain, ip_address, target_id,
                    now, now, scope, tags, notes,
                ),
            )
            aid = int(cur.lastrowid)
        self.conn.commit()
        return aid

    def add_service(
        self,
        service_id: str,
        asset_id: int,
        port: int,
        protocol: str,
        service_name: str | None = None,
        version: str | None = None,
        banner: str | None = None,
    ) -> int:
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM services WHERE service_id = ?", (service_id,))
        row = cur.fetchone()
        if row:
            sid = int(row[0])
            cur.execute(
                """
                UPDATE services
                SET port=?, protocol=?, service_name=?, version=?, banner=?, last_seen=?
                WHERE id=?
                """,
                (port, protocol, service_name, version, banner, now, sid),
            )
        else:
            cur.execute(
                """
                INSERT INTO services
                (service_id, asset_id, port, protocol, service_name, version,
                 banner, first_seen, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (service_id, asset_id, port, protocol, service_name, version,
                 banner, now, now),
            )
            sid = int(cur.lastrowid)
        self.conn.commit()
        return sid

    def add_technology(
        self,
        tech_id: str,
        service_id: int | None,
        name: str,
        version: str | None = None,
        category: str | None = None,
        confidence: float = 0.5,
    ) -> int:
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM technologies WHERE tech_id = ?", (tech_id,))
        row = cur.fetchone()
        if row:
            tid = int(row[0])
            cur.execute(
                """
                UPDATE technologies
                SET service_id=?, name=?, version=?, category=?, confidence=?, last_seen=?
                WHERE id=?
                """,
                (service_id, name, version, category, confidence, now, tid),
            )
        else:
            cur.execute(
                """
                INSERT INTO technologies
                (tech_id, service_id, name, version, category, confidence,
                 first_seen, last_seen)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (tech_id, service_id, name, version, category, confidence,
                 now, now),
            )
            tid = int(cur.lastrowid)
        self.conn.commit()
        return tid

    def add_asset_relationship(
        self,
        source_asset_id: int,
        target_asset_id: int,
        relationship: str,
        confidence: float = 0.5,
        source_tool: str | None = None,
    ) -> int:
        now = self._now_utc()
        cur = self.conn.cursor()
        # Avoid duplicate active relationships
        cur.execute(
            """
            SELECT id FROM asset_relationships
            WHERE source_asset_id=? AND target_asset_id=? AND relationship=?
            """,
            (source_asset_id, target_asset_id, relationship),
        )
        row = cur.fetchone()
        if row:
            rid = int(row[0])
            cur.execute(
                """
                UPDATE asset_relationships
                SET confidence=?, last_seen=?, source_tool=COALESCE(?, source_tool)
                WHERE id=?
                """,
                (confidence, now, source_tool, rid),
            )
        else:
            cur.execute(
                """
                INSERT INTO asset_relationships
                (source_asset_id, target_asset_id, relationship, confidence,
                 first_seen, last_seen, source_tool)
                VALUES (?,?,?,?,?,?,?)
                """,
                (source_asset_id, target_asset_id, relationship, confidence,
                 now, now, source_tool),
            )
            rid = int(cur.lastrowid)
        self.conn.commit()
        return rid

    def add_evidence_artifact(
        self,
        evidence_id: str,
        tool: str,
        target: str,
        artifact_type: str,
        content_path: str,
        content_size: int = 0,
        assessment_id: str | None = None,
        job_id: str | None = None,
    ) -> int:
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO evidence_artifacts
            (evidence_id, assessment_id, job_id, tool, target, artifact_type,
             content_path, content_size, captured_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                evidence_id, assessment_id, job_id, tool, target, artifact_type,
                content_path, content_size, now,
            ),
        )
        aid = int(cur.lastrowid)
        self.conn.commit()
        return aid

    def add_finding_correlation(
        self,
        correlation_id: str,
        finding_id: int,
        observation_id: int,
        tool: str,
        confidence_contribution: float = 0.5,
    ) -> int:
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO finding_correlation
            (correlation_id, finding_id, observation_id, tool,
             confidence_contribution, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (correlation_id, finding_id, observation_id, tool,
             confidence_contribution, now),
        )
        cid = int(cur.lastrowid)
        self.conn.commit()
        return cid

    # ── v2 query helpers ─────────────────────────────────────────────────

    def get_asset_graph(self, target: str | None = None) -> dict:
        """Return assets and their relationships, optionally filtered by target."""
        cur = self.conn.cursor()
        if target:
            cur.execute(
                "SELECT * FROM assets WHERE name = ? OR ip_address = ? OR domain = ?",
                (target, target, target),
            )
        else:
            cur.execute("SELECT * FROM assets")
        assets = [dict(r) for r in cur.fetchall()]

        rels = []
        if assets:
            asset_ids = [a["id"] for a in assets]
            placeholders = ",".join("?" for _ in asset_ids)
            cur.execute(
                f"SELECT * FROM asset_relationships WHERE source_asset_id IN ({placeholders}) "
                f"OR target_asset_id IN ({placeholders})",
                (*asset_ids, *asset_ids),
            )
            rels = [dict(r) for r in cur.fetchall()]

        return {"assets": assets, "relationships": rels}

    def query_findings(
        self,
        target: str | None = None,
        severity: str | None = None,
        validation_status: str | None = None,
        tool: str | None = None,
        asset_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Query normalized findings with optional filters."""
        cur = self.conn.cursor()
        clauses: list[str] = []
        params: list = []
        if target:
            clauses.append("target_id IN (SELECT id FROM targets WHERE target = ?)")
            params.append(target)
        if asset_id:
            clauses.append(
                "target_id IN (SELECT t.id FROM targets t "
                "JOIN assets a ON t.id = a.target_id WHERE a.asset_id = ?)"
            )
            params.append(asset_id)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if validation_status:
            clauses.append("validation_status = ?")
            params.append(validation_status)
        if tool:
            clauses.append("tool = ?")
            params.append(tool)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = cur.execute(
            f"SELECT COUNT(*) FROM findings {where}", params
        ).fetchone()[0]
        rows = cur.execute(
            f"SELECT * FROM findings {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return {"count": total, "findings": [dict(r) for r in rows]}

    def get_evidence(self, evidence_id: str) -> dict | None:
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM evidence_artifacts WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_findings_by_assessment(self, assessment_id: str) -> dict:
        """Return all findings linked to a given assessment_id.

        Joins findings → scans on scan_id and filters by assessment_id.
        Returns {count, findings} with the full finding row including
        confidence, validation_status, source_tools, evidence_refs.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT f.* FROM findings f
            JOIN scans s ON f.scan_id = s.id
            WHERE s.assessment_id = ?
            ORDER BY f.created_at DESC
            """,
            (assessment_id,),
        ).fetchall()
        findings = [dict(r) for r in rows]
        return {"count": len(findings), "findings": findings, "assessment_id": assessment_id}

    def get_assessments_for_target(self, target: str) -> list[dict]:
        """Return all assessment_ids associated with a target.

        Links targets → scans → assessment_id. Returns a list of dicts with
        assessment_id, job_id, tool, started_at, completed_at.
        """
        cur = self.conn.cursor()
        # Find target row(s)
        target_rows = cur.execute(
            "SELECT id FROM targets WHERE target = ?",
            (target,),
        ).fetchall()
        if not target_rows:
            return []
        target_ids = [r[0] for r in target_rows]
        placeholders = ",".join("?" for _ in target_ids)
        rows = cur.execute(
            f"""
            SELECT DISTINCT s.assessment_id, s.job_id, s.tool, s.started_at,
                   s.completed_at, s.workflow_name
            FROM scans s
            WHERE s.target_id IN ({placeholders}) AND s.assessment_id IS NOT NULL
            ORDER BY s.started_at DESC
            """,
            (*target_ids,),
        ).fetchall()
        return [
            {
                "assessment_id": r[0],
                "job_id": r[1],
                "tool": r[2],
                "started_at": r[3],
                "completed_at": r[4],
                "workflow_name": r[5],
            }
            for r in rows
        ]

    def get_findings_by_state(self, validation_status: str) -> dict:
        """Return all findings with a given validation_status.

        Returns {count, findings} with the full finding row.
        """
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT * FROM findings
            WHERE validation_status = ?
            ORDER BY created_at DESC
            """,
            (validation_status,),
        ).fetchall()
        findings = [dict(r) for r in rows]
        return {"count": len(findings), "findings": findings,
                "validation_status": validation_status}

    # ── studio helpers: shared JSON serialization ────────────────────────

    @staticmethod
    def _dump_json(value: dict | list | str | None) -> str | None:
        """Serialize flexible fields to JSON text for TEXT columns.

        Strings are stored as-is (callers may pass pre-serialized JSON);
        dicts/lists are dumped; None passes through.
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    # ── studio: tool definitions ─────────────────────────────────────────

    def upsert_tool_definition(
        self,
        tool_id: str,
        name: str,
        description: str | None = None,
        provider: str = "native",
        provider_ref: str | None = None,
        input_schema: dict | list | str | None = None,
        output_schema: dict | list | str | None = None,
        visibility: str = "internal",
        enabled: bool = True,
        requires_binary: str | None = None,
        default_timeout: int = 300,
        execution_policy: str | None = None,
        scope_required: bool = False,
    ) -> int:
        """Insert or update a unified capability registry entry.

        Returns the tool_definitions row id.
        """
        now = self._now_utc()
        in_json = self._dump_json(input_schema)
        out_json = self._dump_json(output_schema)
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM tool_definitions WHERE tool_id = ?", (tool_id,))
        row = cur.fetchone()
        if row:
            tdid = int(row[0])
            cur.execute(
                """
                UPDATE tool_definitions
                SET name=?, description=?, provider=?, provider_ref=?,
                    input_schema=?, output_schema=?, visibility=?, enabled=?,
                    requires_binary=?, default_timeout=?, execution_policy=?,
                    scope_required=?, updated_at=?
                WHERE id=?
                """,
                (
                    name, description, provider, provider_ref, in_json,
                    out_json, visibility, int(bool(enabled)), requires_binary,
                    default_timeout, execution_policy, int(bool(scope_required)),
                    now, tdid,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO tool_definitions
                (tool_id, name, description, provider, provider_ref,
                 input_schema, output_schema, visibility, enabled,
                 requires_binary, default_timeout, execution_policy,
                 scope_required, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    tool_id, name, description, provider, provider_ref, in_json,
                    out_json, visibility, int(bool(enabled)), requires_binary,
                    default_timeout, execution_policy, int(bool(scope_required)),
                    now, now,
                ),
            )
            tdid = int(cur.lastrowid)
        self.conn.commit()
        return tdid

    def get_tool_definition(self, tool_id: str) -> dict | None:
        """Return one tool definition row by tool_id, or None."""
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM tool_definitions WHERE tool_id = ?", (tool_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_tool_definitions(
        self,
        provider: str | None = None,
        visibility: str | None = None,
        enabled: bool | None = None,
    ) -> list[dict]:
        """List tool definitions with optional provider/visibility/enabled filters."""
        cur = self.conn.cursor()
        clauses: list[str] = []
        params: list = []
        if provider is not None:
            clauses.append("provider = ?")
            params.append(provider)
        if visibility is not None:
            clauses.append("visibility = ?")
            params.append(visibility)
        if enabled is not None:
            clauses.append("enabled = ?")
            params.append(int(bool(enabled)))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = cur.execute(
            f"SELECT * FROM tool_definitions {where} ORDER BY tool_id", params
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_tool_definition(self, tool_id: str) -> bool:
        """Delete a tool definition. Returns True when a row was removed."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM tool_definitions WHERE tool_id = ?", (tool_id,))
        deleted = cur.rowcount > 0
        self.conn.commit()
        return deleted

    # ── studio: agent profiles ───────────────────────────────────────────

    def create_agent_profile(
        self,
        profile_id: str,
        name: str,
        description: str | None = None,
        default_visibility: str = "internal",
        max_parallel_operations: int = 4,
        max_execution_seconds: int = 900,
        allowed_scopes: list | str | None = None,
        excluded_targets: list | str | None = None,
        allowed_operations: list | str | None = None,
    ) -> int:
        """Insert a new agent profile (or update an existing profile_id).

        Returns the agent_profiles row id.
        """
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM agent_profiles WHERE profile_id = ?", (profile_id,))
        row = cur.fetchone()
        if row:
            pid = int(row[0])
            cur.execute(
                """
                UPDATE agent_profiles
                SET name=?, description=?, default_visibility=?,
                    max_parallel_operations=?, max_execution_seconds=?,
                    allowed_scopes=?, excluded_targets=?, allowed_operations=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    name, description, default_visibility,
                    max_parallel_operations, max_execution_seconds,
                    self._dump_json(allowed_scopes),
                    self._dump_json(excluded_targets),
                    self._dump_json(allowed_operations), now, pid,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO agent_profiles
                (profile_id, name, description, default_visibility,
                 max_parallel_operations, max_execution_seconds, allowed_scopes,
                 excluded_targets, allowed_operations, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    profile_id, name, description, default_visibility,
                    max_parallel_operations, max_execution_seconds,
                    self._dump_json(allowed_scopes),
                    self._dump_json(excluded_targets),
                    self._dump_json(allowed_operations), now, now,
                ),
            )
            pid = int(cur.lastrowid)
        self.conn.commit()
        return pid

    def get_agent_profile(self, profile_id: str) -> dict | None:
        """Return one agent profile row by profile_id, or None."""
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM agent_profiles WHERE profile_id = ?", (profile_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_agent_profiles(self) -> list[dict]:
        """List all agent profiles ordered by profile_id."""
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT * FROM agent_profiles ORDER BY profile_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_agent_profile(
        self,
        profile_id: str,
        name: str | None = None,
        description: str | None = None,
        default_visibility: str | None = None,
        max_parallel_operations: int | None = None,
        max_execution_seconds: int | None = None,
        allowed_scopes: list | str | None = None,
        excluded_targets: list | str | None = None,
        allowed_operations: list | str | None = None,
    ) -> bool:
        """Update an agent profile, keeping existing values for omitted fields.

        Returns False when the profile does not exist.
        """
        row = self.get_agent_profile(profile_id)
        if not row:
            return False
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE agent_profiles
            SET name=?, description=?, default_visibility=?,
                max_parallel_operations=?, max_execution_seconds=?,
                allowed_scopes=?, excluded_targets=?, allowed_operations=?,
                updated_at=?
            WHERE profile_id=?
            """,
            (
                name if name is not None else row["name"],
                description if description is not None else row["description"],
                default_visibility if default_visibility is not None
                else row["default_visibility"],
                max_parallel_operations if max_parallel_operations is not None
                else row["max_parallel_operations"],
                max_execution_seconds if max_execution_seconds is not None
                else row["max_execution_seconds"],
                self._dump_json(allowed_scopes) if allowed_scopes is not None
                else row["allowed_scopes"],
                self._dump_json(excluded_targets) if excluded_targets is not None
                else row["excluded_targets"],
                self._dump_json(allowed_operations) if allowed_operations is not None
                else row["allowed_operations"],
                self._now_utc(),
                profile_id,
            ),
        )
        self.conn.commit()
        return True

    def delete_agent_profile(self, profile_id: str) -> bool:
        """Delete an agent profile and its permissions/assignments.

        Returns True when the profile row was removed.
        """
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM agent_tool_permissions WHERE profile_id = ?", (profile_id,)
        )
        cur.execute(
            "DELETE FROM agent_playbook_assignments WHERE profile_id = ?",
            (profile_id,),
        )
        cur.execute("DELETE FROM agent_profiles WHERE profile_id = ?", (profile_id,))
        deleted = cur.rowcount > 0
        self.conn.commit()
        return deleted

    # ── studio: permissions & playbook assignments ───────────────────────

    def grant_tool_permission(
        self, profile_id: str, tool_id: str, granted: bool = True
    ) -> None:
        """Grant (or explicitly deny with granted=False) a tool to a profile."""
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE agent_tool_permissions
            SET granted=?, granted_at=?
            WHERE profile_id=? AND tool_id=?
            """,
            (int(bool(granted)), now, profile_id, tool_id),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO agent_tool_permissions
                (profile_id, tool_id, granted, granted_at)
                VALUES (?,?,?,?)
                """,
                (profile_id, tool_id, int(bool(granted)), now),
            )
        self.conn.commit()

    def revoke_tool_permission(self, profile_id: str, tool_id: str) -> None:
        """Remove a tool permission row (ungranted tools are denied by default)."""
        cur = self.conn.cursor()
        cur.execute(
            """
            DELETE FROM agent_tool_permissions
            WHERE profile_id=? AND tool_id=?
            """,
            (profile_id, tool_id),
        )
        self.conn.commit()

    def list_tool_permission_rows(
        self, profile_id: str, granted_only: bool = False
    ) -> list[dict]:
        """List tool permission rows for one profile, optionally granted only."""
        cur = self.conn.cursor()
        sql = "SELECT tool_id, granted, granted_at FROM agent_tool_permissions WHERE profile_id = ?"
        if granted_only:
            sql += " AND granted = 1"
        rows = cur.execute(sql + " ORDER BY tool_id", (profile_id,)).fetchall()
        return [dict(r) for r in rows]


    def can_agent_call_tool(self, profile_id: str, tool_id: str) -> bool:
        """Return True only when the profile has an explicit grant for the tool.

        Deny-by-default: no permission row means False.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT granted FROM agent_tool_permissions
            WHERE profile_id=? AND tool_id=?
            """,
            (profile_id, tool_id),
        ).fetchone()
        return bool(row and row["granted"])

    def assign_playbook_to_profile(
        self, profile_id: str, playbook_id: str, granted: bool = True
    ) -> None:
        """Grant (or explicitly revoke with granted=False) a playbook to a profile."""
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT granted FROM agent_playbook_assignments
            WHERE profile_id=? AND playbook_id=?
            """,
            (profile_id, playbook_id),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE agent_playbook_assignments
                SET granted=?, granted_at=?
                WHERE profile_id=? AND playbook_id=?
                """,
                (int(bool(granted)), now, profile_id, playbook_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO agent_playbook_assignments
                (profile_id, playbook_id, granted, granted_at)
                VALUES (?,?,?,?)
                """,
                (profile_id, playbook_id, int(bool(granted)), now),
            )
        self.conn.commit()

    def unassign_playbook_from_profile(self, profile_id: str, playbook_id: str) -> None:
        """Remove a playbook assignment row for a profile."""
        cur = self.conn.cursor()
        cur.execute(
            """
            DELETE FROM agent_playbook_assignments
            WHERE profile_id=? AND playbook_id=?
            """,
            (profile_id, playbook_id),
        )
        self.conn.commit()

    def is_playbook_assigned(self, profile_id: str, playbook_id: str) -> bool:
        """Return True only when the profile has an explicit playbook grant."""
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT granted FROM agent_playbook_assignments
            WHERE profile_id=? AND playbook_id=?
            """,
            (profile_id, playbook_id),
        ).fetchone()
        return bool(row and row["granted"])

    def list_playbook_assignments(self, profile_id: str) -> list[dict]:
        """List playbook assignments (granted or revoked) for one profile."""
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT playbook_id, granted, granted_at
            FROM agent_playbook_assignments
            WHERE profile_id = ?
            ORDER BY playbook_id
            """,
            (profile_id,),
        ).fetchall()
        return [dict(r) for r in rows]


    # ── studio: playbooks & versions ─────────────────────────────────────

    def create_playbook(
        self,
        playbook_id: str,
        name: str,
        description: str | None = None,
        category: str | None = None,
        author: str | None = None,
        is_builtin: bool = False,
        status: str = "draft",
    ) -> int:
        """Insert a playbook (or update metadata for an existing playbook_id).

        Returns the playbooks row id.
        """
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM playbooks WHERE playbook_id = ?", (playbook_id,))
        row = cur.fetchone()
        if row:
            pbid = int(row[0])
            cur.execute(
                """
                UPDATE playbooks
                SET name=?, description=?, category=?, author=?, is_builtin=?,
                    status=?, updated_at=?
                WHERE id=?
                """,
                (
                    name, description, category, author, int(bool(is_builtin)),
                    status, now, pbid,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO playbooks
                (playbook_id, name, description, category, author, is_builtin,
                 status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    playbook_id, name, description, category, author,
                    int(bool(is_builtin)), status, now, now,
                ),
            )
            pbid = int(cur.lastrowid)
        self.conn.commit()
        return pbid

    def get_playbook(self, playbook_id: str) -> dict | None:
        """Return one playbook row by playbook_id, or None."""
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM playbooks WHERE playbook_id = ?", (playbook_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_playbooks(self, status: str | None = None) -> list[dict]:
        """List playbooks, optionally filtered by status, newest first."""
        cur = self.conn.cursor()
        if status is not None:
            rows = cur.execute(
                "SELECT * FROM playbooks WHERE status = ? ORDER BY id DESC",
                (status,),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT * FROM playbooks ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_playbook(
        self,
        playbook_id: str,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        author: str | None = None,
        status: str | None = None,
        current_version_id: int | None = None,
        draft_definition: dict | list | str | None = None,
    ) -> bool:
        """Update playbook metadata, keeping existing values for omitted fields.

        ``draft_definition`` stores the working (unpublished) definition as
        JSON so drafts survive reloads; it is cleared on publish. Passing
        ``None`` keeps the current draft.

        Returns False when the playbook does not exist.
        """
        row = self.get_playbook(playbook_id)
        if not row:
            return False
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE playbooks
            SET name=?, description=?, category=?, author=?, status=?,
                current_version_id=?, draft_definition=?, updated_at=?
            WHERE playbook_id=?
            """,
            (
                name if name is not None else row["name"],
                description if description is not None else row["description"],
                category if category is not None else row["category"],
                author if author is not None else row["author"],
                status if status is not None else row["status"],
                current_version_id if current_version_id is not None
                else row["current_version_id"],
                self._dump_json(draft_definition)
                if draft_definition is not None else row["draft_definition"],
                self._now_utc(),
                playbook_id,
            ),
        )
        self.conn.commit()
        return True

    def delete_playbook(self, playbook_id: str) -> bool:
        """Delete a playbook with its versions, assignments, and validations.

        Returns True when the playbook row was removed.
        """
        cur = self.conn.cursor()
        # playbook_versions rows may carry either parent key on legacy
        # databases (integer playbooks.id) or current ones (text playbook_id).
        cur.execute(
            "DELETE FROM playbook_versions WHERE playbook_id IN (%s)"
            % ",".join("?" * len(self._playbook_fk_values(playbook_id))),
            tuple(self._playbook_fk_values(playbook_id)),
        )
        cur.execute(
            "DELETE FROM agent_playbook_assignments WHERE playbook_id = ?",
            (playbook_id,),
        )
        cur.execute(
            "DELETE FROM playbook_validations WHERE playbook_id = ?", (playbook_id,)
        )
        cur.execute(
            "DELETE FROM playbooks WHERE playbook_id = ?", (playbook_id,))
        deleted = cur.rowcount > 0
        self.conn.commit()
        return deleted

    def _playbook_fk_parent(self, playbook_id: str) -> str:
        """Return the parent-key column used by the playbook_versions FK.

        Schemas created earlier referenced playbooks(id) (integer); the
        current schema references playbooks(playbook_id) (text). Reading the
        actual constraint keeps writes compatible with both databases.
        """
        cur = self.conn.cursor()
        for fk in cur.execute("PRAGMA foreign_key_list(playbook_versions)").fetchall():
            if str(fk["table"]).lower() == "playbooks":
                return str(fk["to"] or "id")
        return "playbook_id"

    def _playbook_fk_values(self, playbook_id: str) -> tuple[str]:
        """Return all key values a playbook_versions row can use for this playbook."""
        if self._playbook_fk_parent(playbook_id) == "id":
            row = self.conn.cursor().execute(
                "SELECT id FROM playbooks WHERE playbook_id=?", (playbook_id,)
            ).fetchone()
            if row is not None:
                return (str(int(row[0])), playbook_id)
        return (playbook_id,)

    def publish_playbook_version(
        self,
        playbook_id: str,
        version: str,
        definition: dict | list | str,
        inputs_schema: dict | list | str | None = None,
        notes: str | None = None,
        published_by: str | None = None,
        version_id: str | None = None,
    ) -> int:
        """Append an immutable published version of a playbook.

        The existing playbook row is marked published and its
        current_version_id points to the new version. Published versions are
        never mutated or removed by this helper. Returns the new
        playbook_versions row id (matching workflow_executions.version_id).
        """
        now = self._now_utc()
        # Insert whichever key the actual playbook_versions FK expects
        # (integer playbooks.id on legacy databases, text playbook_id on
        # current ones) — see _playbook_fk_values.
        fk_value = self._playbook_fk_values(playbook_id)[0]
        if version_id is None:
            base = f"{playbook_id}-{version}"
            cur = self.conn.cursor()
            exists = cur.execute(
                "SELECT 1 FROM playbook_versions WHERE version_id = ?", (base,)
            ).fetchone()
            version_id = base if not exists else f"{base}-{uuid.uuid4().hex[:8]}"
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO playbook_versions
            (version_id, playbook_id, version, definition, inputs_schema,
             notes, published_at, published_by)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                version_id, fk_value, version, self._dump_json(definition),
                self._dump_json(inputs_schema), notes, now, published_by,
            ),
        )
        vid = int(cur.lastrowid)
        cur.execute(
            """
            UPDATE playbooks
            SET current_version_id=?, status='published', draft_definition=NULL,
                updated_at=?
            WHERE playbook_id=?
            """,
            (vid, now, playbook_id),
        )
        self.conn.commit()
        return vid

    def get_playbook_version(self, version_id: int | str) -> dict | None:
        """Return one playbook version by integer row id or TEXT version_id."""
        cur = self.conn.cursor()
        if isinstance(version_id, int):
            row = cur.execute(
                "SELECT * FROM playbook_versions WHERE id = ?", (version_id,)
            ).fetchone()
        else:
            row = cur.execute(
                "SELECT * FROM playbook_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_playbook_versions(self, playbook_id: str) -> list[dict]:
        """List all versions of a playbook in publish order (oldest first)."""
        cur = self.conn.cursor()
        fk_values = self._playbook_fk_values(playbook_id)
        placeholders = ",".join("?" * len(fk_values))
        rows = cur.execute(
            f"""
            SELECT * FROM playbook_versions
            WHERE playbook_id IN ({placeholders}) ORDER BY id ASC
            """,
            tuple(fk_values),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── studio: workflow executions & steps ──────────────────────────────

    def create_workflow_execution(
        self,
        execution_id: str,
        playbook_id: str,
        version_id: int,
        job_id: str | None = None,
        assessment_id: str | None = None,
        profile_id: str | None = None,
        inputs: dict | list | str | None = None,
        status: str = "running",
        started_at: str | None = None,
        trigger: str | None = None,
        debug: bool = False,
    ) -> int:
        """Create a durable workflow execution record.

        Returns the workflow_executions row id; re-calling with an existing
        execution_id returns the existing row id without modification.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT id FROM workflow_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row:
            self.conn.commit()
            return int(row[0])
        cur.execute(
            """
            INSERT INTO workflow_executions
            (execution_id, job_id, assessment_id, playbook_id, version_id,
             profile_id, status, inputs, started_at, "trigger", debug)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                execution_id, job_id, assessment_id, playbook_id, version_id,
                profile_id, status, self._dump_json(inputs),
                started_at or self._now_utc(),
                trigger,
                1 if debug else 0,
            ),
        )
        wid = int(cur.lastrowid)
        self.conn.commit()
        return wid

    def update_workflow_execution(
        self,
        execution_id: str,
        status: str | None = None,
        outputs: dict | list | str | None = None,
        error: str | None = None,
        completed_at: str | None = None,
    ) -> bool:
        """Update execution status/outputs/error; omitted fields are kept.

        Returns False when the execution does not exist.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM workflow_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if not row:
            return False
        cur.execute(
            """
            UPDATE workflow_executions
            SET status=?, outputs=?, error=?, completed_at=?
            WHERE execution_id=?
            """,
            (
                status if status is not None else row["status"],
                self._dump_json(outputs) if outputs is not None
                else row["outputs"],
                error if error is not None else row["error"],
                completed_at if completed_at is not None else row["completed_at"],
                execution_id,
            ),
        )
        self.conn.commit()
        return True

    def get_workflow_execution(self, execution_id: str) -> dict | None:
        """Return one workflow execution row by execution_id, or None."""
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM workflow_executions WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_workflow_executions(
        self,
        status: str | None = None,
        playbook_id: str | None = None,
        job_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List workflow executions with optional filters, newest first."""
        cur = self.conn.cursor()
        clauses: list[str] = []
        params: list = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if playbook_id is not None:
            clauses.append("playbook_id = ?")
            params.append(playbook_id)
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = cur.execute(
            f"""
            SELECT * FROM workflow_executions {where}
            ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_step_execution(
        self,
        execution_id: str,
        step_id: str,
        step_type: str | None = None,
        tool_id: str | None = None,
        status: str = "pending",
        inputs: dict | list | str | None = None,
        outputs: dict | list | str | None = None,
        error: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        duration_ms: int | None = None,
    ) -> int:
        """Record one workflow step execution. Returns the row id."""
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO workflow_step_executions
            (execution_id, step_id, step_type, tool_id, status, inputs,
             outputs, error, started_at, completed_at, duration_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                execution_id, step_id, step_type, tool_id, status,
                self._dump_json(inputs), self._dump_json(outputs), error,
                started_at, completed_at, duration_ms,
            ),
        )
        sid = int(cur.lastrowid)
        self.conn.commit()
        return sid

    def update_step_execution(
        self,
        step_execution_id: int,
        status: str | None = None,
        outputs: dict | list | str | None = None,
        error: str | None = None,
        completed_at: str | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        """Update a step execution record; omitted fields are kept.

        Returns False when the step execution row does not exist.
        """
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM workflow_step_executions WHERE id = ?",
            (step_execution_id,),
        ).fetchone()
        if not row:
            return False
        cur.execute(
            """
            UPDATE workflow_step_executions
            SET status=?, outputs=?, error=?, completed_at=?, duration_ms=?
            WHERE id=?
            """,
            (
                status if status is not None else row["status"],
                self._dump_json(outputs) if outputs is not None
                else row["outputs"],
                error if error is not None else row["error"],
                completed_at if completed_at is not None else row["completed_at"],
                duration_ms if duration_ms is not None else row["duration_ms"],
                step_execution_id,
            ),
        )
        self.conn.commit()
        return True

    def list_step_executions(self, execution_id: str) -> list[dict]:
        """List step executions for one workflow execution in record order."""
        cur = self.conn.cursor()
        rows = cur.execute(
            """
            SELECT * FROM workflow_step_executions
            WHERE execution_id = ? ORDER BY id ASC
            """,
            (execution_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_validation(
        self,
        playbook_id: str | None = None,
        version_id: int | None = None,
        status: str = "valid",
        errors: list | dict | str | None = None,
        validated_by: str | None = None,
    ) -> int:
        """Append a validation result. Returns the playbook_validations row id."""
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO playbook_validations
            (version_id, playbook_id, status, errors, validated_at, validated_by)
            VALUES (?,?,?,?,?,?)
            """,
            (
                version_id, playbook_id, status, self._dump_json(errors),
                self._now_utc(), validated_by,
            ),
        )
        rid = int(cur.lastrowid)
        self.conn.commit()
        return rid

    # ── studio: audit & approvals ─────────────────────────────────────────

    def record_audit(
        self,
        event: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        actor: str | None = None,
        data: dict | list | str | None = None,
    ) -> int:
        """Append an audit event. Returns the studio_audit row id."""
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO studio_audit
            (event, entity_type, entity_id, actor, data, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                event, entity_type, entity_id, actor, self._dump_json(data),
                self._now_utc(),
            ),
        )
        rid = int(cur.lastrowid)
        self.conn.commit()
        return rid

    def upsert_approval(
        self,
        gate: str,
        resource_id: str,
        status: str = "pending",
        requested_by: str | None = None,
    ) -> int:
        """Create or refresh a pending approval for (gate, resource_id).

        An existing pending row for the same gate/resource is refreshed;
        approved/closed rows are left as history and a new pending row is
        inserted. Returns the pending_approvals row id.
        """
        now = self._now_utc()
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT id FROM pending_approvals
            WHERE gate=? AND resource_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
            """,
            (gate, resource_id),
        ).fetchone()
        if row:
            aid = int(row[0])
            cur.execute(
                """
                UPDATE pending_approvals
                SET status=?, requested_by=?, requested_at=?
                WHERE id=?
                """,
                (status, requested_by, now, aid),
            )
        else:
            cur.execute(
                """
                INSERT INTO pending_approvals
                (gate, resource_id, status, requested_by, requested_at)
                VALUES (?,?,?,?,?)
                """,
                (gate, resource_id, status, requested_by, now),
            )
            aid = int(cur.lastrowid)
        self.conn.commit()
        return aid

    def get_pending_approval(self, gate: str, resource_id: str) -> dict | None:
        """Return the newest pending approval for (gate, resource_id) or None."""
        cur = self.conn.cursor()
        row = cur.execute(
            """
            SELECT * FROM pending_approvals
            WHERE gate=? AND resource_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
            """,
            (gate, resource_id),
        ).fetchone()
        return dict(row) if row else None

    def approve(
        self,
        approval_id: int,
        approved_by: str,
        status: str = "approved",
    ) -> bool:
        """Close an approval with the given final status. Returns True on success."""
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE pending_approvals
            SET status=?, approved_by=?, approved_at=?
            WHERE id=?
            """,
            (status, approved_by, self._now_utc(), approval_id),
        )
        ok = cur.rowcount > 0
        self.conn.commit()
        return ok

    def _now_utc(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat() + "Z"

    # ── backward-compatible wrappers (v1 API preserved) ──────────────────

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
        now = self._now_utc()
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
            tid = int(cur.lastrowid)
        self.conn.commit()
        return tid

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
        assessment_id: str | None = None,
        job_id: str | None = None,
        workflow_name: str | None = None,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO scans (target_id, tool, command, started_at, completed_at, duration, success, findings_count, artifact_uri, assessment_id, job_id, workflow_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                target_id, tool, command, started_at, completed_at, duration,
                int(bool(success)), int(findings_count), artifact_uri,
                assessment_id, job_id, workflow_name,
            ),
        )
        sid = cur.lastrowid
        self.conn.commit()
        return int(sid)

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
        confidence: float = 0.5,
        validation_status: str = "observed",
        source_tools: str | None = None,
        evidence_refs: str | None = None,
    ) -> int:
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO findings (target_id, scan_id, tool, finding_type, severity, title, description, evidence, port, service, url, status, created_at, updated_at, confidence, validation_status, source_tools, evidence_refs, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                target_id, scan_id, tool, finding_type, severity, title,
                description, evidence, port, service, url, status,
                now, now, confidence, validation_status,
                source_tools or "[]", evidence_refs or "[]", now, now,
            ),
        )
        fid = cur.lastrowid
        self.conn.commit()
        return int(fid)

    def add_credential(
        self,
        target_id: int,
        service: str,
        username: str,
        password: str | None = None,
        hash_value: str | None = None,
        source_tool: str = "",
        notes: str = "",
        asset_id: str | None = None,
        service_id: str | None = None,
    ) -> int:
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO credentials (target_id, service, username, password, hash, source_tool, captured_at, notes, asset_id, service_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                target_id, service, username, password, hash_value, source_tool,
                now, notes, asset_id, service_id,
            ),
        )
        cid = cur.lastrowid
        self.conn.commit()
        return int(cid)

    def save_workflow_run(self, run_id: str, playbook_name: str, status: str,
                         completed_steps: list, state: dict) -> None:
        import json as _json
        now = self._now_utc()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO workflow_runs (run_id, playbook_name, status, completed_steps,
                                      state_json, started_at, finished_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status,
                completed_steps=excluded.completed_steps,
                state_json=excluded.state_json,
                finished_at=excluded.finished_at
            """,
            (run_id, playbook_name, status, _json.dumps(completed_steps),
             _json.dumps(state, default=str), now, now if status != "running" else None),
        )
        self.conn.commit()

    def load_workflow_run(self, run_id: str) -> dict | None:
        import json as _json
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["completed_steps"] = _json.loads(d.get("completed_steps") or "[]")
        except Exception:  # noqa: BLE001
            d["completed_steps"] = []
        try:
            d["state"] = _json.loads(d.get("state_json") or "{}")
        except Exception:  # noqa: BLE001
            d["state"] = {}
        return d

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001, S110
            pass

_db_singleton: DBManager | None = None


def get_db() -> DBManager | None:
    global _db_singleton
    if _db_singleton is None:
        try:
            if getattr(config, "db_enabled", True):
                _db_singleton = DBManager(config.db_path)
                _db_singleton.ensure_schema()
        except Exception:  # noqa: BLE001
            _db_singleton = None
    return _db_singleton


def _now():
    import datetime
    from datetime import timezone

    return datetime.datetime.now(timezone.utc).isoformat() + "Z"
