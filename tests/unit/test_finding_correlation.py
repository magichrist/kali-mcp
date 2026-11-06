"""Unit tests for the Finding Correlation Engine (finding_correlation.py)."""

from __future__ import annotations

import pytest

from kali_mcp.intelligence import Finding, FindingCorrelator


@pytest.fixture()
def correlator() -> FindingCorrelator:
    return FindingCorrelator()


# ── Finding dataclass ────────────────────────────────────────────────

def test_finding_defaults():
    f = Finding(finding_id="f1", title="Test finding")
    assert f.finding_id == "f1"
    assert f.title == "Test finding"
    assert f.severity == "informational"
    assert f.confidence == 0.5
    assert f.validation_status == "observed"
    assert f.source_tools == []
    assert f.evidence_refs == []
    assert f.first_seen is not None
    assert f.last_seen is not None


def test_finding_to_dict():
    f = Finding(
        finding_id="f1", title="SSL Expired", severity="high",
        confidence=0.85, asset_id="example.com",
        source_tools=["nuclei", "whatweb"],
        evidence_refs=["ev1", "ev2"],
    )
    d = f.to_dict()
    assert d["id"] == "f1"
    assert d["title"] == "SSL Expired"
    assert d["severity"] == "high"
    assert d["confidence"] == 0.85
    assert d["asset_id"] == "example.com"
    assert d["source_tools"] == ["nuclei", "whatweb"]
    assert d["evidence_refs"] == ["ev1", "ev2"]
    assert d["validation_status"] == "observed"


# ── Correlation: grouping ────────────────────────────────────────────

def test_correlate_groups_by_asset_and_title(correlator):
    observations = [
        {"title": "SSL Expired", "asset_id": "example.com", "tool": "nuclei"},
        {"title": "SSL Expired", "asset_id": "example.com", "tool": "whatweb"},
        {"title": "Open SSH", "asset_id": "127.0.0.1", "tool": "nmap"},
        {"title": "SSL Expired", "asset_id": "other.com", "tool": "nuclei"},
    ]
    findings = correlator.correlate(observations)
    # 3 groups: example.com|SSL Expired, 127.0.0.1|Open SSH, other.com|SSL Expired
    assert len(findings) == 3


def test_correlate_empty_list(correlator):
    findings = correlator.correlate([])
    assert findings == []


# ── Correlation: merging ─────────────────────────────────────────────

def test_merge_aggregates_source_tools(correlator):
    observations = [
        {"title": "XSS", "asset_id": "app.com", "tool": "nuclei"},
        {"title": "XSS", "asset_id": "app.com", "tool": "whatweb"},
        {"title": "XSS", "asset_id": "app.com", "tool": "nmap"},
    ]
    findings = correlator.correlate(observations)
    assert len(findings) == 1
    f = findings[0]
    assert set(f.source_tools) == {"nuclei", "whatweb", "nmap"}


def test_merge_aggregates_evidence_refs(correlator):
    observations = [
        {"title": "SQLi", "asset_id": "app.com", "tool": "sqlmap",
         "evidence_ref": "ev1"},
        {"title": "SQLi", "asset_id": "app.com", "tool": "sqlmap",
         "evidence_ref": "ev2"},
    ]
    findings = correlator.correlate(observations)
    assert len(findings) == 1
    assert set(findings[0].evidence_refs) == {"ev1", "ev2"}


def test_confidence_increases_with_corroboration(correlator):
    # Single source: base 0.5
    findings = correlator.correlate([{"title": "T", "asset_id": "a", "tool": "nmap"}])
    assert findings[0].confidence == 0.5

    # Two sources: 0.5 + 0.1 = 0.6
    findings = correlator.correlate([
        {"title": "T", "asset_id": "a", "tool": "nmap"},
        {"title": "T", "asset_id": "a", "tool": "nuclei"},
    ])
    assert findings[0].confidence == 0.6

    # Five sources: 0.5 + 0.4 = 0.9
    findings = correlator.correlate([
        {"title": "T", "asset_id": "a", "tool": f"tool_{i}"} for i in range(5)
    ])
    assert findings[0].confidence == 0.9


def test_confidence_capped_at_0_99(correlator):
    # Many sources should cap at 0.99
    findings = correlator.correlate([
        {"title": "T", "asset_id": "a", "tool": f"tool_{i}"} for i in range(20)
    ])
    assert findings[0].confidence <= 0.99


def test_confidence_respects_explicit_higher_value(correlator):
    findings = correlator.correlate([
        {"title": "T", "asset_id": "a", "tool": "nmap", "confidence": 0.95},
        {"title": "T", "asset_id": "a", "tool": "nuclei", "confidence": 0.6},
    ])
    assert findings[0].confidence == 0.95


def test_validation_status_defaults_to_observed(correlator):
    findings = correlator.correlate([{"title": "T", "asset_id": "a", "tool": "nmap"}])
    assert findings[0].validation_status == "observed"


# ── Correlation metadata ─────────────────────────────────────────────

def test_correlation_metadata(correlator):
    observations = [
        {"title": "T1", "asset_id": "a", "tool": "nmap"},
        {"title": "T1", "asset_id": "a", "tool": "nuclei"},
        {"title": "T2", "asset_id": "a", "tool": "nmap"},
    ]
    correlator.correlate(observations)
    meta = correlator.get_correlation_metadata()
    assert meta["total_observations"] == 3
    assert meta["total_groups"] == 2
    assert meta["merged_findings"] == 2


# ── Sorting ──────────────────────────────────────────────────────────

def test_findings_sorted_by_severity_then_confidence(correlator):
    observations = [
        {"title": "Low", "asset_id": "a", "tool": "t", "severity": "low"},
        {"title": "Critical", "asset_id": "a", "tool": "t", "severity": "critical"},
        {"title": "High", "asset_id": "a", "tool": "t", "severity": "high"},
    ]
    findings = correlator.correlate(observations)
    assert findings[0].severity == "critical"
    assert findings[1].severity == "high"
    assert findings[2].severity == "low"
