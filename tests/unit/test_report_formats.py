"""Unit tests for the multi-format report generation (report_generate).

Seeds the vault's ``assessments`` category and verifies each output format
(json, markdown, html, sarif, pdf placeholder, csv, stix) produced by
ReportGenerateTool.
"""

from __future__ import annotations

import json
import uuid

import pytest

from kmcp.tools.agent_interface import ReportGenerateTool
from kmcp.utils.vault import vault_write

FINDINGS = [
    {
        "id": "fnd_report_001",
        "title": "Exposed admin panel",
        "severity": "critical",
        "confidence": 0.9,
        "validation_status": "validated",
        "asset_id": "app.example.test",
        "source_tools": ["nuclei", "httpx"],
        "evidence_refs": ["ev_1"],
        "description": "Admin panel reachable without authentication",
    },
    {
        "id": "fnd_report_002",
        "title": "TLS certificate approaching expiry",
        "severity": "medium",
        "confidence": 0.8,
        "validation_status": "observed",
        "asset_id": "app.example.test",
        "source_tools": ["whatweb"],
        "evidence_refs": ["ev_2"],
        "description": "Certificate expires within 14 days",
    },
]

SUMMARY = {
    "assets_discovered": 3,
    "services_discovered": 5,
    "findings": {"critical": 1, "high": 0, "medium": 1, "low": 0},
}


@pytest.fixture()
def assessment_id() -> str:
    aid = f"assessment_{uuid.uuid4().hex[:10]}"
    vault_write(
        "assessments",
        aid,
        {
            "assessment_id": aid,
            "findings": FINDINGS,
            "summary": SUMMARY,
            "target": "report.test",
            "next_actions": ["Run web_assessment for full coverage"],
            "assets": [{"asset_id": "app.example.test", "type": "webapp"}],
        },
    )
    return aid


@pytest.fixture()
def tool() -> ReportGenerateTool:
    return ReportGenerateTool()


def _body(result: dict) -> str:
    body = result.get("stdout")
    if body:
        return body
    body = result.get("execution_result", {}).get("stdout")
    if body:
        return body
    text = (result.get("content") or [{}])[0].get("text", "")
    if text:
        try:
            parsed = json.loads(text)
            if parsed.get("stdout"):
                return parsed["stdout"]
            return text
        except ValueError:
            return text
    assert False, f"no stdout in response: {list(result)[:6]}"


@pytest.mark.asyncio
async def test_json_format(assessment_id, tool):
    res = await tool.safe_execute({"assessment_id": assessment_id, "format": "json"})
    body = _body(res)
    report = json.loads(body)
    assert report["assessment_id"] == assessment_id
    assert report["format"] == "json"
    assert len(report["findings"]) == 2


@pytest.mark.asyncio
async def test_remediation_present_in_json(assessment_id, tool):
    # Seed one finding carrying a remediation field.
    aid = f"assessment_{uuid.uuid4().hex[:10]}"
    vault_write(
        "assessments",
        aid,
        {
            "assessment_id": aid,
            "findings": [
                {
                    "id": "fnd_rem_001",
                    "title": "Open SSH port",
                    "severity": "high",
                    "confidence": 0.9,
                    "validation_status": "observed",
                    "asset_id": "host.example.test",
                    "source_tools": ["nmap"],
                    "evidence_refs": [],
                    "remediation": "Restrict access with a firewall; close unnecessary ports.",
                }
            ],
            "summary": {
                "assets_discovered": 1,
                "services_discovered": 1,
                "findings": {"critical": 0, "high": 1, "medium": 0, "low": 0},
            },
            "target": "host.example.test",
            "next_actions": [],
            "assets": [],
        },
    )
    res = await tool.safe_execute({"assessment_id": aid, "format": "json"})
    report = json.loads(_body(res))
    finding = report["findings"][0]
    assert finding.get("remediation"), "expected remediation guidance in JSON report"


@pytest.mark.asyncio
async def test_remediation_present_in_markdown(assessment_id, tool):
    aid = f"assessment_{uuid.uuid4().hex[:10]}"
    vault_write(
        "assessments",
        aid,
        {
            "assessment_id": aid,
            "findings": [
                {
                    "id": "fnd_rem_002",
                    "title": "Exposed admin endpoint",
                    "severity": "critical",
                    "confidence": 0.8,
                    "validation_status": "observed",
                    "asset_id": "app.example.test",
                    "source_tools": ["katana"],
                    "evidence_refs": [],
                    "remediation": "Apply authentication to exposed endpoints.",
                }
            ],
            "summary": {
                "assets_discovered": 1,
                "services_discovered": 1,
                "findings": {"critical": 1, "high": 0, "medium": 0, "low": 0},
            },
            "target": "app.example.test",
            "next_actions": [],
            "assets": [],
        },
    )
    res = await tool.safe_execute({"assessment_id": aid, "format": "markdown"})
    body = _body(res)
    assert "Apply authentication to exposed endpoints." in body


@pytest.mark.asyncio
async def test_markdown_format(assessment_id, tool):
    res = await tool.safe_execute({"assessment_id": assessment_id, "format": "markdown"})
    body = _body(res)
    assert "# " in body or body.lstrip().startswith("#")
    assert "fnd_report_001" in body
    assert assessment_id in body


@pytest.mark.asyncio
async def test_html_format(assessment_id, tool):
    res = await tool.safe_execute({"assessment_id": assessment_id, "format": "html"})
    body = _body(res)
    assert "<html" in body.lower()
    assert "fnd_report_001" in body


@pytest.mark.asyncio
async def test_sarif_format(assessment_id, tool):
    res = await tool.safe_execute({"assessment_id": assessment_id, "format": "sarif"})
    sarif = json.loads(_body(res))
    assert sarif["version"] == "2.1.0" or sarif.get("version")
    assert "runs" in sarif
    results = sarif["runs"][0]["results"]
    assert len(results) == 2
    assert results[0]["level"] in {"error", "note", "warning"}


@pytest.mark.asyncio
async def test_pdf_placeholder_document(assessment_id, tool):
    res = await tool.safe_execute({"assessment_id": assessment_id, "format": "pdf"})
    body = _body(res)
    assert "KALI-MCP ASSESSMENT REPORT" in body
    assert "fnd_report_002" in body


@pytest.mark.asyncio
async def test_csv_format(assessment_id, tool):
    res = await tool.safe_execute({"assessment_id": assessment_id, "format": "csv"})
    body = _body(res)
    import csv
    import io

    rows = list(csv.reader(io.StringIO(body)))
    header, data = rows[0], [r for r in rows[1:] if r]
    assert len(data) == 2
    assert "finding_id" in header or "id" in header


@pytest.mark.asyncio
async def test_stix_format(assessment_id, tool):
    res = await tool.safe_execute({"assessment_id": assessment_id, "format": "stix"})
    stix = json.loads(_body(res))
    assert stix["type"] == "bundle"
    assert stix["spec_version"] == "2.1"
    assert stix["assessment_id"] == assessment_id

    types = [o["type"] for o in stix["objects"]]
    assert "identity" in types and "report" in types and "indicator" in types
    indicators = [o for o in stix["objects"] if o["type"] == "indicator"]
    assert len(indicators) == 2
    report_obj = next(o for o in stix["objects"] if o["type"] == "report")
    assert len(report_obj["object_refs"]) == 2


@pytest.mark.asyncio
async def test_invalid_format_rejected(assessment_id, tool):
    with pytest.raises(ValueError):
        tool.validate({"assessment_id": assessment_id, "format": "xml"})


@pytest.mark.asyncio
async def test_missing_assessment_returns_error(tool):
    res = await tool.safe_execute(
        {"assessment_id": "assessment_does_not_exist_at_all", "format": "json"}
    )
    body = _body(res)
    assert "not found" in body.lower() or "error" in body.lower()
