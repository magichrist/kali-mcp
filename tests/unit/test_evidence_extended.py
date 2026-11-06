"""Unit tests for evidence storage/retrieval (kali_mcp/evidence.py).

Covers store_evidence (file + DB row) and get_evidence (retrieve by ID).
"""

from __future__ import annotations

import dataclasses
import re

from kali_mcp.evidence import EVIDENCE_DIR, get_evidence, store_evidence


def _setup_db(tmp_path, monkeypatch):
    from kali_mcp.config import config as real_config
    from kali_mcp.db import manager as dbm

    new_cfg = dataclasses.replace(
        real_config,
        db_path=tmp_path / "db.sqlite",
        artifact_dir=tmp_path / "artifacts",
    )
    monkeypatch.setattr(dbm, "config", new_cfg)
    monkeypatch.setattr(dbm, "_db_singleton", None)
    monkeypatch.setattr("kali_mcp.evidence.config", new_cfg)

    db = dbm.get_db()
    target_id = db.upsert_target("10.0.0.1", target_type="host")
    db.add_scan(
        target_id,
        "nmap",
        "nmap 10.0.0.1",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:01:00Z",
        60.0,
        1,
        0,
        None,
        assessment_id="assess_abc",
        job_id="job_xyz",
    )
    return db


class TestStoreEvidenceExtended:
    def test_writes_artifact_file_and_records_row(self, tmp_path, monkeypatch):
        db = _setup_db(tmp_path, monkeypatch)

        evidence_id = store_evidence(
            tool="nmap",
            target="10.0.0.1",
            artifact_type="stdout",
            content="Nmap scan report for 10.0.0.1\n",
            assessment_id="assess_abc",
            job_id="job_xyz",
        )

        assert re.fullmatch(r"evidence_[0-9a-f]{12}", evidence_id)

        # File was written under the evidence dir.
        files = list(
            (tmp_path / "artifacts" / "evidence").rglob(
                f"{evidence_id}_*.txt"
            )
        )
        assert len(files) == 1
        assert files[0].read_text() == "Nmap scan report for 10.0.0.1\n"

        # Row recorded in evidence_artifacts.
        row = get_evidence(evidence_id)
        assert row is not None
        assert row["evidence_id"] == evidence_id
        assert row["tool"] == "nmap"
        assert row["target"] == "10.0.0.1"
        assert row["artifact_type"] == "stdout"
        assert row["content_path"] == str(files[0])
        assert row["content_size"] == len("Nmap scan report for 10.0.0.1\n")
        assert row["assessment_id"] == "assess_abc"
        assert row["job_id"] == "job_xyz"
        assert "captured_at" in row

    def test_stderr_artifact_type(self, tmp_path, monkeypatch):
        db = _setup_db(tmp_path, monkeypatch)

        evidence_id = store_evidence(
            tool="nmap",
            target="10.0.0.1",
            artifact_type="stderr",
            content="nmap: error\n",
            assessment_id="assess_abc",
        )

        row = get_evidence(evidence_id)
        assert row is not None
        assert row["artifact_type"] == "stderr"

    def test_file_content_persists(self, tmp_path, monkeypatch):
        db = _setup_db(tmp_path, monkeypatch)

        content = "multi\nline\ncontent\n"
        evidence_id = store_evidence(
            tool="httpx",
            target="example.com",
            artifact_type="file",
            content=content,
        )

        files = list(
            (tmp_path / "artifacts" / "evidence").rglob(
                f"{evidence_id}_*.txt"
            )
        )
        assert len(files) == 1
        assert files[0].read_text() == content

    def test_get_evidence_unknown_returns_none(self, tmp_path, monkeypatch):
        from kali_mcp.db import manager as dbm

        monkeypatch.setattr(dbm, "_db_singleton", None)
        assert get_evidence("evidence_000000000000") is None

    def test_store_evidence_without_db_returns_id(self, tmp_path, monkeypatch):
        from kali_mcp.db import manager as dbm

        monkeypatch.setattr(dbm, "get_db", lambda: None)
        monkeypatch.setattr("kali_mcp.evidence.EVIDENCE_DIR", tmp_path / "evidence")
        evidence_id = store_evidence(
            tool="nmap",
            target="10.0.0.1",
            artifact_type="stdout",
            content="hello",
        )
        assert re.fullmatch(r"evidence_[0-9a-f]{12}", evidence_id)


class TestEvidenceDirConstant:
    def test_constant_points_at_artifacts_evidence(self):
        assert str(EVIDENCE_DIR).endswith("artifacts/evidence")
