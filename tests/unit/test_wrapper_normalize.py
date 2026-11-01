"""Tests for every wrapper's normalize() and the parser-backed tools' execute() contract."""

from __future__ import annotations

import json

import pytest

from tools import ALL_TOOLS

TOOL_MAP = {t.name: t for t in ALL_TOOLS}

# Synthetic tool outputs exercising each parser
HYDRA_OUT = (
    "Hydra v9.5 starting\n"
    "[22][ssh] host: 10.0.0.1   login: root   password: toor\n"
    "[22][ssh] host: 10.0.0.1   login: admin   password: admin123\n"
    "1 of 1 target successfully completed\n"
)
MEDUSA_OUT = "[ssh] host: 10.0.0.5 user: root password: toor: SUCCESS\n"
JOHN_OUT = "5f4dcc3b5aa765d61d8327deb882cf99:password\n1 session opened\n"
HASHCAT_OUT = "5f4dcc3b5aa765d61d8327deb882cf99:monkey\n"
MASSCAN_OUT = "Discovered open port 80/tcp on 10.0.0.1\nDiscovered open port 443/tcp on 10.0.0.1\n"
GOBUSTER_OUT = "/admin (Status: 200)\n/backup (Status: 403)\n"
DIRB_OUT = "+ http://x/cgi-bin/ (CODE:200)\n==> DIRECTORY: http://x/uploads/\n"
WFUZZ_OUT = "000001:   200  28 L   55 W      5 Ch   'http://x/admin'\n"
RESPONDER_OUT = "[!] NTLMv2 Hash found for user CORP\\admin\n"
ZAP_OUT = "WARN-NEW: 10038 https://x\nLOW: 10098 https://x\n"


class TestNormalizeContract:
    """Every normalize() must return {'normalized': dict} without raising."""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "hydra",
            "medusa",
            "john",
            "hashcat",
            "masscan",
            "gobuster",
            "dirb",
            "wfuzz",
            "responder",
            "zap",
            "msfconsole",
            "bettercap",
        ],
    )
    def test_normalize_returns_dict(self, tool_name):
        tool = TOOL_MAP[tool_name]
        result = tool.normalize("sample stdout", "", 0)
        assert isinstance(result, dict)
        assert isinstance(result.get("normalized"), dict)

    def test_hydra_normalize_counts_creds(self):
        norm = TOOL_MAP["hydra"].normalize(HYDRA_OUT, "", 0)["normalized"]
        assert norm["credentials_found"] == 2
        assert len(norm["credentials"]) == 2

    def test_medusa_normalize_counts_creds(self):
        norm = TOOL_MAP["medusa"].normalize(MEDUSA_OUT, "", 0)["normalized"]
        assert norm["credentials_found"] == 1

    def test_john_normalize_counts_cracked(self):
        norm = TOOL_MAP["john"].normalize(JOHN_OUT, "", 0)["normalized"]
        assert norm["cracked_count"] == 1

    def test_hashcat_normalize_counts_cracked(self):
        norm = TOOL_MAP["hashcat"].normalize(HASHCAT_OUT, "", 0)["normalized"]
        assert norm["cracked_count"] == 1

    def test_masscan_normalize_lists_ports(self):
        norm = TOOL_MAP["masscan"].normalize(MASSCAN_OUT, "", 0)["normalized"]
        assert norm["open_ports"] == 2
        assert {"port": 80, "protocol": "tcp"} in norm["ports"]

    def test_gobuster_normalize_lists_paths(self):
        norm = TOOL_MAP["gobuster"].normalize(GOBUSTER_OUT, "", 0)["normalized"]
        assert norm["paths_found"] == 2
        assert "/admin" in norm["paths"]

    def test_dirb_normalize(self):
        norm = TOOL_MAP["dirb"].normalize(DIRB_OUT, "", 0)["normalized"]
        assert norm["paths_found"] >= 1

    def test_wfuzz_normalize(self):
        norm = TOOL_MAP["wfuzz"].normalize(WFUZZ_OUT, "", 0)["normalized"]
        assert norm["hits_found"] == 1

    def test_responder_normalize(self):
        norm = TOOL_MAP["responder"].normalize(RESPONDER_OUT, "", 0)["normalized"]
        assert norm["hashes_captured"] == 1

    def test_normalize_handles_none_stdout(self):
        for tool_name in ("hydra", "masscan", "gobuster", "wfuzz", "john"):
            result = TOOL_MAP[tool_name].normalize(None, None, 1)  # type: ignore[arg-type]
            assert isinstance(result["normalized"], dict)


class _FakeResult:
    """Minimal ExecutionResult stand-in for monkeypatched engine runs."""

    def __init__(self, stdout: str, exit_code: int = 0):
        self.tool = "fake"
        self.command = "fake --run"
        self.stdout = stdout
        self.stderr = ""
        self.exit_code = exit_code
        self.success = exit_code == 0
        self.timed_out = False
        self.duration = 0.1
        self.start_time = "2026-10-31T00:00:00Z"
        self.end_time = "2026-10-31T00:00:01Z"

    def to_dict(self):
        return {
            "tool": self.tool,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "success": self.success,
            "timed_out": self.timed_out,
            "duration": self.duration,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


PARSER_CASES = {
    "hydra": (
        {"target": "10.0.0.1", "service": "ssh", "user_list": "/u", "pass_list": "/p"},
        HYDRA_OUT,
        "credentials",
        2,
    ),
    "medusa": (
        {"target": "10.0.0.1", "service": "ssh", "user_list": "/u", "pass_list": "/p"},
        MEDUSA_OUT,
        "credentials",
        1,
    ),
    "john": ({"hash_file": "/h"}, JOHN_OUT, "credentials", 1),
    "hashcat": ({"hash_file": "/h"}, HASHCAT_OUT, "credentials", 1),
    "masscan": ({"target": "10.0.0.1"}, MASSCAN_OUT, "findings", 2),
    "gobuster": ({"target": "http://x", "wordlist": "/w"}, GOBUSTER_OUT, "findings", 2),
    "dirb": ({"target": "http://x", "wordlist": "/w"}, DIRB_OUT, "findings", 1),
    "wfuzz": ({"target": "http://x/FUZZ", "wordlist": "/w"}, WFUZZ_OUT, "findings", 1),
    "responder": ({"interface": "eth0"}, RESPONDER_OUT, "findings", 1),
}


@pytest.mark.parametrize("tool_name", sorted(PARSER_CASES))
def test_parser_tools_execute_contract(tool_name, tmp_path, monkeypatch):
    """Full execute() → parsed findings/creds persisted, stdout wrapped in contract."""
    import dataclasses

    from config import config as real_config
    from utils import vault as v

    new_cfg = dataclasses.replace(real_config, db_path=tmp_path / "db.sqlite")
    monkeypatch.setattr("db.manager.config", new_cfg)
    monkeypatch.setattr("db.manager._db_singleton", None)
    monkeypatch.setattr(v, "VAULT_ROOT", tmp_path / "vault")
    v.ensure_vault_dirs()

    args, stdout, payload_key, expected_count = PARSER_CASES[tool_name]
    tool = TOOL_MAP[tool_name]

    import execution

    async def fake_execute(*a, **kw):
        return _FakeResult(stdout)

    monkeypatch.setattr(execution.engine, "execute", fake_execute)
    result = _run(tool.safe_execute(args))

    assert result["isError"] is False
    outer = json.loads(result["content"][0]["text"])
    contract = json.loads(outer["stdout"])
    assert contract["parse_success"] is True
    assert contract["persistence"]["db_recorded"] is True
    assert contract["persistence"]["vault_deposited"] is True
    assert len(contract[payload_key]) == expected_count

    # Vault received the run
    vault_files = list((tmp_path / "vault" / "findings").rglob("*.json"))
    assert vault_files, f"{tool_name}: no vault deposit"


def _run(coro):
    import asyncio

    return asyncio.run(coro)
