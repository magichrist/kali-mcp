"""Tests for the built-in internal modules (Playbook Studio Phase 1, Lane D)."""

from __future__ import annotations

import pytest

from kmcp.workflow import modules_runtime as mr
from kmcp.workflow.modules_runtime import ModuleContext

CTX = ModuleContext(assessment_id="assess_1", job_id="job_1", playbook_name="pb_test")


@pytest.fixture(autouse=True)
def _clean_and_load():
    """Clean registry, load builtin modules, clean again after each test."""
    mr.clear()
    loaded = mr.load_builtin_modules(reload=True)
    assert isinstance(loaded, list)
    yield
    mr.clear()


class TestTargetModules:
    def test_target_registered(self):
        assert mr.has("target.validate")
        assert mr.has("target.scope_check")

    def test_target_validate_valid_ip(self):
        res = mr.execute("target.validate", CTX, {"target": "127.0.0.1"})
        assert res["valid"] is True
        assert res["kind"] == "ip"
        assert res["target"] == "127.0.0.1"

    def test_target_validate_valid_domain(self):
        res = mr.execute("target.validate", CTX, {"target": "example.com"})
        assert res["valid"] is True
        assert res["kind"] == "domain"

    def test_target_validate_invalid_chars(self):
        res = mr.execute("target.validate", CTX, {"target": "not a target!!"})
        assert res["valid"] is False
        assert "error" in res

    def test_target_validate_empty(self):
        # Empty string is rejected by the input schema (required field) —
        # that's expected behavior, tested via the schema layer.
        with pytest.raises(mr.ModuleError, match="missing required input"):
            mr.execute("target.validate", CTX, {"target": ""})

    def test_target_scope_check_permissive(self):
        # No scope env vars → permissive → allowed
        res = mr.execute("target.scope_check", CTX, {"target": "127.0.0.1"})
        assert res["allowed"] is True


class TestDnsModules:
    def test_dns_registered(self):
        assert mr.has("dns.resolve")

    def test_dns_resolve_missing_target(self):
        # Missing target key is rejected by the input schema
        with pytest.raises(mr.ModuleError, match="missing required input"):
            mr.execute("dns.resolve", CTX, {})

    def test_dns_resolve_unregistered_tool(self):
        # Use a tool name that is definitely not registered
        res = mr.execute(
            "dns.resolve", CTX, {"target": "example.com", "tool": "nonexistent_dns_tool_xyz"}
        )
        assert "not registered" in res.get("error", "")
        assert res["target"] == "example.com"


class TestTlsModules:
    def test_tls_registered(self):
        assert mr.has("tls.certificate")

    def test_tls_certificate_unregistered_tool(self):
        res = mr.execute(
            "tls.certificate", CTX, {"target": "example.com", "tool": "nonexistent_tls_tool_xyz"}
        )
        assert "not registered" in res.get("error", "")


class TestNetworkModules:
    def test_network_registered(self):
        assert mr.has("network.port_discovery")

    def test_network_port_discovery_unregistered_tool(self):
        res = mr.execute(
            "network.port_discovery",
            CTX,
            {"target": "127.0.0.1", "tool": "nonexistent_network_tool_xyz"},
        )
        assert "not registered" in res.get("error", "")


class TestWebModules:
    def test_web_registered(self):
        assert mr.has("web.http_probe")

    def test_web_http_probe_unregistered_tool(self):
        res = mr.execute(
            "web.http_probe",
            CTX,
            {"url": "https://example.com", "tool": "nonexistent_web_tool_xyz"},
        )
        assert "not registered" in res.get("error", "")


class TestIntelligenceModules:
    def test_intelligence_registered(self):
        assert mr.has("intelligence.correlate")

    def test_intelligence_correlate_dedupes(self):
        findings = [
            {"id": "f1", "target": "127.0.0.1", "type": "xss", "name": "XSS", "severity": "high"},
            {
                "id": "f2",
                "target": "example.org",
                "type": "sqli",
                "name": "SQLi",
                "severity": "critical",
            },
            {
                "id": "f1",
                "target": "127.0.0.1",
                "type": "xss",
                "name": "XSS",
                "severity": "high",
            },  # dup
        ]
        res = mr.execute("intelligence.correlate", CTX, {"findings": findings})
        assert res["count"] == 2
        assert res["unique_targets"] == 2
        assert res["correlated"][0]["severity"] == "critical"
        assert res["correlated"][0]["severity_rank"] == 0

    def test_intelligence_correlate_invalid_input(self):
        res = mr.execute("intelligence.correlate", CTX, {"findings": "not a list"})
        assert "error" in res


class TestModuleContext:
    def test_module_context_fields(self):
        ctx = ModuleContext(assessment_id="a", job_id="j", playbook_name="p")
        assert ctx.assessment_id == "a"
        assert ctx.job_id == "j"
        assert ctx.playbook_name == "p"

    def test_module_context_defaults(self):
        ctx = ModuleContext()
        assert ctx.assessment_id is None
        assert ctx.job_id is None
        assert ctx.playbook_name is None


class TestListModules:
    def test_list_modules_includes_builtins(self):
        names = {m["name"] for m in mr.list_modules()}
        expected = {
            "target.validate",
            "target.scope_check",
            "dns.resolve",
            "tls.certificate",
            "network.port_discovery",
            "web.http_probe",
            "intelligence.correlate",
        }
        assert expected <= names, f"missing: {expected - names}"

    def test_list_modules_reports_schemas(self):
        by_name = {m["name"]: m for m in mr.list_modules()}
        assert by_name["target.validate"]["has_input_schema"] is True
        assert by_name["target.validate"]["has_output_schema"] is True
