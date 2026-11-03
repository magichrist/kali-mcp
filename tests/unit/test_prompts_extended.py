"""Unit tests for prompts.py (prompt factory functions + registration)."""

from __future__ import annotations

from unittest.mock import MagicMock

from kali_mcp.prompts import (
    _ad,
    _osint,
    _quick_scan,
    _recon,
    _report,
    _webapp,
    register_prompts,
)


class TestPromptFactories:
    def test_recon_standard(self) -> None:
        msgs = _recon("example.com")
        assert len(msgs) == 2
        assert "example.com" in msgs[0]["content"]["text"]
        assert "Phase 1" in msgs[1]["content"]["text"]

    def test_recon_deep(self) -> None:
        msgs = _recon("example.com", depth="deep", scope="internal only")
        text = msgs[1]["content"]["text"]
        assert "subdomains" in text
        assert "internal only" in msgs[0]["content"]["text"]

    def test_webapp(self) -> None:
        msgs = _webapp("http://target", auth="yes")
        assert "http://target" in msgs[0]["content"]["text"]
        assert "webapp_crawl" in msgs[1]["content"]["text"]

    def test_ad(self) -> None:
        msgs = _ad("corp.example.com", credentials="admin:pass")
        assert "corp.example.com" in msgs[0]["content"]["text"]
        assert "Kerberoasting" in msgs[1]["content"]["text"]

    def test_osint(self) -> None:
        msgs = _osint("subject", sources="breach")
        assert "subject" in msgs[0]["content"]["text"]
        assert "breach" in msgs[1]["content"]["text"]

    def test_quick_scan(self) -> None:
        msgs = _quick_scan("10.0.0.1", ports="22,80", profile="fast")
        assert "10.0.0.1" in msgs[0]["content"]["text"]
        assert "nmap_scan" in msgs[1]["content"]["text"]

    def test_report(self) -> None:
        msgs = _report("eng-1", "finding: x")
        assert "eng-1" in msgs[0]["content"]["text"]
        assert "Executive summary" in msgs[1]["content"]["text"]


class TestRegisterPrompts:
    def test_register_prompts_registers_six(self) -> None:
        fake_mcp = MagicMock()
        register_prompts(fake_mcp)
        # @mcp.prompt decorator is called 6 times → 6 registrations
        assert fake_mcp.prompt.call_count == 6
        registered_names = [call.kwargs.get("name") for call in fake_mcp.prompt.call_args_list]
        expected = {
            "recon_workflow",
            "webapp_assessment",
            "ad_assessment",
            "osint_harvest",
            "quick_scan",
            "report_template",
        }
        assert set(registered_names) == expected
