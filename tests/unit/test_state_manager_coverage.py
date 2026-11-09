"""Coverage tests for state_manager.py checkpoint/resume state persistence.

Covers save_state / load_state / clear_state including the memory fast-path,
the vault read path, non-JSON / missing / malformed vault payloads, and
best-effort error swallowing. Real vault/SQLite I/O is mocked out.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from kali_mcp.workflow import state_manager as sm


@pytest.fixture(autouse=True)
def _clean_run_status():
    """Isolate the module-level RUN_STATUS dict between tests."""
    sm.RUN_STATUS.clear()
    yield
    sm.RUN_STATUS.clear()


class TestSaveState:
    def test_saves_to_memory_and_vault(self):
        state = {"status": "running", "completed_steps": [0, 1], "timeout": 900}
        with patch("kali_mcp.workflow.state_manager.vault_write") as mock_write:
            sm.save_state("pb1", state)
        assert sm.RUN_STATUS["pb1"] == state
        mock_write.assert_called_once_with(
            category="playbook_state",
            name="pb1",
            content=state,
            tags="playbook:state",
        )

    def test_swallows_vault_errors(self):
        with patch(
            "kali_mcp.workflow.state_manager.vault_write",
            side_effect=RuntimeError("vault down"),
        ):
            # must not propagate
            sm.save_state("pb1", {"status": "x"})
        assert sm.RUN_STATUS["pb1"] == {"status": "x"}

    def test_overwrites_existing_entry(self):
        sm.RUN_STATUS["pb1"] = {"status": "old"}
        with patch("kali_mcp.workflow.state_manager.vault_write"):
            sm.save_state("pb1", {"status": "new"})
        assert sm.RUN_STATUS["pb1"] == {"status": "new"}


class TestLoadState:
    def test_loads_from_memory_fast_path(self):
        sm.RUN_STATUS["pb1"] = {"status": "completed"}
        assert sm.load_state("pb1") == {"status": "completed"}
        assert sm.RUN_STATUS["pb1"] == {"status": "completed"}

    def test_loads_from_vault_json(self):
        with patch(
            "kali_mcp.utils.vault.vault_read",
            return_value='{"status": "completed", "completed_steps": [0]}',
        ):
            data = sm.load_state("pb1")
        assert data == {"status": "completed", "completed_steps": [0]}
        # vault hit is cached in memory
        assert sm.RUN_STATUS["pb1"] == data

    def test_loads_vault_payload_without_braces_returns_none(self):
        with patch("kali_mcp.utils.vault.vault_read", return_value="not-a-json-payload"):
            assert sm.load_state("pb1") is None

    def test_loads_vault_read_error_returns_none(self):
        with patch("kali_mcp.utils.vault.vault_read", side_effect=OSError("db locked")):
            assert sm.load_state("pb1") is None

    def test_loads_malformed_json_returns_none(self):
        with patch("kali_mcp.utils.vault.vault_read", return_value="{invalid json"):
            assert sm.load_state("pb1") is None

    def test_loads_empty_content_returns_none(self):
        # empty string is falsy -> skips the braces check -> json.loads("") raises
        with patch("kali_mcp.utils.vault.vault_read", return_value=""):
            assert sm.load_state("pb1") is None

    def test_loads_none_content_returns_none(self):
        with patch("kali_mcp.utils.vault.vault_read", return_value=None):
            assert sm.load_state("pb1") is None


class TestClearState:
    def test_removes_existing_entry(self):
        sm.RUN_STATUS["pb1"] = {"status": "x"}
        sm.clear_state("pb1")
        assert "pb1" not in sm.RUN_STATUS

    def test_clear_missing_entry_is_noop(self):
        # must not raise for an unknown playbook
        sm.clear_state("does-not-exist")
        assert sm.RUN_STATUS == {}

    def test_clear_then_save_works(self):
        sm.RUN_STATUS["pb1"] = {"status": "x"}
        sm.clear_state("pb1")
        with patch("kali_mcp.workflow.state_manager.vault_write"):
            sm.save_state("pb1", {"status": "fresh"})
        assert sm.RUN_STATUS["pb1"] == {"status": "fresh"}
