"""Unit tests for the `kmcp studio` / frontend browser commands."""

from __future__ import annotations

from types import SimpleNamespace

from kali_mcp.cli import build_parser, cmd_studio, main


def _args(**overrides) -> SimpleNamespace:
    defaults = {"url": None, "host": None, "port": None, "no_browser": True}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _stub_browser(monkeypatch) -> None:
    """Patch browser opening so tests never spawn a real browser."""
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: True)


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
        _stub_browser(monkeypatch)

        assert cmd_studio(_args(url="http://localhost:7777", port="9999")) == 0
        # The loopback probe uses the URL's port (7777), proving the explicit
        # URL won over the `port` flag (9999).
        assert any(":7777/studio" in u for u in reached)
        assert not any(":9999" in u for u in reached)

    def test_no_browser_on_existing_server_no_child(self, monkeypatch) -> None:
        monkeypatch.setenv("MCP_PORT", "8399")
        monkeypatch.delenv("STUDIO_PORT", raising=False)
        monkeypatch.setattr("kali_mcp.cli._server_reachable", lambda url, timeout=1.5: True)
        _stub_browser(monkeypatch)

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
        _stub_browser(monkeypatch)

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
        _stub_browser(monkeypatch)

        assert cmd_studio(_args()) == 0
        assert any(":9001/studio" in u for u in reached)


class TestWildcardHostResolution:
    def test_wildcard_bind_resolves_to_lan_ip(self, monkeypatch) -> None:
        """MCP_HOST=0.0.0.0 → browser URL uses the machine's LAN IP."""
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.delenv("STUDIO_PORT", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.setenv("KALI_MCP_INSECURE", "1")  # silence protection note
        monkeypatch.setattr("kali_mcp.cli._primary_lan_ip", lambda: "127.0.0.1")

        reached = {}
        monkeypatch.setattr(
            "kali_mcp.cli._server_reachable",
            lambda url, timeout=1.5: reached.setdefault(url, True) or True,
        )
        _stub_browser(monkeypatch)

        assert cmd_studio(_args()) == 0
        assert "http://127.0.0.1:8399/studio" in reached

    def test_primary_lan_ip_returned_is_used_in_url(self, monkeypatch) -> None:
        from kali_mcp.cli import _browser_url_for_host

        monkeypatch.setattr("kali_mcp.cli._primary_lan_ip", lambda: "127.0.0.1")
        url = _browser_url_for_host("0.0.0.0", 8399)
        assert url == "http://127.0.0.1:8399/studio"

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
        assert (
            _browser_url_for_host("staging.internal", 8399) == "http://staging.internal:8399/studio"
        )

    def test_port_env_still_applies_with_wildcard(self, monkeypatch) -> None:
        from kali_mcp.cli import _browser_url_for_host

        monkeypatch.setattr("kali_mcp.cli._primary_lan_ip", lambda: "127.0.0.1")
        assert _browser_url_for_host("0.0.0.0", 8340) == "http://127.0.0.1:8340/studio"


class TestIsLanIp:
    def test_accepts_private_lan_addresses(self) -> None:
        from kali_mcp.cli import _is_lan_ip

        assert _is_lan_ip("192.168.2.4")
        assert _is_lan_ip("10.0.0.8")
        assert _is_lan_ip("172.16.5.9")

    def test_rejects_ghost_and_special_addresses(self) -> None:
        from kali_mcp.cli import _is_lan_ip

        # Reserved 240.0.0.0/4 — reported by UDP-route detection on machines
        # with virtual/VPN tunnel interfaces; unroutable locally.
        assert not _is_lan_ip("240.0.0.2")
        assert not _is_lan_ip("127.0.0.1")       # loopback
        assert not _is_lan_ip("169.254.3.2")     # link-local
        assert not _is_lan_ip("224.0.0.5")       # multicast
        assert not _is_lan_ip("8.8.8.8")         # public
        assert not _is_lan_ip("not-an-ip")


class TestBrowserOpenBehaviour:
    def test_cmd_studio_prints_manual_hint_when_browser_raises(
        self, monkeypatch, capsys
    ) -> None:
        monkeypatch.setenv("MCP_PORT", "8399")
        monkeypatch.delenv("STUDIO_PORT", raising=False)
        monkeypatch.setenv("KALI_MCP_INSECURE", "1")
        monkeypatch.setattr("kali_mcp.cli._server_reachable", lambda url, timeout=1.5: True)

        def boom(url, *a, **k):
            raise RuntimeError("no browser on this host")

        monkeypatch.setattr("webbrowser.open", boom)
        assert cmd_studio(_args(no_browser=False)) == 0
        err = capsys.readouterr().err
        assert "open the URL manually" in err

    def test_cmd_studio_opens_url_via_webbrowser(self, monkeypatch) -> None:
        monkeypatch.setenv("MCP_PORT", "8399")
        monkeypatch.delenv("STUDIO_PORT", raising=False)
        monkeypatch.setenv("KALI_MCP_INSECURE", "1")
        monkeypatch.setattr("kali_mcp.cli._server_reachable", lambda url, timeout=1.5: True)

        opened: list[str] = []
        monkeypatch.setattr("webbrowser.open", lambda url, *a, **k: opened.append(url) or True)

        assert cmd_studio(_args(no_browser=False)) == 0
        assert any(u.endswith(":8399/studio") for u in opened)


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
