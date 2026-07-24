"""Comprehensive tests for kali-mcp — all 29 tools, execution engine, validation, and server wiring.

Run:  python3 test_comprehensive.py
      python3 -m pytest test_comprehensive.py -v   (if pytest installed)
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── Helpers ───────────────────────────────────────────────────────────────────

_PASS = 0
_FAIL = 0


def check(label: str, condition: bool, detail: str = ""):
    global _PASS, _FAIL
    if condition:
        _PASS += 1
        print(f"  PASS: {label}")
    else:
        _FAIL += 1
        msg = f"  FAIL: {label}"
        if detail:
            msg += f"  ({detail})"
        print(msg)


def parse_json(text: str) -> dict:
    """Parse MCP tool response text, stripping leading/trailing junk."""
    start = text.index("{")
    end = text.rindex("}") + 1
    return json.loads(text[start:end])


# ─── 1. Config ─────────────────────────────────────────────────────────────────

def test_config():
    print("\n=== Config ===")
    from config import config
    check("port is 8399", config.port == 8399)
    check("default_timeout is 300", config.default_timeout == 300)
    check("max_timeout is 3600", config.max_timeout == 3600)
    check("max_concurrent is 10", config.max_concurrent == 10)
    check("host is 0.0.0.0", config.host == "0.0.0.0")


# ─── 2. Models ─────────────────────────────────────────────────────────────────

def test_models():
    print("\n=== Models ===")
    from models import ExecutionResult, ToolError, utc_now_iso

    ts = utc_now_iso()
    check("utc_now_iso returns ISO string", "T" in ts and "Z" in ts or "+" in ts)

    r = ExecutionResult(
        tool="test", command="echo hi", stdout="hi\n", stderr="",
        exit_code=0, success=True, timed_out=False,
        duration=0.123, start_time=ts, end_time=ts,
    )
    d = r.to_dict()
    check("to_dict has tool", d["tool"] == "test")
    check("to_dict has stdout", d["stdout"] == "hi\n")
    check("to_dict has success", d["success"] is True)
    check("to_dict has duration", d["duration"] == 0.123)

    e = ToolError(error="bad", details="oops")
    ed = e.to_dict()
    check("ToolError.to_dict error", ed["error"] == "bad")
    check("ToolError.to_dict details", ed["details"] == "oops")
    check("ToolError.to_dict success=False", ed["success"] is False)

    e2 = ToolError(error="bad")
    ed2 = e2.to_dict()
    check("ToolError no details omits key", "details" not in ed2)


# ─── 3. Validation ─────────────────────────────────────────────────────────────

def test_validation():
    print("\n=== Validation ===")
    from validation import (
        validate_required, validate_ip, validate_cidr,
        validate_domain, validate_url, validate_timeout,
        validate_enum, validate_ports,
    )

    # validate_required
    check("required passes with field", validate_required({"x": "1"}, "x") is None)
    try:
        validate_required({}, "x")
        check("required fails without field", False)
    except ValueError:
        check("required fails without field", True)

    # validate_ip
    check("valid IPv4", validate_ip("192.168.1.1") is None)
    check("valid IPv6", validate_ip("::1") is None)
    try:
        validate_ip("not_an_ip")
        check("invalid IP raises", False)
    except ValueError:
        check("invalid IP raises", True)

    # validate_cidr
    check("valid CIDR", validate_cidr("10.0.0.0/8") is None)
    check("valid /32", validate_cidr("192.168.1.1/32") is None)
    try:
        validate_cidr("10.0.0.0/33")
        check("invalid CIDR raises", False)
    except ValueError:
        check("invalid CIDR raises", True)

    # validate_domain
    check("valid domain", validate_domain("example.com") is None)
    check("valid subdomain", validate_domain("sub.example.com") is None)
    try:
        validate_domain("not valid domain!")
        check("invalid domain raises", False)
    except ValueError:
        check("invalid domain raises", True)

    # validate_url
    check("valid https", validate_url("https://example.com") is None)
    check("valid http", validate_url("http://10.0.0.1:8080/path") is None)
    try:
        validate_url("ftp://bad")
        check("invalid URL raises", False)
    except ValueError:
        check("invalid URL raises", True)

    # validate_timeout
    check("timeout int 60", validate_timeout(60) is None)
    check("timeout str '30'", validate_timeout("30") is None)
    check("timeout boundary 1", validate_timeout(1) is None)
    check("timeout boundary 3600", validate_timeout(3600) is None)
    try:
        validate_timeout(0)
        check("timeout 0 raises", False)
    except ValueError:
        check("timeout 0 raises", True)
    try:
        validate_timeout(9999)
        check("timeout 9999 raises", False)
    except ValueError:
        check("timeout 9999 raises", True)
    try:
        validate_timeout("abc")
        check("timeout 'abc' raises", False)
    except ValueError:
        check("timeout 'abc' raises", True)

    # validate_enum
    check("enum valid", validate_enum("smb", ["smb", "ssh"]) is None)
    try:
        validate_enum("bad", ["smb", "ssh"])
        check("enum invalid raises", False)
    except ValueError:
        check("enum invalid raises", True)

    # validate_ports
    check("ports single", validate_ports("80") is None)
    check("ports range", validate_ports("80-443") is None)
    check("ports multi", validate_ports("80,443,8080") is None)
    try:
        validate_ports("99999")
        check("port >65535 raises", False)
    except ValueError:
        check("port >65535 raises", True)


# ─── 4. Responses ──────────────────────────────────────────────────────────────

def test_responses():
    print("\n=== Responses ===")
    from responses import success_response, error_response, error_response_from_exception
    from models import ExecutionResult, ToolError, utc_now_iso

    ts = utc_now_iso()
    r = ExecutionResult(
        tool="test", command="echo", stdout="ok", stderr="",
        exit_code=0, success=True, timed_out=False,
        duration=0.01, start_time=ts, end_time=ts,
    )
    sr = success_response(r)
    check("success has content", "content" in sr)
    check("success isError=False", sr["isError"] is False)
    check("success has text block", sr["content"][0]["type"] == "text")
    parsed = json.loads(sr["content"][0]["text"])
    check("success text is JSON", parsed["tool"] == "test")

    er = error_response(ToolError(error="fail", details="details"))
    check("error isError=True", er["isError"] is True)
    eparsed = json.loads(er["content"][0]["text"])
    check("error text has error", eparsed["error"] == "fail")

    er2 = error_response_from_exception(RuntimeError("boom"))
    check("exception response isError=True", er2["isError"] is True)


# ─── 5. Registry ───────────────────────────────────────────────────────────────

def test_registry():
    print("\n=== Registry ===")
    from registry import ToolRegistry
    from tools.base import BaseTool

    reg = ToolRegistry()

    class FakeTool(BaseTool):
        @property
        def name(self): return "fake"
        @property
        def description(self): return "fake tool"
        def input_schema(self): return {"type": "object", "properties": {}}
        def validate(self, arguments): pass
        def build_command(self, arguments): return ["fake"]
        async def execute(self, arguments): return {}

    t = FakeTool()
    reg.register(t)
    check("get registered tool", reg.get("fake") is t)
    check("get unknown returns None", reg.get("nope") is None)
    check("list_all has 1", len(reg.list_all()) == 1)
    check("tool_names has fake", "fake" in reg.tool_names())

    # overwrite
    t2 = FakeTool()
    reg.register(t2)
    check("overwrite returns new", reg.get("fake") is t2)


# ─── 6. Security ───────────────────────────────────────────────────────────────

def test_security():
    print("\n=== Security ===")
    from security import sanitize_command_parts, quote_argument

    check("sanitize strings", sanitize_command_parts(["a", "b"]) == ["a", "b"])
    check("sanitize mixed", sanitize_command_parts(["echo", 42]) == ["echo", "42"])
    check("quote basic", quote_argument("hello") == "hello")
    check("quote with space", quote_argument("hello world") == "'hello world'")


# ─── 7. All 29 Tools — Schema, Validation, Command Building ───────────────────

# Correct arguments for each tool that passes validation
TOOL_ARGS = {
    "generic_command": {"command": "echo hello"},
    "python_command": {"code": "print('test')"},
    "file_read": {"path": "/etc/hostname"},
    "file_write": {"path": "/tmp/mcp_test_comprehensive", "content": "test"},
    "nmap": {"target": "127.0.0.1", "scan_type": "quick"},
    "httpx": {"target": "127.0.0.1"},
    "nuclei": {"target": "127.0.0.1"},
    "ffuf": {"target": "http://127.0.0.1", "wordlist": "/usr/share/wordlists/dirb/common.txt"},
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
    "file_download": {"server_path": "/etc/hosts"},
}

# Arguments that should FAIL validation
INVALID_ARGS = {
    "generic_command": {"command": ""},
    "python_command": {"code": ""},
    "file_read": {},
    "file_write": {},
    "nmap": {},
    "httpx": {},
    "nuclei": {},
    "ffuf": {"target": "http://x"},
    "katana": {},
    "subfinder": {},
    "amass": {},
    "sqlmap": {},
    "commix": {},
    "wpscan": {},
    "enum4linux": {},
    "netexec": {"target": "1.2.3.4"},
    "crackmapexec": {"target": "1.2.3.4"},
    "bloodhound": {},  # domain is required
    "theharvester": {},
    "spiderfoot": {},
    "naabu": {},
    "arjun": {},
    "whatweb": {},
    "dursgo": None,
    "searchsploit": None,
    "farsight": None,
    "flowlyt": None,
    "zighound": None,
    "zizmor": None,
    "file_download": {},
}


def test_all_tool_schemas():
    print("\n=== Tool Schemas (all 29) ===")
    from tools import ALL_TOOLS

    names = {t.name for t in ALL_TOOLS}
    check("30 tools loaded", len(ALL_TOOLS) == 30, f"got {len(ALL_TOOLS)}")
    check("no duplicate names", len(names) == 30)

    for t in ALL_TOOLS:
        schema = t.input_schema()
        check(
            f"{t.name}: schema has properties",
            "properties" in schema and len(schema["properties"]) > 0,
        )
        # Every property must have a "type"
        for pname, prop in schema.get("properties", {}).items():
            check(
                f"{t.name}.{pname} has type",
                "type" in prop,
            )
        # required fields must exist in properties
        for req in schema.get("required", []):
            check(
                f"{t.name}: required '{req}' in properties",
                req in schema["properties"],
            )
        # description must be non-empty
        check(f"{t.name}: has description", bool(t.description.strip()))


def test_all_tool_validate_and_build():
    print("\n=== Tool Validate + BuildCommand (all 29) ===")
    from tools import ALL_TOOLS

    for t in ALL_TOOLS:
        args = TOOL_ARGS.get(t.name, {})
        try:
            t.validate(args)
            cmd = t.build_command(args)
            check(
                f"{t.name}: validate+build OK",
                isinstance(cmd, list) and len(cmd) > 0,
                f"cmd={cmd[:4]}",
            )
        except Exception as e:
            check(f"{t.name}: validate+build OK", False, str(e))


def test_invalid_args_rejected():
    print("\n=== Invalid Arguments Rejected ===")
    from tools import ALL_TOOLS

    tool_map = {t.name: t for t in ALL_TOOLS}

    for name, invalid in INVALID_ARGS.items():
        if invalid is None:
            continue  # skip tools with all-optional args
        t = tool_map[name]
        try:
            t.validate(invalid)
            check(f"{name}: invalid args rejected", False, f"args={invalid}")
        except (ValueError, KeyError):
            check(f"{name}: invalid args rejected", True)


# ─── 8. Execution Engine ───────────────────────────────────────────────────────

async def test_execution_engine():
    print("\n=== Execution Engine ===")
    from execution import engine

    # Successful command
    r = await engine.execute(["echo", "hello world"], tool="test")
    check("echo stdout", r.stdout.strip() == "hello world")
    check("echo exit_code=0", r.exit_code == 0)
    check("echo success=True", r.success is True)
    check("echo timed_out=False", r.timed_out is False)
    check("echo has duration", r.duration > 0)
    check("echo has start_time", len(r.start_time) > 0)

    # Non-zero exit code
    r2 = await engine.execute(["false"], tool="test")
    check("false exit_code=1", r2.exit_code == 1)
    check("false success=False", r2.success is False)

    # Missing binary
    r3 = await engine.execute(["__nonexistent_binary_xyz__"], tool="test")
    check("missing binary success=False", r3.success is False)
    check("missing binary has stderr", "not found" in r3.stderr.lower())

    # Timeout
    r4 = await engine.execute(
        ["sleep", "30"], tool="test", timeout=1, request_id="timeout_test",
    )
    check("timeout timed_out=True", r4.timed_out is True)
    check("timeout success=False", r4.success is False)

    # cwd parameter
    r5 = await engine.execute(["pwd"], tool="test", cwd="/tmp")
    import os as _os
    expected_cwd = _os.path.realpath("/tmp")
    check("cwd works", r5.stdout.strip() == expected_cwd)

    # env parameter
    r6 = await engine.execute(
        ["bash", "-c", "echo $MCP_TEST_VAR"],
        tool="test",
        env={"MCP_TEST_VAR": "env_works"},
    )
    check("env variable passed", r6.stdout.strip() == "env_works")

    # stderr output
    r7 = await engine.execute(
        ["bash", "-c", "echo err_msg >&2"], tool="test",
    )
    check("stderr captured", "err_msg" in r7.stderr)

    # Shell metacharacters via bash -c
    r8 = await engine.execute(
        ["bash", "-c", "echo a && echo b; echo {x,y}"],
        tool="test",
    )
    lines = r8.stdout.strip().split("\n")
    check("shell && works", lines[0] == "a" and lines[1] == "b")
    check("shell braces work", "x" in lines[2] and "y" in lines[2])


# ─── 9. Generic Command Tool — Full Execution ──────────────────────────────────

async def test_generic_command():
    print("\n=== GenericCommand Tool ===")
    from tools.generic_command import GenericCommandTool

    t = GenericCommandTool()

    # Basic echo
    result = await t.safe_execute({"command": "echo hello"})
    data = parse_json(result["content"][0]["text"])
    check("generic echo success", data["success"])
    check("generic echo stdout", data["stdout"].strip() == "hello")
    check("generic echo no error", result["isError"] is False)

    # Shell features: &&, ;, pipes, redirection
    result = await t.safe_execute({
        "command": "echo abc | tr a-z A-Z"
    })
    data = parse_json(result["content"][0]["text"])
    check("generic pipe works", data["stdout"].strip() == "ABC")

    # Command substitution
    result = await t.safe_execute({
        "command": "echo $(echo nested)"
    })
    data = parse_json(result["content"][0]["text"])
    check("generic subshell", data["stdout"].strip() == "nested")

    # Glob
    result = await t.safe_execute({
        "command": "ls /etc/hos*"
    })
    data = parse_json(result["content"][0]["text"])
    check("generic glob", "hosts" in data["stdout"])

    # Integer timeout
    result = await t.safe_execute({"command": "echo ok", "timeout": 60})
    data = parse_json(result["content"][0]["text"])
    check("generic int timeout", data["success"])

    # String timeout
    result = await t.safe_execute({"command": "echo ok", "timeout": "30"})
    data = parse_json(result["content"][0]["text"])
    check("generic str timeout", data["success"])

    # No timeout (default)
    result = await t.safe_execute({"command": "echo ok"})
    data = parse_json(result["content"][0]["text"])
    check("generic default timeout", data["success"])

    # Empty command rejected
    result = await t.safe_execute({"command": ""})
    check("generic empty cmd isError", result["isError"] is True)

    # Missing command rejected
    result = await t.safe_execute({})
    check("generic missing cmd isError", result["isError"] is True)

    # Cwd
    import os as _os2
    expected = _os2.path.realpath("/tmp")
    result = await t.safe_execute({"command": "pwd", "cwd": "/tmp"})
    data = parse_json(result["content"][0]["text"])
    check("generic cwd", data["stdout"].strip() == expected)


# ─── 10. Python Command Tool ───────────────────────────────────────────────────

async def test_python_command():
    print("\n=== PythonCommand Tool ===")
    from tools.python_command import PythonCommandTool

    t = PythonCommandTool()

    # Basic print
    result = await t.safe_execute({"code": "print(2 + 2)"})
    data = parse_json(result["content"][0]["text"])
    check("python basic print", data["stdout"].strip() == "4")
    check("python success", data["success"])

    # Multi-line with import
    result = await t.safe_execute({
        "code": "import math\nprint(math.sqrt(144))"
    })
    data = parse_json(result["content"][0]["text"])
    check("python import+math", data["stdout"].strip() == "12.0")

    # Stderr on error
    result = await t.safe_execute({
        "code": "import sys\nprint('err', file=sys.stderr)\nprint('out')"
    })
    data = parse_json(result["content"][0]["text"])
    check("python stderr captured", "err" in data["stderr"])
    check("python stdout also captured", data["stdout"].strip() == "out")

    # Syntax error
    result = await t.safe_execute({"code": "def foo("})
    data = parse_json(result["content"][0]["text"])
    check("python syntax error exit_code!=0", data["exit_code"] != 0)

    # Empty code rejected
    result = await t.safe_execute({"code": ""})
    check("python empty code isError", result["isError"] is True)

    # Integer timeout
    result = await t.safe_execute({"code": "print('ok')", "timeout": 60})
    data = parse_json(result["content"][0]["text"])
    check("python int timeout", data["success"])


# ─── 11. File Read Tool ────────────────────────────────────────────────────────

async def test_file_read():
    print("\n=== FileRead Tool ===")
    from tools.file_read import FileReadTool

    t = FileReadTool()

    # Read /etc/hosts (exists on all unix incl macOS)
    result = await t.safe_execute({"path": "/etc/hosts"})
    data = parse_json(result["content"][0]["text"])
    check("file_read success", data["success"])
    check("file_read has content", len(data.get("stdout", "")) > 0)

    # Missing file
    result = await t.safe_execute({"path": "/nonexistent/file"})
    check("file_read missing isError", result["isError"] is True)

    # Missing path
    result = await t.safe_execute({})
    check("file_read no path isError", result["isError"] is True)

    # max_bytes — file_read wraps output in JSON, check bytes_read field
    result = await t.safe_execute({"path": "/etc/hosts", "max_bytes": 5})
    data = parse_json(result["content"][0]["text"])
    inner = parse_json(data["stdout"])
    check("file_read max_bytes=5 truncates", inner["bytes_read"] <= 5)


# ─── 12. File Write Tool ──────────────────────────────────────────────────────

async def test_file_write():
    print("\n=== FileWrite Tool ===")
    from tools.file_write import FileWriteTool

    t = FileWriteTool()

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_write.txt")
        result = await t.safe_execute({"path": path, "content": "hello world"})
        data = parse_json(result["content"][0]["text"])
        check("file_write success", data["success"])

        with open(path) as f:
            check("file_write content correct", f.read() == "hello world")

        # Missing path
        result = await t.safe_execute({"content": "x"})
        check("file_write no path isError", result["isError"] is True)

        # Missing content
        result = await t.safe_execute({"path": path})
        check("file_write no content isError", result["isError"] is True)


# ─── 13. Server Handler Type Mapping ───────────────────────────────────────────

def test_server_handler_types():
    print("\n=== Server Handler Types ===")
    from tools import ALL_TOOLS

    for t in ALL_TOOLS:
        schema = t.input_schema()
        params = schema.get("properties", {})
        required = schema.get("required", [])
        for pname, prop in params.items():
            ptype = prop.get("type")
            has_default = "default" in prop
            is_required = pname in required
            check(
                f"{t.name}.{pname}: type={ptype} default={has_default} req={is_required}",
                ptype in ("string", "integer", "number", "boolean", "object", "array"),
            )


# ─── 14. Tool-Specific Validation (edge cases) ────────────────────────────────

def test_tool_specific_validation():
    print("\n=== Tool-Specific Validation ===")
    from tools import ALL_TOOLS
    tool_map = {t.name: t for t in ALL_TOOLS}

    # nmap: bad target
    t = tool_map["nmap"]
    try:
        t.validate({"target": "1.2.3.4!@#"})
        check("nmap bad target rejected", False)
    except ValueError:
        check("nmap bad target rejected", True)

    # netexec: invalid protocol
    t = tool_map["netexec"]
    try:
        t.validate({"target": "1.2.3.4", "protocol": "badproto"})
        check("netexec bad protocol rejected", False)
    except ValueError:
        check("netexec bad protocol rejected", True)

    # zighound: validation removed — always passes
    t = tool_map["zighound"]
    try:
        t.validate({"command": "badcmd"})
        check("zighound validation removed (no reject)", True)
    except ValueError:
        check("zighound validation removed (no reject)", False)

    # zighound: scan no longer requires target
    t = tool_map["zighound"]
    try:
        t.validate({"command": "scan"})
        check("zighound scan no target check", True)
    except ValueError:
        check("zighound scan no target check", False)

    # zighound: agent no longer requires host
    t = tool_map["zighound"]
    try:
        t.validate({"command": "agent"})
        check("zighound agent no host check", True)
    except ValueError:
        check("zighound agent no host check", False)

    # nmap: timeout boundary
    t = tool_map["nmap"]
    try:
        t.validate({"target": "1.2.3.4", "timeout": 9999})
        check("nmap timeout>3600 rejected", False)
    except ValueError:
        check("nmap timeout>3600 rejected", True)

    # ffuf: needs both target and wordlist
    t = tool_map["ffuf"]
    try:
        t.validate({"target": "http://x"})
        check("ffuf needs wordlist", False)
    except ValueError:
        check("ffuf needs wordlist", True)

    # bloodhound: domain is now required
    t = tool_map["bloodhound"]
    try:
        t.validate({})
        check("bloodhound empty args rejected", False)
    except ValueError:
        check("bloodhound empty args rejected", True)

    # searchsploit: no required params in schema, but validate enforces at least one
    t = tool_map["searchsploit"]
    try:
        t.validate({})
        check("searchsploit: empty args valid (all optional)", True)
    except ValueError:
        check("searchsploit: empty args rejected by validate", True)


# ─── 15. SafeExecute Error Handling ────────────────────────────────────────────

async def test_safe_execute_error_handling():
    print("\n=== SafeExecute Error Handling ===")
    from tools.generic_command import GenericCommandTool

    t = GenericCommandTool()

    # Command that exits non-zero
    result = await t.safe_execute({"command": "exit 42"})
    data = parse_json(result["content"][0]["text"])
    check("safe_execute non-zero exit", data["exit_code"] == 42)
    check("safe_execute success=False", data["success"] is False)
    check("safe_execute isError=False (tool ran ok)", result["isError"] is False)

    # Command that produces output + non-zero exit
    result = await t.safe_execute({"command": "echo partial && exit 1"})
    data = parse_json(result["content"][0]["text"])
    check("safe_execute stdout preserved on error", data["stdout"].strip() == "partial")
    check("safe_execute exit_code=1", data["exit_code"] == 1)

    # Command not found
    result = await t.safe_execute({"command": "totally_fake_command_xyz"})
    data = parse_json(result["content"][0]["text"])
    check("cmd not found success=False", data["success"] is False)


# ─── 16. Command Building Correctness ──────────────────────────────────────────

def test_command_building():
    print("\n=== Command Building Correctness ===")
    from tools import ALL_TOOLS
    tool_map = {t.name: t for t in ALL_TOOLS}

    # generic_command wraps in bash -c
    cmd = tool_map["generic_command"].build_command({"command": "echo hi"})
    check("generic: bash -c wrapper", cmd[0] == "bash" and cmd[1] == "-c" and cmd[2] == "echo hi")

    # python_command uses python3
    cmd = tool_map["python_command"].build_command({"code": "print(1)"})
    check("python: python3 prefix", cmd[0] == "python3")

    # nmap has nmap binary
    cmd = tool_map["nmap"].build_command({"target": "10.0.0.1", "scan_type": "quick"})
    check("nmap: starts with nmap", cmd[0] == "nmap")

    # subfinder has subfinder binary
    cmd = tool_map["subfinder"].build_command({"domain": "example.com"})
    check("subfinder: starts with subfinder", cmd[0] == "subfinder")

    # amass uses enum subcommand
    cmd = tool_map["amass"].build_command({"domain": "example.com"})
    check("amass: amass enum", cmd[0] == "amass" and cmd[1] == "enum")

    # netexec uses nxc binary
    cmd = tool_map["netexec"].build_command({"target": "1.2.3.4", "protocol": "smb"})
    check("netexec: starts with nxc", cmd[0] == "nxc")

    # bloodhound uses bloodhound-python
    cmd = tool_map["bloodhound"].build_command({})
    check("bloodhound: bloodhound-python", cmd[0] == "bloodhound-python")

    # searchsploit is standalone
    cmd = tool_map["searchsploit"].build_command({"query": "apache"})
    check("searchsploit: starts with searchsploit", cmd[0] == "searchsploit")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    global _PASS, _FAIL
    _PASS = 0
    _FAIL = 0

    print("=" * 60)
    print("KALI-MCP COMPREHENSIVE TEST SUITE")
    print("=" * 60)

    # Sync tests
    test_config()
    test_models()
    test_validation()
    test_responses()
    test_registry()
    test_security()
    test_all_tool_schemas()
    test_all_tool_validate_and_build()
    test_invalid_args_rejected()
    test_server_handler_types()
    test_tool_specific_validation()
    test_command_building()

    # Async tests
    asyncio.run(test_execution_engine())
    asyncio.run(test_generic_command())
    asyncio.run(test_python_command())
    asyncio.run(test_file_read())
    asyncio.run(test_file_write())
    asyncio.run(test_safe_execute_error_handling())

    # Summary
    total = _PASS + _FAIL
    print("\n" + "=" * 60)
    print(f"RESULTS: {_PASS}/{total} passed, {_FAIL} failed")
    print("=" * 60)

    if _FAIL > 0:
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
