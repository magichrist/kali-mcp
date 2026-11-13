"""Unit tests covering the full tool inventory.

Every registered tool is checked for:
  - a valid JSON schema (properties, types, required fields)
  - validate() + build_command() succeeding with known-good args
  - validate() rejecting known-bad args
"""

from __future__ import annotations

import pytest

from kmcp.tools import ALL_TOOLS

EXPECTED_TOOL_COUNT = 76

VALID_ARGS = {
    "generic_command": {"command": "echo hello"},
    "kmcp_help": {"query": "vault"},
    "python_command": {"code": "print('test')"},
    "file_read": {"path": "/etc/hostname"},
    "file_write": {"path": "/tmp/mcp_test_write", "content": "test"},
    "file_download": {"server_path": "/etc/hosts"},
    "nmap": {"target": "127.0.0.1", "scan_type": "quick"},
    "httpx": {"target": "127.0.0.1"},
    "nuclei": {"target": "127.0.0.1"},
    "ffuf": {
        "target": "http://127.0.0.1",
        "wordlist": "/usr/share/wordlists/dirb/common.txt",
    },
    "katana": {"target": "http://127.0.0.1"},
    "subfinder": {"domain": "example.com"},
    "amass": {"domain": "example.com"},
    "sqlmap": {"target": "http://127.0.0.1"},
    "commix": {"target": "http://127.0.0.1"},
    "wpscan": {"target": "http://127.0.0.1"},
    "enum4linux": {"target": "127.0.0.1"},
    "netexec": {"target": "127.0.0.1", "protocol": "smb"},
    "crackmapexec": {"target": "127.0.0.1", "protocol": "smb"},
    "bloodhound": {"domain": "corp.local"},
    "theharvester": {"domain": "example.com"},
    "spiderfoot": {"target": "127.0.0.1"},
    "naabu": {"target": "127.0.0.1"},
    "arjun": {"target": "http://127.0.0.1"},
    "whatweb": {"target": "http://127.0.0.1"},
    "dursgo": {"target": "http://127.0.0.1"},
    "searchsploit": {"query": "apache 2.4"},
    "farsight": {"domain": "example.com"},
    "flowlyt": {"repo": "owner/repo"},
    "zighound": {"command": "scan", "target": "127.0.0.1"},
    "zizmor": {"target": "owner/repo"},
    "msfconsole": {"resource": "/tmp/mcp_test_rc"},
    "hydra": {
        "target": "127.0.0.1",
        "service": "ssh",
        "user_list": "/tmp/users.txt",
        "pass_list": "/tmp/pass.txt",
    },
    "hashcat": {"hash_file": "/tmp/hashes.txt"},
    "gobuster": {
        "target": "http://127.0.0.1",
        "wordlist": "/usr/share/wordlists/dirb/common.txt",
    },
    "masscan": {"target": "127.0.0.1"},
    "john": {"hash_file": "/tmp/hashes.txt"},
    "zap": {"target": "http://127.0.0.1"},
    "wfuzz": {
        "target": "http://127.0.0.1/FUZZ",
        "wordlist": "/usr/share/wordlists/dirb/common.txt",
    },
    "dirb": {
        "target": "http://127.0.0.1",
        "wordlist": "/usr/share/wordlists/dirb/common.txt",
    },
    "medusa": {
        "target": "127.0.0.1",
        "service": "ssh",
        "user_list": "/tmp/users.txt",
        "pass_list": "/tmp/pass.txt",
    },
    "bettercap": {"target": "127.0.0.0/24", "modules": "net.sniff on"},
    "responder": {"interface": "eth0"},
    "parallel_execute": {
        "target": "127.0.0.1",
        "tools": [{"tool": "generic_command", "args": {"command": "echo hi"}}],
    },
    "parallel_status": {},
    "playbook_recon": {"target": "example.com"},
    "playbook_webapp": {"target": "http://127.0.0.1"},
    "playbook_ad": {"target": "127.0.0.1", "domain": "corp.local"},
    "playbook_engine": {
        "playbook": {
            "name": "test",
            "steps": [
                {
                    "id": "step1",
                    "parallel": False,
                    "tools": [{"tool": "generic_command", "args": {"command": "echo hi"}}],
                }
            ],
        }
    },
    "playbook_list": {},
    "playbook_status": {"name": "playbook_recon"},
    "vault_write": {
        "category": "notes",
        "name": "schema_test",
        "content": {"k": "v"},
    },
    "vault_read": {"category": "notes", "name": "schema_test"},
    "vault_query": {"search": "x"},
    "vault_list": {},
    "vault_delete": {"category": "notes", "name": "schema_test"},
    "vault_stats": {},
    # ── v2.0 Agent Interface Layer ──
    "assessment_run": {
        "workflow": "web_assessment",
        "targets": ["example.com"],
        "profile": "safe_active",
        "execution": {"max_parallel": 2, "max_duration": 300, "resume": False},
        "output": {"detail": "summary", "include_raw": False},
    },
    "batch_run": {
        "operations": [
            {"tool": "nmap", "target_ref": "127.0.0.1", "args": {"target": "127.0.0.1"}}
        ],
        "max_parallel": 2,
        "continue_on_error": True,
    },
    "job_control": {"job_id": "job_test123", "action": "status"},
    "findings_query": {"severity": "high", "limit": 10, "offset": 0},
    "evidence_get": {"evidence_id": "evidence_test123"},
    "asset_graph": {"target": "example.com", "limit": 10},
    "tool_catalog": {"mode": "agent", "layer": "intelligence"},
    "report_generate": {"assessment_id": "assessment_test123", "format": "json"},
    "finding_transition": {
        "finding_id": "finding_test123",
        "new_state": "validated",
        "source": "analyst",
        "reason": "Verified manually",
    },
    "assessment_diff": {
        "assessment_id_a": "assessment_test_a",
        "assessment_id_b": "assessment_test_b",
    },
    "coverage_summary": {"assessment_id": "assessment_test123"},
    "assessment_run": {
        "workflow": "web_assessment",
        "targets": ["example.com"],
    },
    "batch_run": {"operations": [{"tool": "nmap", "args": {"target": "127.0.0.1"}}]},
    "findings_query": {"severity": "high"},
    "asset_graph": {"target": "example.com"},
    "tool_catalog": {"mode": "agent"},
    "report_generate": {"assessment_id": "assessment_test123"},
    "playbook_run": {"playbook": "api_recon", "target": "example.com"},
    "playbook_catalog": {},
    "playbook_result": {"job_id": "job_test123"},
    "playbook_create": {"playbook_id": "quick_http_probe", "name": "Quick HTTP Probe"},
    "playbook_validate": {"playbook_id": "quick_http_probe", "definition": {"name": "quick_http_probe"}},
    "playbook_publish": {
        "playbook_id": "quick_http_probe",
        "version": "1.0",
        "definition": {"name": "quick_http_probe"},
    },
    "template_list": {},
    "template_run": {
        "template_id": "quick_web_scan",
        "params": {"target": "example.com"},
    },
}

INVALID_ARGS = {
    "generic_command": {"command": ""},
    "python_command": {"code": ""},
    "file_read": {},
    "file_write": {},
    "file_download": {},
    "nmap": {},
    "httpx": {},
    "nuclei": {},
    "ffuf": {},
    "katana": {},
    "subfinder": {},
    "amass": {},
    "sqlmap": {},
    "commix": {},
    "wpscan": {},
    "enum4linux": {},
    "netexec": {"target": "127.0.0.1"},
    "crackmapexec": {"target": "127.0.0.1"},
    "bloodhound": {},
    "theharvester": {},
    "spiderfoot": {},
    "naabu": {},
    "arjun": {},
    "whatweb": {},
    "dursgo": None,
    "searchsploit": None,
    "farsight": {},
    "flowlyt": None,
    "zighound": None,  # all-optional args — nothing invalid to test
    "zizmor": None,
    "msfconsole": {},
    "hydra": {},
    "hashcat": {},
    "gobuster": {},
    "masscan": {},
    "john": {},
    "zap": {},
    "wfuzz": {},
    "dirb": {},
    "medusa": {},
    "bettercap": {"target": "127.0.0.0/24"},
    "responder": {},
    "parallel_execute": {"target": "127.0.0.1"},
    "parallel_status": None,
    "playbook_recon": {},
    "playbook_webapp": {"target": "ftp://bad-scheme"},
    "playbook_ad": {},
    "playbook_engine": {"playbook": "not-an-object"},
    "playbook_list": None,
    "playbook_status": None,
    "vault_write": {"category": "", "name": "", "content": None},
    "vault_read": {},
    "vault_query": None,
    "vault_list": None,
    "vault_delete": {},
    "vault_stats": None,
    "finding_transition": {"finding_id": "", "new_state": "invalid_state"},
    "assessment_diff": {},
    "coverage_summary": {},
    "assessment_run": {"targets": ["example.com"]},
    "batch_run": {"operations": []},
    "job_control": {},
    "evidence_get": {},
    "report_generate": {"format": "xml"},
    "playbook_run": {"playbook": "no_such_playbook", "target": "example.com"},
    "playbook_result": {},
    "playbook_create": {"playbook_id": ""},
    "playbook_validate": {"playbook_id": "x", "definition": None},
    "playbook_publish": {"playbook_id": "x", "version": "", "definition": {}},
    "template_run": {"template_id": "no_such_template"},
    "playbook_catalog": None,
    "template_list": None,
    "findings_query": None,
    "asset_graph": None,
    "tool_catalog": None,
}

ALL_TOOL_NAMES = [t.name for t in ALL_TOOLS]


def test_tool_inventory():
    names = {t.name for t in ALL_TOOLS}
    assert len(ALL_TOOLS) == EXPECTED_TOOL_COUNT, f"got {len(ALL_TOOLS)}"
    assert len(names) == EXPECTED_TOOL_COUNT, "duplicate tool names"
    # The roadmap's Phase-2 wrappers must all be registered
    for name in (
        "msfconsole",
        "hydra",
        "hashcat",
        "gobuster",
        "masscan",
        "john",
        "zap",
        "wfuzz",
        "dirb",
        "medusa",
        "bettercap",
        "responder",
        "parallel_execute",
        "parallel_status",
        "playbook_recon",
        "playbook_webapp",
        "playbook_ad",
        "playbook_engine",
        "playbook_list",
        "playbook_status",
    ):
        assert name in names, f"{name} not registered"


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.name)
def test_schema_shape(tool):
    schema = tool.input_schema()
    assert "properties" in schema and len(schema["properties"]) > 0
    for pname, prop in schema["properties"].items():
        assert "type" in prop, f"{tool.name}.{pname} has no type"
        types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
        assert all(
            t in ("string", "integer", "number", "boolean", "object", "array") for t in types
        ), f"{tool.name}.{pname} has invalid type {prop['type']}"
    for req in schema.get("required", []):
        assert req in schema["properties"], f"{tool.name}: required '{req}' not in properties"
    assert tool.description.strip(), f"{tool.name}: empty description"


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.name)
def test_valid_args_pass_and_build(tool):
    args = VALID_ARGS.get(tool.name)
    assert args is not None, f"VALID_ARGS missing entry for {tool.name}"
    tool.validate(args)
    cmd = tool.build_command(args)
    assert isinstance(cmd, (list, str)) and len(cmd) > 0


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.name)
def test_invalid_args_rejected(tool):
    invalid = INVALID_ARGS.get(tool.name)
    if invalid is None:
        pytest.skip("tool has all-optional args")
    with pytest.raises((ValueError, TypeError, KeyError)):
        tool.validate(invalid)


# ─── Command-building specifics ────────────────────────────────────────────────


def _tool_map():
    return {t.name: t for t in ALL_TOOLS}


def test_generic_command_returns_shell_string():
    cmd = _tool_map()["generic_command"].build_command({"command": "echo hi"})
    assert cmd == "echo hi"


def test_python_command_prefix():
    cmd = _tool_map()["python_command"].build_command({"code": "print(1)"})
    assert cmd[0] == "python3"


def test_nmap_binary():
    cmd = _tool_map()["nmap"].build_command({"target": "127.0.0.1", "scan_type": "quick"})
    assert cmd[0] == "nmap"


def test_subfinder_binary():
    cmd = _tool_map()["subfinder"].build_command({"domain": "example.com"})
    assert cmd[0] == "subfinder"


def test_amass_enum_subcommand():
    cmd = _tool_map()["amass"].build_command({"domain": "example.com"})
    assert cmd[0] == "amass" and cmd[1] == "enum"


def test_netexec_uses_nxc():
    cmd = _tool_map()["netexec"].build_command({"target": "127.0.0.1", "protocol": "smb"})
    assert cmd[0] == "nxc"


def test_bloodhound_uses_python_variant():
    cmd = _tool_map()["bloodhound"].build_command({})
    assert cmd[0] == "bloodhound-python"


def test_searchsploit_binary():
    cmd = _tool_map()["searchsploit"].build_command({"query": "apache"})
    assert cmd[0] == "searchsploit"


# ─── Tool-specific validation edge cases ───────────────────────────────────────


def test_nmap_bad_target_rejected():
    with pytest.raises(ValueError):
        _tool_map()["nmap"].validate({"target": "127.0.0.1!@#"})


def test_nmap_timeout_above_max_rejected():
    with pytest.raises(ValueError):
        _tool_map()["nmap"].validate({"target": "127.0.0.1", "timeout": 9999})


def test_netexec_bad_protocol_rejected():
    with pytest.raises(ValueError):
        _tool_map()["netexec"].validate({"target": "127.0.0.1", "protocol": "badproto"})


def test_bloodhound_requires_domain():
    with pytest.raises(ValueError):
        _tool_map()["bloodhound"].validate({})


def test_zighound_validation_relaxed():
    t = _tool_map()["zighound"]
    t.validate({"command": "scan"})
    t.validate({"command": "agent"})


def test_farsight_requires_valid_domain_and_depth():
    t = _tool_map()["farsight"]
    with pytest.raises(ValueError):
        t.validate({})
    with pytest.raises(ValueError):
        t.validate({"domain": "example.com", "depth": 5})
    t.validate({"domain": "example.com", "depth": 3})
