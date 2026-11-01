"""Unit tests for output parsers and persistence helpers (tools/persist.py)."""

from __future__ import annotations

import json

from tools.parallel_execute import aggregate_results
from tools.persist import (
    extract_target,
    parse_dirb,
    parse_gobuster,
    parse_hashcat,
    parse_hydra,
    parse_john,
    parse_masscan,
    parse_medusa,
    parse_responder_hashes,
    parse_wfuzz,
    persist_run,
)


class TestParsers:
    def test_hydra_credentials(self):
        out = "[22][ssh] host: 10.0.0.1   login: root   password: toor\n"
        creds = parse_hydra(out)
        assert len(creds) == 1
        assert creds[0]["service"] == "ssh"
        assert creds[0]["username"] == "root"
        assert creds[0]["password"] == "toor"
        assert creds[0]["port"] == 22

    def test_medusa_credentials(self):
        out = "[ssh] host: 10.0.0.5 user: admin password: secret: SUCCESS\n"
        creds = parse_medusa(out)
        assert len(creds) == 1
        assert creds[0]["username"] == "admin"
        assert creds[0]["password"] == "secret"

    def test_john_show_format(self):
        creds = parse_john("5f4dcc3b5aa765d61d8327deb882cf99:password\n")
        assert creds[0]["password"] == "password"

    def test_john_paren_format(self):
        creds = parse_john("password (admin)\n")
        assert creds[0]["username"] == "admin"
        assert creds[0]["password"] == "password"

    def test_hashcat_pairs(self):
        creds = parse_hashcat("5f4dcc3b5aa765d61d8327deb882cf99:monkey\n")
        assert creds[0]["password"] == "monkey"

    def test_gobuster_paths(self):
        out = "/admin (Status: 200)\nhttp://10.0.0.1/backup (Status: 403)\n"
        findings = parse_gobuster(out)
        assert len(findings) == 2
        assert findings[0]["url"] == "/admin"
        assert findings[1]["url"].endswith("/backup")

    def test_dirb_paths(self):
        out = "+ http://10.0.0.1/cgi-bin/ (CODE:200)\n"
        findings = parse_dirb(out)
        assert len(findings) == 1
        assert findings[0]["type"] == "web_dir"

    def test_wfuzz_hits(self):
        out = "000001:   200  28 L   55 W      5 Ch   'http://10.0.0.1/admin'\n"
        findings = parse_wfuzz(out)
        assert len(findings) == 1
        assert findings[0]["url"] == "http://10.0.0.1/admin"

    def test_masscan_ports(self):
        out = "Discovered open port 80/tcp on 10.0.0.1\n"
        findings = parse_masscan(out)
        assert findings[0]["port"] == 80
        assert findings[0]["service"] == "tcp"

    def test_responder_hash_events(self):
        out = "[+] NTLMv2 Hash found for user admin\n"
        findings = parse_responder_hashes(out)
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"


class TestExtractTarget:
    def test_prefers_target_key(self):
        assert extract_target({"target": "a", "domain": "b"}) == "a"

    def test_falls_back_to_domain(self):
        assert extract_target({"domain": "example.com"}) == "example.com"

    def test_unknown_when_empty(self):
        assert extract_target({}) == "unknown"


class TestAggregateResults:
    def test_dedups_ports_by_key(self):
        def _resp(tool):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "tool": tool,
                                "success": True,
                                "command": "cmd",
                                "stdout": "Discovered open port 80/tcp on 10.0.0.1",
                                "stderr": "",
                            }
                        ),
                    }
                ]
            }

        results = [_resp("masscan"), _resp("nmap")]
        agg = aggregate_results(results)
        assert agg["sub_results_count"] == 2
        # Same (command, port, proto) key across two tools → single entry
        assert len(agg["open_ports"]) == 1

    def test_collects_errors_isolated(self):
        results = [
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "tool": "x",
                                "success": False,
                                "stderr": "boom",
                                "stdout": "",
                            }
                        ),
                    }
                ],
            }
        ]
        agg = aggregate_results(results)
        assert any("boom" in e for e in agg["errors"])


class TestPersistRun:
    def test_persists_to_db_and_vault(self, tmp_path, monkeypatch):
        # Redirect DB + vault to a temp location (config is a frozen dataclass,
        # so patch the module-level reference with a replaced instance)
        import dataclasses

        from config import config as real_config

        new_cfg = dataclasses.replace(real_config, db_path=tmp_path / "db.sqlite")
        monkeypatch.setattr("db.manager.config", new_cfg)
        monkeypatch.setattr("db.manager._db_singleton", None)

        from utils import vault as v

        monkeypatch.setattr(v, "VAULT_ROOT", tmp_path / "vault")
        v.ensure_vault_dirs()

        summary = persist_run(
            "test_tool",
            {"target": "10.9.9.9"},
            "test_tool --run",
            {
                "stdout": "out",
                "stderr": "",
                "success": True,
                "start_time": "",
                "end_time": "",
                "duration": 0,
            },
            findings=[{"type": "note", "title": "t", "evidence": "e"}],
            credentials=[{"service": "ssh", "username": "u", "password": "p"}],
        )
        assert summary["db_recorded"] is True
        assert summary["vault_deposited"] is True

        # Vault got the run + the credential
        vault_files = list((tmp_path / "vault" / "findings").rglob("*.json"))
        assert vault_files
        cred_files = list((tmp_path / "vault" / "credentials").glob("*.json"))
        assert cred_files
        assert json.loads(cred_files[0].read_text())["username"] == "u"

    def test_survives_db_failure(self, monkeypatch):
        import db.manager as dbm

        monkeypatch.setattr(dbm, "get_db", lambda: None)
        summary = persist_run("t", {"target": "x"}, "t", None)
        assert isinstance(summary, dict)
