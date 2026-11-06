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