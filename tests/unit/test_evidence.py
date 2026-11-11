"""Unit tests for the evidence reference system (kmcp/evidence.py)."""

from __future__ import annotations

import dataclasses
import re

from kmcp.evidence import EVIDENCE_DIR, get_evidence, store_evidence


class TestStoreEvidence:
    def test_writes_artifact_file_and_records_row(self, tmp_path, monkeypatch):
        from kmcp.config import config as real_config
        from kmcp.db import manager as dbm

        new_cfg = dataclasses.replace(
            real_config,
            db_path=tmp_path / "db.sqlite",
            artifact_dir=tmp_path / "artifacts",
        )
        monkeypatch.setattr(dbm, "config", new_cfg)
        monkeypatch.setattr(dbm, "_db_singleton", None)
        monkeypatch.setattr("kmcp.evidence.config", new_cfg)

        db = dbm.get_db()
        # evidence_artifacts.assessment_id references scans(assessment_id),
        # so a scan row must exist first.
        target_id = db.upsert_target("127.0.0.1")
        db.add_scan(
            target_id,
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

        evidence_id = store_evidence(
            tool="nmap",
            target="127.0.0.1",
            artifact_type="stdout",
            content="Nmap scan report for 127.0.0.1\n",
            assessment_id="assess_abc",
            job_id="job_xyz",
        )

        assert re.fullmatch(r"evidence_[0-9a-f]{12}", evidence_id)

        # File was written under the evidence dir.
        files = list((tmp_path / "artifacts" / "evidence").rglob(f"{evidence_id}_*.txt"))
        assert len(files) == 1
        assert files[0].read_text() == "Nmap scan report for 127.0.0.1\n"

        # Row recorded in evidence_artifacts.
        row = get_evidence(evidence_id)
        assert row is not None
        assert row["evidence_id"] == evidence_id
        assert row["tool"] == "nmap"
        assert row["target"] == "127.0.0.1"
        assert row["artifact_type"] == "stdout"
        assert row["content_path"] == str(files[0])
        assert row["content_size"] == len("Nmap scan report for 127.0.0.1\n")
        assert row["assessment_id"] == "assess_abc"
        assert row["job_id"] == "job_xyz"
        assert "captured_at" in row

    def test_constant_points_at_artifacts_evidence(self):
        assert str(EVIDENCE_DIR).endswith("artifacts/evidence")

    def test_get_evidence_unknown_returns_none(self, tmp_path, monkeypatch):
        from kmcp.db import manager as dbm

        monkeypatch.setattr(dbm, "_db_singleton", None)
        assert get_evidence("evidence_000000000000") is None

    def test_store_evidence_without_db_returns_id(self, tmp_path, monkeypatch):
        from kmcp.db import manager as dbm

        monkeypatch.setattr(dbm, "get_db", lambda: None)
        monkeypatch.setattr("kmcp.evidence.EVIDENCE_DIR", tmp_path / "evidence")
        evidence_id = store_evidence(
            tool="nmap",
            target="127.0.0.1",
            artifact_type="stdout",
            content="hello",
        )
        assert re.fullmatch(r"evidence_[0-9a-f]{12}", evidence_id)
