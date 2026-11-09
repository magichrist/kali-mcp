"""Unit tests for `kmcp init` (.env bootstrap)."""

from __future__ import annotations

from pathlib import Path

from kali_mcp.cli import cmd_init, main

EXAMPLE = """\
# Server
MCP_HOST=0.0.0.0
MCP_PORT=8399

# Authentication (set in production)
MCP_API_TOKEN=

# Optional
MCP_RATE_LIMIT=0
"""


def _init(tmp_path: Path, existing_env: str | None = None, force: bool = False):
    """Run cmd_init inside tmp_path."""
    example = tmp_path / ".env.example"
    example.write_text(EXAMPLE)

    env_path = tmp_path / ".env"
    if existing_env is not None:
        env_path.write_text(existing_env)

    import types
    from unittest.mock import patch

    args = types.SimpleNamespace(force=force)
    with patch("kali_mcp.cli.REPO_ROOT", tmp_path):
        rc = cmd_init(args)
    return rc, env_path


class TestInitFresh:
    def test_creates_env_with_token(self, tmp_path) -> None:
        rc, env_path = _init(tmp_path, existing_env=None)
        assert rc == 0
        assert env_path.exists()
        content = env_path.read_text()
        assert "MCP_API_TOKEN=" in content
        token = dict(
            line.split("=", 1)
            for line in content.splitlines()
            if "=" in line and not line.startswith("#")
        )["MCP_API_TOKEN"]
        assert len(token) >= 32

    def test_no_example_fails(self, tmp_path) -> None:
        import types
        from unittest.mock import patch

        args = types.SimpleNamespace(force=False)
        with patch("kali_mcp.cli.REPO_ROOT", tmp_path):
            rc = cmd_init(args)
        assert rc == 1


class TestInitBackfill:
    def test_fills_empty_token_keeps_other_values(self, tmp_path) -> None:
        rc, env_path = _init(
            tmp_path,
            existing_env="MCP_HOST=127.0.0.1\nMCP_API_TOKEN=\n",
        )
        assert rc == 0
        content = env_path.read_text()
        assert "MCP_HOST=127.0.0.1" in content  # untouched
        token = next(l for l in content.splitlines() if l.startswith("MCP_API_TOKEN="))
        assert len(token.split("=", 1)[1]) >= 32

    def test_does_not_touch_a_set_token(self, tmp_path) -> None:
        rc, env_path = _init(tmp_path, existing_env="MCP_API_TOKEN=existing_secret_value\n")
        assert rc == 0
        content = env_path.read_text()
        assert "MCP_API_TOKEN=existing_secret_value" in content

    def test_reports_complete_when_all_set(self, tmp_path) -> None:
        rc, _env_path = _init(tmp_path, existing_env="MCP_API_TOKEN=abc\n")
        assert rc == 0

    def test_idempotent(self, tmp_path) -> None:
        _init(tmp_path, existing_env="MCP_API_TOKEN=s\n")
        _first, env_path = _init(tmp_path, existing_env=None)
        before = env_path.read_text()
        _second, env_path = _init(tmp_path, existing_env=None)
        assert env_path.read_text() == before


class TestParser:
    def test_init_parser(self) -> None:
        parser = main and __import__("kali_mcp.cli", fromlist=["build_parser"]).build_parser()
        args = parser.parse_args(["init"])
        assert args.force is False

    def test_init_force_flag(self) -> None:
        from kali_mcp.cli import build_parser

        args = build_parser().parse_args(["init", "--force"])
        assert args.force is True
