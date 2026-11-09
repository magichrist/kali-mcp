"""Extended unit tests for the Kali MCP CLI (kali_mcp/cli.py).

Covers cmd_start, cmd_monitor, cmd_purge scopes/confirm behavior,
build_parser edge cases, and main() default/unknown-command handling.
"""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kali_mcp.cli import build_parser, cmd_monitor, cmd_purge, cmd_start, main


class TestParserExtended:
    def test_start_defaults_host_and_port_none(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["start"])
        assert args.command == "start"
        assert args.host is None
        assert args.port is None

    def test_start_alias_s_resolves_to_start_func(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["s"])
        assert args.command == "s"
        assert args.func is cmd_start

    def test_monitor_alias_m_resolves_to_monitor_func(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["m"])
        assert args.command == "m"
        assert args.func is cmd_monitor

    def test_purge_accepts_all_valid_scopes(self) -> None:
        parser = build_parser()
        for scope in ("db", "vault", "all"):
            args = parser.parse_args(["purge", scope])
            assert args.scope == scope
            assert args.confirm is False

    def test_purge_confirm_flag_long_and_short(self) -> None:
        parser = build_parser()
        assert parser.parse_args(["purge", "db", "--confirm"]).confirm is True
        assert parser.parse_args(["purge", "db", "-y"]).confirm is True

    def test_purge_invalid_scope_rejected(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["purge", "everything"])


class TestCmdStart:
    def test_cmd_start_sets_env_from_args_and_calls_server_main(self) -> None:
        with (
            patch("kali_mcp.cli._load_env"),
            patch("kali_mcp.server.main") as mock_server_main,
            patch.dict(os.environ, {}, clear=True),
        ):
            args = SimpleNamespace(host="127.0.0.1", port="9999")
            assert cmd_start(args) == 0
            mock_server_main.assert_called_once()
            assert os.environ["MCP_HOST"] == "127.0.0.1"
            assert os.environ["MCP_PORT"] == "9999"

    def test_cmd_start_keeps_existing_env_when_args_none(self) -> None:
        with (
            patch("kali_mcp.cli._load_env"),
            patch("kali_mcp.server.main") as mock_server_main,
            patch.dict(os.environ, {"MCP_HOST": "env-host", "MCP_PORT": "env-port"}, clear=True),
        ):
            args = SimpleNamespace(host=None, port=None)
            assert cmd_start(args) == 0
            mock_server_main.assert_called_once()
            assert os.environ["MCP_HOST"] == "env-host"
            assert os.environ["MCP_PORT"] == "env-port"


class TestCmdMonitor:
    def test_cmd_monitor_passes_url_to_monitor_main(self) -> None:
        with (
            patch("kali_mcp.cli._load_env"),
            patch("kali_mcp.monitor.tui.main") as mock_monitor_main,
            patch.dict(os.environ, {}, clear=True),
        ):
            args = SimpleNamespace(url="http://127.0.0.1:9000")
            assert cmd_monitor(args) == 0
            mock_monitor_main.assert_called_once_with("http://127.0.0.1:9000", None)

    def test_cmd_monitor_defaults_url_when_none(self) -> None:
        with (
            patch("kali_mcp.cli._load_env"),
            patch("kali_mcp.monitor.tui.main") as mock_monitor_main,
            patch.dict(os.environ, {}, clear=True),
        ):
            args = SimpleNamespace(url=None)
            cmd_monitor(args)
            mock_monitor_main.assert_called_once_with("http://127.0.0.1:8399", None)


class TestCmdPurgeExtended:
    def _make_args(self, scope="all", confirm=True) -> SimpleNamespace:
        return SimpleNamespace(scope=scope, confirm=confirm)

    def test_invalid_scope_returns_one(self) -> None:
        import kali_mcp.cli as cli_mod

        orig_root = cli_mod.REPO_ROOT
        cli_mod.REPO_ROOT = Path("/tmp/nonexistent_kmcp")
        try:
            args = self._make_args(scope="bogus", confirm=True)
            assert cmd_purge(args) == 1
        finally:
            cli_mod.REPO_ROOT = orig_root

    def test_purge_db_scope_removes_only_db_files(self, tmp_path) -> None:
        import kali_mcp.cli as cli_mod

        db_file = tmp_path / "data" / "kali-mcp.sqlite"
        db_file.parent.mkdir(parents=True)
        db_file.write_text("fake-db")
        vault_dir = tmp_path / "artifacts" / "vault"
        vault_dir.mkdir(parents=True)
        (vault_dir / "index.json").write_text("{}")

        orig_root = cli_mod.REPO_ROOT
        cli_mod.REPO_ROOT = tmp_path
        try:
            args = self._make_args(scope="db", confirm=True)
            assert cmd_purge(args) == 0
            assert not db_file.exists()
            assert vault_dir.exists()  # vault untouched
        finally:
            cli_mod.REPO_ROOT = orig_root

    def test_purge_vault_scope_removes_only_vault(self, tmp_path) -> None:
        import kali_mcp.cli as cli_mod

        db_file = tmp_path / "data" / "kali-mcp.sqlite"
        db_file.parent.mkdir(parents=True)
        db_file.write_text("fake-db")
        vault_dir = tmp_path / "artifacts" / "vault"
        vault_dir.mkdir(parents=True)
        (vault_dir / "index.json").write_text("{}")

        orig_root = cli_mod.REPO_ROOT
        cli_mod.REPO_ROOT = tmp_path
        try:
            args = self._make_args(scope="vault", confirm=True)
            assert cmd_purge(args) == 0
            assert db_file.exists()  # db untouched
            assert not vault_dir.exists()
        finally:
            cli_mod.REPO_ROOT = orig_root

    def test_purge_all_scope_removes_both(self, tmp_path) -> None:
        import kali_mcp.cli as cli_mod

        db_file = tmp_path / "data" / "kali-mcp.sqlite"
        db_file.parent.mkdir(parents=True)
        db_file.write_text("fake-db")
        vault_dir = tmp_path / "artifacts" / "vault"
        vault_dir.mkdir(parents=True)
        (vault_dir / "index.json").write_text("{}")

        orig_root = cli_mod.REPO_ROOT
        cli_mod.REPO_ROOT = tmp_path
        try:
            args = self._make_args(scope="all", confirm=True)
            assert cmd_purge(args) == 0
            assert not db_file.exists()
            assert not vault_dir.exists()
        finally:
            cli_mod.REPO_ROOT = orig_root

    def test_purge_aborts_without_confirm(self) -> None:
        import kali_mcp.cli as cli_mod

        orig_root = cli_mod.REPO_ROOT
        cli_mod.REPO_ROOT = Path("/tmp/nonexistent_kmcp2")
        try:
            args = self._make_args(scope="all", confirm=False)
            with patch("kali_mcp.cli._confirm", return_value=False):
                assert cmd_purge(args) == 1
        finally:
            cli_mod.REPO_ROOT = orig_root


class TestMainExtended:
    def test_main_no_arguments_prints_help(self) -> None:
        """Running ``kmcp`` with no command prints help instead of starting the server."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main([]) == 0
        output = buf.getvalue()
        assert "usage:" in output
        assert "playbook" in output
        assert "tool" in output
        assert "execution" in output

    def test_main_explicit_start(self) -> None:
        with patch("kali_mcp.cli.cmd_start", return_value=0) as mock_start:
            assert main(["start"]) == 0
            mock_start.assert_called_once()

    def test_main_unknown_command_exits(self) -> None:
        with pytest.raises(SystemExit):
            main(["not-a-real-command"])
