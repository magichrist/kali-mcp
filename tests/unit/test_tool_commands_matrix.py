"""Parametrized build_command matrix — every tool's argv starts with the right binary."""

from __future__ import annotations

import pytest

from kali_mcp.tools import ALL_TOOLS

TOOL_MAP = {t.name: t for t in ALL_TOOLS}

# tool name → (valid args, expected argv[0], expected argv[1] or None)
COMMAND_MATRIX = {
    "generic_command": ({"command": "echo hi"}, "echo"),
    "python_command": ({"code": "print(1)"}, "python3"),
    "file_read": ({"path": "/etc/hosts"}, "cat"),
    "file_write": (
        {"path": "/tmp/x", "content": "y"},
        "true",
    ),  # no subprocess — sentinel
    "file_download": ({"server_path": "/etc/hosts"}, "file_download"),
    "nmap": ({"target": "10.0.0.1", "scan_type": "quick"}, "nmap"),
    "httpx": ({"target": "127.0.0.1"}, "/usr/bin/httpx-toolkit"),
    "nuclei": ({"target": "127.0.0.1"}, "nuclei"),
    "ffuf": ({"target": "http://x", "wordlist": "/w.txt"}, "ffuf"),
    "katana": ({"target": "http://x"}, "katana"),
    "subfinder": ({"domain": "example.com"}, "subfinder"),
    "amass": ({"domain": "example.com"}, "amass"),
    "sqlmap": ({"target": "http://x"}, "sqlmap"),
    "commix": ({"target": "http://x"}, "commix"),
    "wpscan": ({"target": "http://x"}, "wpscan"),
    "enum4linux": ({"target": "127.0.0.1"}, "enum4linux"),
    "netexec": ({"target": "1.2.3.4", "protocol": "smb"}, "nxc"),
    "crackmapexec": ({"target": "1.2.3.4", "protocol": "smb"}, "crackmapexec"),
    "bloodhound": ({"domain": "corp.local"}, "bloodhound-python"),
    "theharvester": ({"domain": "example.com"}, "theHarvester"),
    "spiderfoot": ({"target": "127.0.0.1"}, "spiderfoot-cli"),
    "naabu": ({"target": "127.0.0.1"}, "naabu"),
    "arjun": ({"target": "http://x"}, "arjun"),
    "whatweb": ({"target": "http://x"}, "whatweb"),
    "dursgo": ({"target": "http://x"}, "dursgo"),
    "searchsploit": ({"query": "apache"}, "searchsploit"),
    "farsight": ({"domain": "example.com"}, "farsight"),
    "flowlyt": ({"repo": "owner/repo"}, "flowlyt"),
    "zighound": ({"command": "scan", "target": "127.0.0.1"}, "zighound"),
    "zizmor": ({"target": "owner/repo"}, "zizmor"),
    "msfconsole": ({"resource": "/tmp/x.rc"}, "msfconsole"),
    "hydra": (
        {
            "target": "10.0.0.1",
            "service": "ssh",
            "user_list": "/u.txt",
            "pass_list": "/p.txt",
        },
        "hydra",
    ),
    "hashcat": ({"hash_file": "/h.txt"}, "hashcat"),
    "gobuster": ({"target": "http://x", "wordlist": "/w.txt"}, "gobuster"),
    "masscan": ({"target": "10.0.0.1"}, "masscan"),
    "john": ({"hash_file": "/h.txt"}, "john"),
    "zap": ({"target": "http://x"}, "zap-baseline.py"),
    "wfuzz": ({"target": "http://x/FUZZ", "wordlist": "/w.txt"}, "wfuzz"),
    "dirb": ({"target": "http://x", "wordlist": "/w.txt"}, "dirb"),
    "medusa": (
        {
            "target": "10.0.0.1",
            "service": "ssh",
            "user_list": "/u.txt",
            "pass_list": "/p.txt",
        },
        "medusa",
    ),
    "bettercap": ({"target": "10.0.0.1", "modules": "net.sniff on"}, "bettercap"),
    "responder": ({"interface": "eth0"}, "responder"),
    "parallel_execute": (
        {"target": "t", "tools": [{"tool": "nmap"}]},
        "parallel_execute",
    ),
    "parallel_status": ({"job_id": "j1"}, "parallel_status"),
    "playbook_recon": ({"target": "example.com"}, "playbook_recon"),
    "playbook_webapp": ({"target": "http://x"}, "playbook_webapp"),
    "playbook_ad": ({"target": "10.0.0.1"}, "playbook_ad"),
    "playbook_engine": (
        {"playbook": {"name": "n", "steps": [{"tools": [{"tool": "nmap"}]}]}},
        "playbook_engine",
    ),
    "playbook_list": ({}, "playbook_list"),
    "playbook_status": ({"name": "p"}, "playbook_status"),
    "vault_write": (
        {"category": "notes", "name": "t", "content": {"k": "v"}},
        "vault_write",
    ),
    "vault_read": ({"category": "notes", "name": "t"}, "vault_read"),
    "vault_query": ({"search": "x"}, "vault_query"),
    "vault_list": ({}, "vault_list"),
    "vault_delete": ({"category": "notes", "name": "t"}, "vault_delete"),
    "vault_stats": ({}, "vault_stats"),
    "finding_transition": (
        {"finding_id": "f1", "new_state": "validated"},
        "finding_transition",
    ),
    "assessment_diff": (
        {"assessment_id_a": "a", "assessment_id_b": "b"},
        "assessment_diff",
    ),
    "coverage_summary": (
        {"assessment_id": "a"},
        "coverage_summary",
    ),
    "assessment_run": (
        {"workflow": "web_assessment", "targets": ["example.com"]},
        "assessment_run",
    ),
    "batch_run": (
        {"operations": [{"tool": "nmap", "args": {"target": "127.0.0.1"}}]},
        "batch_run",
    ),
    "job_control": (
        {"job_id": "job_x", "action": "status"},
        "job_control",
    ),
    "findings_query": ({"severity": "high"}, "findings_query"),
    "evidence_get": ({"evidence_id": "ev_x"}, "evidence_get"),
    "asset_graph": ({"target": "example.com"}, "asset_graph"),
    "tool_catalog": ({"mode": "agent"}, "tool_catalog"),
    "report_generate": (
        {"assessment_id": "assessment_x"},
        "report_generate",
    ),
    "playbook_run": (
        {"playbook": "api_recon", "target": "example.com"},
        "playbook_run",
    ),
    "playbook_catalog": ({}, "playbook_catalog"),
    "playbook_result": ({"job_id": "job_x"}, "playbook_result"),
    "template_list": ({}, "template_list"),
    "template_run": (
        {"template_id": "quick_web_scan", "params": {"target": "example.com"}},
        "template_run",
    ),
}


def test_matrix_covers_every_tool():
    all_tool_names = {t.name for t in ALL_TOOLS}
    assert set(COMMAND_MATRIX) == all_tool_names, (
        "COMMAND_MATRIX out of sync with ALL_TOOLS: "
        f"missing={all_tool_names - set(COMMAND_MATRIX)}, "
        f"extra={set(COMMAND_MATRIX) - all_tool_names}"
    )


@pytest.mark.parametrize("name", sorted(COMMAND_MATRIX))
def test_first_argv_element(name):
    entry = COMMAND_MATRIX[name]
    args, expected_bin = entry[0], entry[1]
    tool = TOOL_MAP[name]
    cmd = tool.build_command(args)
    if name == "generic_command":
        # shell-mode tool returns the command string itself
        assert isinstance(cmd, str) and cmd.startswith(expected_bin)
        return
    assert isinstance(cmd, list)
    assert cmd[0] == expected_bin, f"{name}: argv[0]={cmd[0]!r}, expected {expected_bin!r}"


@pytest.mark.parametrize("name", sorted(COMMAND_MATRIX))
def test_command_is_nonempty_and_no_nones(name):
    args = COMMAND_MATRIX[name][0]
    cmd = TOOL_MAP[name].build_command(args)
    if isinstance(cmd, str):
        assert cmd.strip() != ""
        return
    assert len(cmd) > 0
    assert all(part is not None for part in cmd)
    assert all(str(part).strip() != "" for part in cmd)


# ── Flag-level spot checks ────────────────────────────────────────────────────


def test_hydra_flags():
    cmd = TOOL_MAP["hydra"].build_command(
        {
            "target": "h",
            "service": "ftp",
            "user_list": "/u",
            "pass_list": "/p",
            "port": 2121,
            "threads": 16,
        }
    )
    assert cmd == [
        "hydra",
        "-L",
        "/u",
        "-P",
        "/p",
        "-s",
        "2121",
        "h",
        "ftp",
        "-t",
        "16",
    ]


def test_masscan_port_and_rate():
    cmd = TOOL_MAP["masscan"].build_command(
        {"target": "10.0.0.0/24", "ports": "80,443", "rate": 5000}
    )
    assert "-p" in cmd and "80,443" in cmd
    assert cmd[cmd.index("--rate") + 1] == "5000"


def test_gobuster_mode_and_extensions():
    cmd = TOOL_MAP["gobuster"].build_command(
        {
            "target": "http://x",
            "wordlist": "/w",
            "mode": "dir",
            "extensions": "php,html",
        }
    )
    assert cmd[1] == "dir"
    assert "-x" in cmd and "php,html" in cmd


def test_john_format_wordlist_show():
    cmd = TOOL_MAP["john"].build_command(
        {
            "hash_file": "/h",
            "format": "raw-sha1",
            "wordlist": "/w",
            "show": True,
        }
    )
    assert cmd[cmd.index("--format") + 1] == "raw-sha1"
    assert "--wordlist" in cmd and "--show" in cmd
    assert cmd[-1] == "/h"


def test_hashcat_mode():
    cmd = TOOL_MAP["hashcat"].build_command({"hash_file": "/h", "mode": 0, "wordlist": "/w"})
    assert cmd[cmd.index("-m") + 1] == "0"


def test_wfuzz_rejects_missing_placeholder():
    with pytest.raises(ValueError, match="FUZZ"):
        TOOL_MAP["wfuzz"].validate({"target": "http://x", "wordlist": "/w"})


def test_bettercap_requires_caplet_or_modules():
    with pytest.raises(ValueError, match="caplet"):
        TOOL_MAP["bettercap"].validate({"target": "10.0.0.1"})


def test_zap_rejects_non_http():
    with pytest.raises(ValueError):
        TOOL_MAP["zap"].validate({"target": "ftp://x"})


def test_nuclei_includes_target_flag():
    cmd = TOOL_MAP["nuclei"].build_command({"target": "http://x"})
    assert "-u" in cmd and "http://x" in cmd


def test_sqlmap_batch_mode():
    cmd = TOOL_MAP["sqlmap"].build_command({"target": "http://x"})
    assert "--batch" in cmd


def test_whatweb_aggression_level():
    cmd = TOOL_MAP["whatweb"].build_command({"target": "http://x", "aggression": 3})
    assert any(a == "-a3" for a in cmd)
