"""Unit tests for the Assessment Coverage Tracker (coverage_tracker.py)."""

from __future__ import annotations

import pytest

from kali_mcp.intelligence import CoverageTracker


@pytest.fixture()
def tracker() -> CoverageTracker:
    return CoverageTracker()


# ── record_coverage ──────────────────────────────────────────────────


def test_record_coverage_basic(tracker):
    tracker.record_coverage(
        assessment_id="assess_1",
        asset_id="asset_1",
        service="http/80",
        tool="nmap",
        result_status="findings",
        findings_count=3,
    )
    records = tracker.get_records("assess_1")
    assert len(records) == 1
    assert records[0]["asset_id"] == "asset_1"
    assert records[0]["service"] == "http/80"
    assert records[0]["tool"] == "nmap"
    assert records[0]["result_status"] == "findings"
    assert records[0]["findings_count"] == 3


def test_record_coverage_multiple_tools(tracker):
    tracker.record_coverage("assess_1", "asset_1", None, "nmap", "scanned", 0)
    tracker.record_coverage("assess_1", "asset_1", None, "nuclei", "findings", 2)
    tracker.record_coverage("assess_1", "asset_2", "http/443", "nmap", "scanned", 0)
    records = tracker.get_records("assess_1")
    assert len(records) == 3


# ── get_coverage_summary ─────────────────────────────────────────────


def test_get_coverage_summary_empty(tracker):
    summary = tracker.get_coverage_summary("empty_assess")
    assert summary["assessment_id"] == "empty_assess"
    assert summary["percent_covered"] == 0.0
    assert summary["assets_discovered"] == 0
    assert summary["assets_scanned"] == 0
    assert summary["tools_count"] == 0
    assert summary["total_findings"] == 0


def test_get_coverage_summary_with_data(tracker):
    tracker.record_coverage("assess_1", "asset_1", "http/80", "nmap", "findings", 3)
    tracker.record_coverage("assess_1", "asset_1", None, "nuclei", "no_findings", 0)
    tracker.record_coverage("assess_1", "asset_2", "http/443", "nmap", "findings", 1)
    summary = tracker.get_coverage_summary("assess_1")
    assert summary["percent_covered"] == 100.0
    assert summary["assets_discovered"] == 2
    assert summary["assets_scanned"] == 2
    assert summary["services_scanned"] == 3
    assert summary["tools_used"] == ["nmap", "nuclei"]
    assert summary["tools_count"] == 2
    assert summary["total_findings"] == 4


def test_percent_covered_partial(tracker):
    # asset_1 discovered but only asset_2 scanned
    tracker.record_coverage("assess_1", "asset_2", None, "nmap", "scanned", 0)
    tracker._assets_seen["assess_1"].add("asset_1")
    summary = tracker.get_coverage_summary("assess_1")
    assert summary["percent_covered"] == 50.0


# ── get_coverage_gaps ────────────────────────────────────────────────


def test_get_coverage_gaps_empty(tracker):
    gaps = tracker.get_coverage_gaps("empty_assess")
    assert gaps == []


def test_get_coverage_gaps_asset_unscanned(tracker):
    tracker.record_coverage("assess_1", "asset_1", None, "nmap", "scanned", 0)
    tracker._assets_seen["assess_1"].add("asset_2")
    # asset_2 discovered but never scanned
    gaps = tracker.get_coverage_gaps("assess_1")
    unscanned = [g for g in gaps if g["type"] == "asset_unscanned"]
    assert len(unscanned) == 1
    assert unscanned[0]["asset_id"] == "asset_2"


def test_get_coverage_gaps_service_unscanned(tracker):
    tracker.record_coverage("assess_1", "asset_1", "http/80", "nmap", "scanned", 0)
    # http/443 discovered but never scanned
    tracker._services_scanned["assess_1"].add(("asset_1", "http/443"))
    gaps = tracker.get_coverage_gaps("assess_1")
    unscanned = [g for g in gaps if g["type"] == "service_unscanned"]
    assert len(unscanned) == 1
    assert unscanned[0]["asset_id"] == "asset_1"
    assert unscanned[0]["service"] == "http/443"


def test_get_coverage_gaps_asset_no_findings(tracker):
    tracker.record_coverage("assess_1", "asset_1", None, "nmap", "no_findings", 0)
    gaps = tracker.get_coverage_gaps("assess_1")
    no_findings = [g for g in gaps if g["type"] == "asset_no_findings"]
    assert len(no_findings) == 1
    assert no_findings[0]["asset_id"] == "asset_1"
