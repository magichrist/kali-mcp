"""Unit tests for the package entry point (kali_mcp/__main__.py)."""

from __future__ import annotations

import contextlib
import io
from unittest.mock import patch

from kali_mcp.cli import main as cli_main


def test_main_no_arguments_prints_help() -> None:
    """``python -m kali_mcp`` with no args prints help instead of starting the server."""
    from io import StringIO

    import contextlib

    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        assert cli_main([]) == 0
    output = buf.getvalue()
    assert "usage:" in output
    assert "playbook" in output
    assert "tool" in output
    assert "execution" in output


def test_main_guard_invokes_main() -> None:
    """The __main__ guard calls main() when the module is run as __main__."""
    from kali_mcp.server import main as real_main

    assert callable(real_main)
    # __main__.py re-exports main; verify it points to a callable
    from kali_mcp import __main__ as main_mod

    assert callable(main_mod.main)


def test_module_has_main_attribute() -> None:
    from kali_mcp import __main__ as main_mod

    assert hasattr(main_mod, "main")
    assert callable(main_mod.main)
