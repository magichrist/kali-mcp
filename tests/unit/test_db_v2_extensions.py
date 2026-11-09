"""Unit tests for v2 DB extensions in src/kali_mcp/db/manager.py.

Covers upsert_asset, add_service, add_technology, add_asset_relationship,
add_evidence_artifact, add_finding_correlation, get_asset_graph, query_findings,
get_evidence, v2 column extensions, and idempotent column migrations.
"""

from __future__ import annotations

import pytest

from kali_mcp.db.manager import DBManager


@pytest.fixture()
def db(tmp_path):
    manager = DBManager(tmp_path / "test.sqlite")
    manager.ensure_schema()
    yield manager
    manager.close()


def _add_target_scan_finding(db):
    """Seed one target, scan, and finding with v2 columns populated."""
    tid = db.upsert_target("127.0.0.1", target_type="host")
    sid = db.add_scan(
        tid,
        "nmap",
        "nmap -sT 127.0.0.1",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:05Z",
        5.0,
        1,
        1,
        None,
        assessment_id="assess_abc",
        job_id="job_xyz",
        workflow_name="recon",
    )
    fid = db.add_finding(
        tid,
        sid,
        "nmap",
        "open_port",
        "medium",
        "SSH exposed",
        "tcp/22 open",
        "nmap output",
        port=22,
        service="ssh",
        confidence=0.9,
        validation_status="confirmed",
        source_tools='["nmap"]',
        evidence_refs='["evidence_1"]',
    )
    return tid, sid, fid


class TestUpsertAsset:
    def test_insert_then_update_is_idempotent(self, db):
        tid = db.upsert_target("127.0.0.1", target_type="host")
        aid1 = db.upsert_asset(
            asset_id="asset_127.0.0.1",
            asset_type="host",
            name="127.0.0.1",
            target_id=tid,
            scope="in-scope",
            tags="web",
        )
        assert aid1 > 0
        row = db.conn.execute(
            "SELECT tags, scope FROM assets WHERE asset_id = ?",
            ("asset_127.0.0.1",),
        ).fetchone()
        assert row["tags"] == "web"
        assert row["scope"] == "in-scope"

        # Same asset_id -> same row, fields updated.
        aid2 = db.upsert_asset(
            asset_id="asset_127.0.0.1",
            asset_type="host",
            name="127.0.0.1",
            target_id=tid,
            tags="web,dmz",
            scope="out-of-scope",
        )
        assert aid2 == aid1
        row = db.conn.execute(
            "SELECT tags, scope, last_seen FROM assets WHERE id = ?", (aid1,)
        ).fetchone()
        assert row["tags"] == "web,dmz"
        assert row["scope"] == "out-of-scope"
        assert row["last_seen"] is not None

    def test_minimal_fields(self, db):
        aid = db.upsert_asset(asset_id="asset_min", asset_type="ip", name="127.0.0.1")
        assert aid > 0
        row = db.conn.execute(
            "SELECT asset_type, name, first_seen, last_seen FROM assets WHERE id=?",
            (aid,),
        ).fetchone()
        assert row["asset_type"] == "ip"
        assert row["name"] == "127.0.0.1"
        assert row["first_seen"] is not None
        assert row["last_seen"] is not None


class TestAddService:
    def test_insert_and_update(self, db):
        tid = db.upsert_target("127.0.0.1", target_type="host")
        aid = db.upsert_asset(
            asset_id="asset_127.0.0.1",
            asset_type="host",
            name="127.0.0.1",
            target_id=tid,
        )
        sid1 = db.add_service(
            service_id="svc_127.0.0.1_22_tcp",
            asset_id=aid,
            port=22,
            protocol="tcp",
            service_name="ssh",
            version="OpenSSH 8.2",
        )
        assert sid1 > 0
        row = db.conn.execute(
            "SELECT service_name, version FROM services WHERE id=?", (sid1,)
        ).fetchone()
        assert row["service_name"] == "ssh"
        assert row["version"] == "OpenSSH 8.2"

        # Same service_id -> same row, version updated.
        sid2 = db.add_service(
            service_id="svc_127.0.0.1_22_tcp",
            asset_id=aid,
            port=22,
            protocol="tcp",
            service_name="ssh",
            version="OpenSSH 8.4",
        )
        assert sid2 == sid1
        row = db.conn.execute("SELECT version FROM services WHERE id=?", (sid1,)).fetchone()
        assert row["version"] == "OpenSSH 8.4"


class TestAddTechnology:
    def test_insert_and_update(self, db):
        tid = db.upsert_target("127.0.0.1", target_type="host")
        aid = db.upsert_asset(
            asset_id="asset_127.0.0.1",
            asset_type="host",
            name="127.0.0.1",
            target_id=tid,
        )
        sid = db.add_service(
            service_id="svc_127.0.0.1_80_tcp",
            asset_id=aid,
            port=80,
            protocol="tcp",
            service_name="http",
        )
        tid1 = db.add_technology(
            tech_id="tech_apache",
            service_id=sid,
            name="Apache",
            version="2.4.41",
            category="web_server",
            confidence=0.9,
        )
        assert tid1 > 0
        row = db.conn.execute(
            "SELECT name, category, confidence FROM technologies WHERE id=?",
            (tid1,),
        ).fetchone()
        assert row["name"] == "Apache"
        assert row["category"] == "web_server"
        assert row["confidence"] == 0.9

        tid2 = db.add_technology(
            tech_id="tech_apache",
            service_id=sid,
            name="Apache",
            category="web_server",
            confidence=0.99,
        )
        assert tid2 == tid1
        row = db.conn.execute("SELECT confidence FROM technologies WHERE id=?", (tid1,)).fetchone()
        assert row["confidence"] == 0.99

    def test_null_service_id_allowed(self, db):
        tid = db.add_technology(
            tech_id="tech_lang",
            service_id=None,
            name="Python",
            category="language",
        )
        assert tid > 0
        row = db.conn.execute("SELECT service_id FROM technologies WHERE id=?", (tid,)).fetchone()
        assert row["service_id"] is None


class TestAddAssetRelationship:
    def test_insert_and_update(self, db):
        aid_ip = db.upsert_asset(asset_id="asset_ip_127.0.0.1", asset_type="ip", name="127.0.0.1")
        aid_domain = db.upsert_asset(
            asset_id="asset_dom_example",
            asset_type="domain",
            name="example.com",
        )
        rid1 = db.add_asset_relationship(
            source_asset_id=aid_ip,
            target_asset_id=aid_domain,
            relationship="resolves_to",
            confidence=0.8,
            source_tool="nmap",
        )
        assert rid1 > 0
        row = db.conn.execute(
            "SELECT relationship, confidence, source_tool FROM asset_relationships WHERE id=?",
            (rid1,),
        ).fetchone()
        assert row["relationship"] == "resolves_to"
        assert row["confidence"] == 0.8
        assert row["source_tool"] == "nmap"

        # Same (source, target, relationship) -> updated in place.
        rid2 = db.add_asset_relationship(
            source_asset_id=aid_ip,
            target_asset_id=aid_domain,
            relationship="resolves_to",
            confidence=0.95,
            source_tool="masscan",
        )
        assert rid2 == rid1
        row = db.conn.execute(
            "SELECT confidence, source_tool FROM asset_relationships WHERE id=?",
            (rid1,),
        ).fetchone()
        assert row["confidence"] == 0.95
        assert row["source_tool"] == "masscan"


class TestAddEvidenceArtifact:
    def test_insert_row(self, db):
        tid = db.upsert_target("127.0.0.1", target_type="host")
        db.add_scan(
            tid,
            "nmap",
            "nmap 127.0.0.1",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:01:00Z",
            60.0,
            1,
            0,
            None,
            assessment_id="assess_abc",
            job_id="job_xyz",
        )
        aid = db.add_evidence_artifact(
            evidence_id="evidence_abc123def456",
            tool="nmap",
            target="127.0.0.1",
            artifact_type="stdout",
            content_path="/artifacts/evidence/evidence_abc123def456_stdout.txt",
            content_size=123,
            assessment_id="assess_abc",
            job_id="job_xyz",
        )
        assert aid > 0
        row = db.conn.execute(
            "SELECT * FROM evidence_artifacts WHERE evidence_id=?",
            ("evidence_abc123def456",),
        ).fetchone()
        assert row is not None
        assert row["tool"] == "nmap"
        assert row["target"] == "127.0.0.1"
        assert row["artifact_type"] == "stdout"
        assert row["content_size"] == 123
        assert row["assessment_id"] == "assess_abc"
        assert row["job_id"] == "job_xyz"
        assert row["captured_at"] is not None


class TestAddFindingCorrelation:
    def test_insert_row(self, db):
        _tid, _sid, fid = _add_target_scan_finding(db)
        cid = db.add_finding_correlation(
            correlation_id="corr_1",
            finding_id=fid,
            observation_id=fid,
            tool="nmap",
            confidence_contribution=0.7,
        )
        assert cid > 0
        row = db.conn.execute(
            "SELECT * FROM finding_correlation WHERE correlation_id=?",
            ("corr_1",),
        ).fetchone()
        assert row is not None
        assert row["finding_id"] == fid
        assert row["observation_id"] == fid
        assert row["tool"] == "nmap"
        assert row["confidence_contribution"] == 0.7

    def test_insert_or_ignore_duplicate(self, db):
        _tid, _sid, fid = _add_target_scan_finding(db)
        cid1 = db.add_finding_correlation(
            correlation_id="corr_dup",
            finding_id=fid,
            observation_id=fid,
            tool="nmap",
        )
        cid2 = db.add_finding_correlation(
            correlation_id="corr_dup",
            finding_id=fid,
            observation_id=fid,
            tool="nmap",
        )
        assert cid1 == cid2  # INSERT OR IGNORE keeps the first row id


class TestGetAssetGraph:
    def test_unfiltered_returns_all_assets(self, db):
        aid1 = db.upsert_asset(asset_id="asset_a", asset_type="host", name="host_a")
        aid2 = db.upsert_asset(asset_id="asset_b", asset_type="domain", name="example.com")
        db.add_asset_relationship(aid1, aid2, "contains")
        graph = db.get_asset_graph()
        assert len(graph["assets"]) == 2
        assert len(graph["relationships"]) == 1

    def test_filtered_by_target_name(self, db):
        db.upsert_asset(asset_id="asset_a", asset_type="host", name="host_a")
        db.upsert_asset(asset_id="asset_b", asset_type="domain", name="example.com")
        graph = db.get_asset_graph(target="host_a")
        assert len(graph["assets"]) == 1
        assert graph["assets"][0]["name"] == "host_a"

    def test_filtered_by_target_ip(self, db):
        db.upsert_asset(
            asset_id="asset_a",
            asset_type="ip",
            name="127.0.0.1",
            ip_address="127.0.0.1",
        )
        graph = db.get_asset_graph(target="127.0.0.1")
        assert len(graph["assets"]) == 1

    def test_filtered_by_target_domain(self, db):
        db.upsert_asset(
            asset_id="asset_a",
            asset_type="domain",
            name="example.com",
            domain="example.com",
        )
        graph = db.get_asset_graph(target="example.com")
        assert len(graph["assets"]) == 1

    def test_filtered_no_match(self, db):
        db.upsert_asset(asset_id="asset_a", asset_type="host", name="host_a")
        graph = db.get_asset_graph(target="nonexistent")
        assert len(graph["assets"]) == 0
        assert len(graph["relationships"]) == 0


class TestQueryFindings:
    def test_insert_and_query_all(self, db):
        _tid, _sid, fid = _add_target_scan_finding(db)
        result = db.query_findings()
        assert result["count"] == 1
        assert len(result["findings"]) == 1
        assert result["findings"][0]["id"] == fid

    def test_filter_by_target(self, db):
        _tid, _sid, fid = _add_target_scan_finding(db)
        tid2 = db.upsert_target("otherhost.example", target_type="host")
        sid2 = db.add_scan(
            tid2,
            "nmap",
            "nmap otherhost.example",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:01:00Z",
            5.0,
            1,
            0,
            None,
        )
        db.add_finding(
            tid2,
            sid2,
            "nmap",
            "open_port",
            "high",
            "Other",
            "d",
            "e",
        )
        result = db.query_findings(target="127.0.0.1")
        assert result["count"] == 1
        assert result["findings"][0]["id"] == fid

    def test_filter_by_severity(self, db):
        _tid, _sid, _fid = _add_target_scan_finding(db)
        tid2 = db.upsert_target("127.0.0.1", target_type="host")
        sid2 = db.add_scan(
            tid2,
            "nmap",
            "nmap 127.0.0.1",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:01:00Z",
            5.0,
            1,
            0,
            None,
        )
        db.add_finding(
            tid2,
            sid2,
            "nmap",
            "open_port",
            "high",
            "Other",
            "d",
            "e",
        )
        result = db.query_findings(severity="high")
        assert result["count"] == 1
        assert result["findings"][0]["severity"] == "high"

    def test_filter_by_validation_status(self, db):
        _tid, _sid, fid = _add_target_scan_finding(db)
        tid2 = db.upsert_target("127.0.0.1", target_type="host")
        sid2 = db.add_scan(
            tid2,
            "nmap",
            "nmap 127.0.0.1",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:01:00Z",
            5.0,
            1,
            0,
            None,
        )
        db.add_finding(
            tid2,
            sid2,
            "nmap",
            "open_port",
            "medium",
            "Other",
            "d",
            "e",
            validation_status="observed",
        )
        result = db.query_findings(validation_status="confirmed")
        assert result["count"] == 1
        assert result["findings"][0]["id"] == fid

    def test_filter_by_tool(self, db):
        _tid, _sid, _fid = _add_target_scan_finding(db)
        tid2 = db.upsert_target("127.0.0.1", target_type="host")
        sid2 = db.add_scan(
            tid2,
            "masscan",
            "masscan 127.0.0.1",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:01:00Z",
            5.0,
            1,
            0,
            None,
        )
        db.add_finding(
            tid2,
            sid2,
            "masscan",
            "open_port",
            "medium",
            "Other",
            "d",
            "e",
        )
        result = db.query_findings(tool="masscan")
        assert result["count"] == 1
        assert result["findings"][0]["tool"] == "masscan"

    def test_pagination_limit_offset(self, db):
        tid, sid, _ = _add_target_scan_finding(db)
        for i in range(5):
            db.add_finding(
                tid,
                sid,
                "nmap",
                "open_port",
                "low",
                f"Finding {i}",
                "d",
                "e",
            )
        result = db.query_findings(limit=3, offset=0)
        assert result["count"] == 6  # 1 seeded + 5 additional
        assert len(result["findings"]) == 3
        result2 = db.query_findings(limit=3, offset=3)
        assert len(result2["findings"]) == 3

    def test_v2_columns_default_and_values(self, db):
        _tid, _sid, fid = _add_target_scan_finding(db)
        row = db.conn.execute(
            "SELECT confidence, validation_status, source_tools, evidence_refs "
            "FROM findings WHERE id=?",
            (fid,),
        ).fetchone()
        assert row["confidence"] == 0.9
        assert row["validation_status"] == "confirmed"
        assert row["source_tools"] == '["nmap"]'
        assert row["evidence_refs"] == '["evidence_1"]'


class TestGetEvidence:
    def test_get_evidence_row(self, db):
        tid = db.upsert_target("127.0.0.1", target_type="host")
        db.add_scan(
            tid,
            "nmap",
            "nmap 127.0.0.1",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:01:00Z",
            60.0,
            1,
            0,
            None,
            assessment_id="assess_abc",
            job_id="job_xyz",
        )
        db.add_evidence_artifact(
            evidence_id="evidence_row123",
            tool="nmap",
            target="127.0.0.1",
            artifact_type="stdout",
            content_path="/tmp/evidence_row123_stdout.txt",
            content_size=42,
            assessment_id="assess_abc",
            job_id="job_xyz",
        )
        row = db.get_evidence("evidence_row123")
        assert row is not None
        assert row["evidence_id"] == "evidence_row123"
        assert row["tool"] == "nmap"
        assert row["content_size"] == 42

    def test_get_evidence_unknown_returns_none(self, db):
        assert db.get_evidence("evidence_does_not_exist") is None


class TestV2ColumnExtensions:
    def test_targets_v2_columns_exist(self, db):
        cols = {row[1] for row in db.conn.execute("PRAGMA table_info(targets)")}
        for col in ("asset_id", "domain", "ip_address", "first_seen", "last_seen"):
            assert col in cols

    def test_scans_v2_columns_exist(self, db):
        cols = {row[1] for row in db.conn.execute("PRAGMA table_info(scans)")}
        for col in ("assessment_id", "job_id", "workflow_name"):
            assert col in cols

    def test_findings_v2_columns_exist(self, db):
        cols = {row[1] for row in db.conn.execute("PRAGMA table_info(findings)")}
        for col in (
            "confidence",
            "validation_status",
            "source_tools",
            "evidence_refs",
            "first_seen",
            "last_seen",
        ):
            assert col in cols

    def test_credentials_v2_columns_exist(self, db):
        cols = {row[1] for row in db.conn.execute("PRAGMA table_info(credentials)")}
        for col in ("asset_id", "service_id"):
            assert col in cols


class TestIdempotentMigrations:
    def test_ensure_schema_twice_does_not_raise(self, db):
        db.ensure_schema()
        db.ensure_schema()

    def test_existing_column_migration_skipped(self, db):
        # All v2 columns already exist from the fixture; re-running
        # ensure_schema must not attempt to re-add them (no duplicate error).
        before = {row[1] for row in db.conn.execute("PRAGMA table_info(targets)")}
        db.ensure_schema()
        after = {row[1] for row in db.conn.execute("PRAGMA table_info(targets)")}
        assert before == after
