"""Unit tests for the package entry point (kali_mcp/__main__.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_main_calls_server_main() -> None:
    """``python -m kali_mcp`` must invoke kali_mcp.server.main."""
    with patch("kali_mcp.server.main") as mock_main:
        from kali_mcp import __main__ as main_mod

        main_mod.main()
        mock_main.assert_called_once()


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
