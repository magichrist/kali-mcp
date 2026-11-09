"""Unit tests for the Assessment Diff Engine (assessment_diff.py)."""

from __future__ import annotations

import pytest

from kali_mcp.intelligence import AssessmentDiffer, DiffResult


class MockDB:
    """Mock database manager for testing the differ."""

    def __init__(self, assessments: dict[str, dict]):
        self._assessments = assessments
        self.conn = None

    def get_findings_by_assessment(self, assessment_id: str) -> dict:
        data = self._assessments.get(assessment_id, {})
        return {"count": len(data.get("findings", [])), "findings": data.get("findings", [])}


@pytest.fixture()
def db_both() -> MockDB:
    return MockDB(
        {
            "assess_a": {
                "findings": [
                    {
                        "id": "f1",
                        "title": "SSL Expired",
                        "severity": "high",
                        "confidence": 0.7,
                        "asset_id": "example.com",
                        "validation_status": "observed",
                    },
                    {
                        "id": "f2",
                        "title": "Open SSH",
                        "severity": "medium",
                        "confidence": 0.5,
                        "asset_id": "127.0.0.1",
                        "validation_status": "observed",
                    },
                ]
            },
            "assess_b": {
                "findings": [
                    {
                        "id": "f1",
                        "title": "SSL Expired",
                        "severity": "critical",
                        "confidence": 0.9,
                        "asset_id": "example.com",
                        "validation_status": "validated",
                    },
                    {
                        "id": "f3",
                        "title": "Reflected XSS",
                        "severity": "high",
                        "confidence": 0.8,
                        "asset_id": "example.com",
                        "validation_status": "observed",
                    },
                ]
            },
        }
    )


# ── diff: new findings ───────────────────────────────────────────────


def test_diff_detects_new_findings(db_both):
    differ = AssessmentDiffer(db_manager=db_both)
    result = differ.diff("assess_a", "assess_b")
    new_titles = {f["title"] for f in result.new_findings}
    assert new_titles == {"Reflected XSS"}


# ── diff: resolved findings ──────────────────────────────────────────


def test_diff_detects_resolved_findings(db_both):
    differ = AssessmentDiffer(db_manager=db_both)
    result = differ.diff("assess_a", "assess_b")
    resolved_titles = {f["title"] for f in result.resolved_findings}
    assert resolved_titles == {"Open SSH"}


# ── diff: changed findings ───────────────────────────────────────────


def test_diff_detects_changed_severity_and_confidence(db_both):
    differ = AssessmentDiffer(db_manager=db_both)
    result = differ.diff("assess_a", "assess_b")
    assert len(result.changed_findings) == 1
    cf = result.changed_findings[0]
    assert cf["title"] == "SSL Expired"
    changes = cf["changes"]
    assert "severity" in changes
    assert changes["severity"]["from"] == "high"
    assert changes["severity"]["to"] == "critical"
    assert "confidence" in changes
    assert changes["confidence"]["from"] == 0.7
    assert changes["confidence"]["to"] == 0.9


# ── diff: no changes ─────────────────────────────────────────────────


def test_diff_no_changes_when_identical(db_both):
    differ = AssessmentDiffer(db_manager=db_both)
    result = differ.diff("assess_a", "assess_a")
    assert len(result.new_findings) == 0
    assert len(result.resolved_findings) == 0
    assert len(result.changed_findings) == 0
    assert result.summary["new_findings_count"] == 0


# ── diff: empty assessments ──────────────────────────────────────────


def test_diff_empty_baseline():
    db = MockDB({"assess_a": {"findings": []}, "assess_b": {"findings": []}})
    differ = AssessmentDiffer(db_manager=db)
    result = differ.diff("assess_a", "assess_b")
    assert len(result.new_findings) == 0
    assert len(result.resolved_findings) == 0


# ── DiffResult ───────────────────────────────────────────────────────


def test_diff_result_to_dict():
    dr = DiffResult(
        assessment_id_a="a",
        assessment_id_b="b",
        new_findings=[{"id": "f1"}],
        resolved_findings=[{"id": "f2"}],
        summary={"new_findings_count": 1, "resolved_findings_count": 1},
    )
    d = dr.to_dict()
    assert d["assessment_id_a"] == "a"
    assert d["assessment_id_b"] == "b"
    assert d["summary"]["new_findings_count"] == 1
