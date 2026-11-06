"""Unit tests for the `kmcp studio` / frontend browser commands."""

from __future__ import annotations

from types import SimpleNamespace

from kali_mcp.cli import build_parser, cmd_studio, main


def _args(**overrides) -> SimpleNamespace:
    defaults = {"url": None, "host": None, "port": None, "no_browser": True}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestParser:
    def test_studio_registers_with_alias(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["studio"])
        assert args.func is cmd_studio

    def test_studio_shorthand_st(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["st"])
        assert args.func is cmd_studio

    def test_studio_no_browser_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["studio", "--no-browser"])
        assert args.no_browser is True

class TestStudioPortSelection:
    def test_explicit_url_wins_over_port_flag(self, monkeypatch) -> None:
        monkeypatch.setenv("MCP_PORT", "8399")
        monkeypatch.delenv("STUDIO_PORT", raising=False)

        reached = {}
        monkeypatch.setattr(
            "kali_mcp.cli._server_reachable",
            lambda url, timeout=1.5: reached.setdefault(url, True) or True,
        )
        monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)

        assert cmd_studio(_args(url="http://localhost:7777", port="9999")) == 0
        assert "http://localhost:7777/studio" in reached

    def test_no_browser_on_existing_server_no_child(self, monkeypatch) -> None:
        monkeypatch.setenv("MCP_PORT", "8399")
        monkeypatch.delenv("STUDIO_PORT", raising=False)
        monkeypatch.setattr("kali_mcp.cli._server_reachable", lambda url, timeout=1.5: True)
        monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)

        assert cmd_studio(_args()) == 0

    def test_studio_port_env_selects_browser_url(self, monkeypatch) -> None:
        """With STUDIO_PORT set, the browser URL targets the dedicated port."""
        monkeypatch.setenv("MCP_PORT", "8399")
        monkeypatch.setenv("STUDIO_PORT", "8340")

        reached = {}

        def fake_reachable(url, timeout=1.5):
            reached[url] = True
            return True

        monkeypatch.setattr("kali_mcp.cli._server_reachable", fake_reachable)
        monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)

        assert cmd_studio(_args()) == 0
        assert any(":8340/studio" in u for u in reached)

    def test_mcp_port_fallback_when_no_studio_port(self, monkeypatch) -> None:
        monkeypatch.delenv("STUDIO_PORT", raising=False)
        monkeypatch.setenv("MCP_PORT", "9001")

        reached = {}
        monkeypatch.setattr(
            "kali_mcp.cli._server_reachable",
            lambda url, timeout=1.5: reached.setdefault(url, True) or True,
        )
        monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)

        assert cmd_studio(_args()) == 0
        assert any(":9001/studio" in u for u in reached)


class TestWildcardHostResolution:
    def test_wildcard_bind_resolves_to_lan_ip(self, monkeypatch) -> None:
        """MCP_HOST=0.0.0.0 → browser URL uses the machine's LAN IP."""
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.delenv("STUDIO_PORT", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.setenv("KALI_MCP_INSECURE", "1")  # silence protection note
        monkeypatch.setattr("kali_mcp.cli._primary_lan_ip", lambda: "192.168.2.4")

        reached = {}
        monkeypatch.setattr(
            "kali_mcp.cli._server_reachable",
            lambda url, timeout=1.5: reached.setdefault(url, True) or True,
        )
        monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)

        assert cmd_studio(_args()) == 0
        assert "http://192.168.2.4:8399/studio" in reached

    def test_primary_lan_ip_returned_is_used_in_url(self, monkeypatch) -> None:
        from kali_mcp.cli import _browser_url_for_host

        monkeypatch.setattr("kali_mcp.cli._primary_lan_ip", lambda: "192.168.2.4")
        url = _browser_url_for_host("0.0.0.0", 8399)
        assert url == "http://192.168.2.4:8399/studio"

    def test_wildcard_bind_falls_back_to_localhost_offline(self, monkeypatch) -> None:
        from kali_mcp.cli import _browser_url_for_host

        monkeypatch.setattr("kali_mcp.cli._primary_lan_ip", lambda: "")
        assert _browser_url_for_host("0.0.0.0", 8399) == "http://127.0.0.1:8399/studio"
        assert _browser_url_for_host("::", 8399) == "http://127.0.0.1:8399/studio"

    def test_explicit_host_is_never_remapped(self, monkeypatch) -> None:
        from kali_mcp.cli import _browser_url_for_host

        monkeypatch.setattr(
            "kali_mcp.cli._primary_lan_ip",
            lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
        )
        assert _browser_url_for_host("127.0.0.1", 8399) == "http://127.0.0.1:8399/studio"
        assert _browser_url_for_host("192.168.2.9", 8399) == "http://192.168.2.9:8399/studio"
        assert _browser_url_for_host("staging.internal", 8399) == "http://staging.internal:8399/studio"

    def test_port_env_still_applies_with_wildcard(self, monkeypatch) -> None:
        from kali_mcp.cli import _browser_url_for_host

        monkeypatch.setattr("kali_mcp.cli._primary_lan_ip", lambda: "10.0.0.7")
        assert _browser_url_for_host("0.0.0.0", 8340) == "http://10.0.0.7:8340/studio"


class TestMainBehaviour:
    def test_duplicate_frontend_commands_removed(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                main(["--help"])
            except SystemExit:
                pass
        help_text = buf.getvalue()
        assert "studio" in help_text
        for gone in ("frontend", "webui", "dashboard", "gui", "open-frontend"):
            assert gone not in help_text