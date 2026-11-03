"""Unit tests for the Kali MCP CLI (kali_mcp/cli.py)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from kali_mcp.cli import build_parser, cmd_purge, main


class TestParser:
    def test_start_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["start", "--host", "127.0.0.1", "--port", "9999"])
        assert args.command == "start"
        assert args.host == "127.0.0.1"
        assert args.port == "9999"

    def test_start_alias_s(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["s"])
        assert args.command == "s"
        assert args.func is not None

    def test_monitor_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["monitor", "http://example.com:9000"])
        assert args.command == "monitor"
        assert args.url == "http://example.com:9000"

    def test_monitor_alias_m(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["m"])
        assert args.command == "m"
        assert args.func is not None

    def test_monitor_no_url_defaults_none(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["monitor"])
        assert args.command == "monitor"
        assert args.url is None

    def test_purge_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["purge", "db", "--confirm"])
        assert args.command == "purge"
        assert args.scope == "db"
        assert args.confirm is True

    def test_purge_alias_p(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["p", "vault"])
        assert args.command == "p"
        assert args.scope == "vault"
        assert args.confirm is False

    def test_purge_invalid_scope(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["purge", "invalid"])

    def test_no_command(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestMain:
    def test_start_calls_server_main(self) -> None:
        with patch("kali_mcp.cli.cmd_start", return_value=0) as mock_start:
            assert main(["start"]) == 0
            mock_start.assert_called_once()

    def test_monitor_calls_monitor_main(self) -> None:
        with patch("kali_mcp.cli.cmd_monitor", return_value=0) as mock_monitor:
            assert main(["monitor", "http://x:1"]) == 0
            mock_monitor.assert_called_once()


class TestPurge:
    def test_purge_aborts_without_confirm(self) -> None:
        args = SimpleNamespace(scope="db", confirm=False)
        with patch("kali_mcp.cli._confirm", return_value=False):
            assert cmd_purge(args) == 1

    def test_purge_proceeds_with_confirm(self, tmp_path) -> None:
        import kali_mcp.cli as cli_mod

        # Create fake db + vault files under tmp_path
        db_file = tmp_path / "data" / "kali-mcp.sqlite"
        db_file.parent.mkdir(parents=True)
        db_file.write_text("fake")
        vault_dir = tmp_path / "artifacts" / "vault"
        vault_dir.mkdir(parents=True)
        (vault_dir / "index.json").write_text("{}")

        orig_root = cli_mod.REPO_ROOT
        cli_mod.REPO_ROOT = tmp_path
        try:
            args = SimpleNamespace(scope="all", confirm=True)
            assert cmd_purge(args) == 0
            assert not db_file.exists()
            assert not vault_dir.exists()
        finally:
            cli_mod.REPO_ROOT = orig_root

    def test_purge_nothing_to_remove(self) -> None:
        import kali_mcp.cli as cli_mod

        orig_root = cli_mod.REPO_ROOT
        cli_mod.REPO_ROOT = Path("/tmp/nonexistent_kmcp_test")
        try:
            args = SimpleNamespace(scope="db", confirm=True)
            assert cmd_purge(args) == 0
        finally:
            cli_mod.REPO_ROOT = orig_root
