# Resilience Audit Report

> Generated: 2026-07-24 | Tool: resilience-architect | Scope: kali-mcp full codebase

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Files Audited | 18 source files |
| Tools Registered | 29 (27 native + health_check + generic_command) |
| Critical Findings | 3 |
| High Findings | 5 |
| Medium Findings | 7 |
| Low Findings | 4 |
| Overall Resilience Score | 62/100 |

**Summary:** The application has solid fundamentals — structured error responses, timeout enforcement, semaphore-based concurrency, and graceful process cleanup. However, several critical gaps exist in exception propagation, input sanitization, and failure isolation that could cause cascading failures in production.

---

## Overall Score

| Category | Score | Notes |
|----------|-------|-------|
| Exception Handling | 70/100 | Tool-level catches are good; engine has gaps |
| Input Validation | 75/100 | Consistent validate pattern; some tools lack it |
| Failure Isolation | 55/100 | No circuit breakers; semaphore is global |
| Recovery & Retry | 40/100 | No retries, no fallback, no reconnect |
| Security Hardening | 65/100 | Command injection protected; path traversal weak |
| Production Readiness | 50/100 | No health probes, no metrics, no correlation IDs |
| Resource Management | 70/100 | Output limits enforced; memory leaks possible |
| Error Response Quality | 80/100 | Consistent JSON; some info leakage |

---

## Critical Findings

### RES-001: Execution Engine Exception Propagation

| Field | Value |
|-------|-------|
| Severity | P0 Critical |
| Component | `execution.py:44-52` |
| Issue | `asyncio.create_subprocess_exec` can raise `FileNotFoundError` (binary not found), `PermissionError`, or `ValueError` (bad args). These are NOT caught by the engine's `try/except`. |
| Evidence | `execution.py:44-52` — subprocess creation has no specific exception handling |
| Impact | Unhandled exception propagates to MCP handler, which catches it generically but loses context. Server logs show raw traceback. |
| Failure Scenario | Agent calls tool with binary not installed (e.g., `httpx`). `FileNotFoundError` propagates uncaught. Server continues but agent gets unhelpful error. |
| Root Cause | Subprocess creation wrapped in generic `except Exception` but `FileNotFoundError` from missing binary is not anticipated. |
| Recommended Fix | Catch `FileNotFoundError`, `PermissionError`, `OSError` specifically around subprocess creation and return structured error. |
| Complexity | Low |

### RES-002: Config Integer Parsing Crash

| Field | Value |
|-------|-------|
| Severity | P0 Critical |
| Component | `config.py:16-23` |
| Issue | `int(os.getenv("MCP_PORT", "8399"))` crashes with `ValueError` if env var contains non-integer. No try/except. Server fails to start. |
| Evidence | `config.py:16` — `int()` cast with no protection |
| Impact | Server refuses to start. No graceful fallback. |
| Failure Scenario | `MCP_PORT=abc` in `.env` file. `Config()` instantiation raises `ValueError`. Server crash on startup. |
| Root Cause | No input validation on env var parsing. |
| Recommended Fix | Wrap `int()` casts in try/except with fallback to defaults. |
| Complexity | Low |

### RES-003: Farsight Report File Race Condition

| Field | Value |
|-------|-------|
| Severity | P0 Critical |
| Component | `tools/farsight.py:112-116` |
| Issue | Report file is written by external `farsight` binary, then read by MCP server. If `farsight` fails or writes partial output, `report_path.read_text()` may read empty/partial file or raise `FileNotFoundError`. |
| Evidence | `farsight.py:112-116` — `report_path.exists()` check then `read_text()` with no atomicity guarantee |
| Impact | Agent receives truncated or empty report with no indication of failure. |
| Failure Scenario | `farsight scan` crashes mid-write. Report file exists but is empty/partial. Server reads it and returns garbage. |
| Root Cause | No file integrity validation after external process writes. |
| Recommended Fix | Check file size > 0, validate content starts with expected header, add fallback if file missing. |
| Complexity | Low |

---

## High Findings

### RES-004: Generic Command No Input Sanitization

| Field | Value |
|-------|-------|
| Severity | P1 High |
| Component | `tools/generic_command.py:62-68` |
| Issue | `shlex.split(command_string)` passes raw user input to subprocess. While `shlex.split` prevents shell injection, it does not prevent command abuse (e.g., `rm -rf /`, `dd if=/dev/zero of=/dev/sda`). |
| Evidence | `generic_command.py:62-68` — no blocklist or command filtering |
| Impact | Agent can execute any command on the Kali machine. No guardrails. |
| Failure Scenario | Agent executes destructive command via `generic_command`. No protection. |
| Root Cause | By design (escape hatch), but no safety net. |
| Recommended Fix | Add optional command blocklist (configurable). Log all generic_command executions at WARN level. |
| Complexity | Medium |

### RES-005: File Write Path Traversal

| Field | Value |
|-------|-------|
| Severity | P1 High |
| Component | `tools/file_write.py:53-62` |
| Issue | `validate_path` checks `os.path.isabs()` but does NOT check for path traversal (e.g., `../../etc/passwd`). Agent can write to any absolute path. |
| Evidence | `file_write.py:53-62` — only checks `isabs()`, not path containment |
| Impact | Agent can overwrite system files if running as root. |
| Failure Scenario | Agent writes to `/etc/crontab` or `/root/.ssh/authorized_keys`. |
| Root Cause | No path containment check. |
| Recommended Fix | Add configurable allowed directories (e.g., `/home/kali/`, `/tmp/`). Block writes outside allowed paths. |
| Complexity | Medium |

### RES-006: Semaphore Starvation

| Field | Value |
|-------|-------|
| Severity | P1 High |
| Component | `execution.py:24` |
| Issue | Global semaphore `config.max_concurrent` (default 10) shared across ALL tools. If 10 long-running nmap scans are active, all other tools block. |
| Evidence | `execution.py:24` — single semaphore for all execution |
| Impact | Tool starvation. Short tools (health_check) blocked by long tools (nmap). |
| Failure Scenario | Agent fires 10 nmap scans. 11th request (health_check) blocks for minutes. |
| Root Cause | No per-tool or priority-based concurrency control. |
| Recommended Fix | Consider separate semaphores for long-running vs short tools, or priority queue. |
| Complexity | Medium |

### RES-007: Logging Handler Leak on Re-init

| Field | Value |
|-------|-------|
| Severity | P1 High |
| Component | `logging_utils.py:26-48` |
| Issue | `setup_logging()` calls `addHandler()` without checking if handlers already exist. If called multiple times (e.g., module reload), duplicate handlers accumulate. Each handler writes to the same file, causing duplicate log entries. |
| Evidence | `logging_utils.py:26-48` — no `getLogger().handlers` check |
| Impact | Log files grow 2x, 3x, etc. on each re-init. Performance degradation. |
| Failure Scenario | Server restart via import cycle. Duplicate handlers. |
| Root Cause | No guard against duplicate handler registration. |
| Recommended Fix | Check `if not root.handlers:` before adding handlers. |
| Complexity | Low |

### RES-008: Tool Handler Error Info Leakage

| Field | Value |
|-------|-------|
| Severity | P1 High |
| Component | `server.py:93-95` |
| Issue | `json.dumps({"error": str(e)})` returns raw exception message to agent. May contain file paths, stack details, or internal state. |
| Evidence | `server.py:93-95` — `str(e)` returned directly |
| Impact | Agent sees internal error details. Information disclosure. |
| Failure Scenario | Tool raises exception with file path in message. Agent receives path. |
| Root Cause | No error sanitization before returning to client. |
| Recommended Fix | Return generic error message; log full details server-side only. |
| Complexity | Low |

---

## Medium Findings

### RES-009: No Request Correlation IDs

| Field | Value |
|-------|-------|
| Severity | P2 Medium |
| Component | `server.py`, `execution.py` |
| Issue | No request ID or correlation ID. Cannot trace a request across logs. |
| Impact | Debugging production issues is difficult. Cannot correlate request → execution → error. |
| Recommended Fix | Generate UUID per request, pass through execution, include in all log entries. |
| Complexity | Medium |

### RES-010: No Retry with Backoff

| Field | Value |
|-------|-------|
| Severity | P2 Medium |
| Component | All tools |
| Issue | No tool implements retry logic. External API failures (e.g., SpiderFoot, Farsight) are immediate failures. |
| Impact | Transient network errors cause permanent tool failure. |
| Recommended Fix | Add configurable retry with exponential backoff for network-dependent tools. |
| Complexity | Medium |

### RES-011: No Circuit Breaker

| Field | Value |
|-------|-------|
| Severity | P2 Medium |
| Component | `execution.py` |
| Issue | No circuit breaker pattern. If an external tool hangs repeatedly, every request waits for full timeout. |
| Impact | Repeated failures waste time and resources. |
| Recommended Fix | Track consecutive failures per tool. Open circuit after N failures. |
| Complexity | Medium |

### RES-012: No Graceful Shutdown

| Field | Value |
|-------|-------|
| Severity | P2 Medium |
| Component | `server.py:187` |
| Issue | `uvicorn.run()` has no signal handling. Ctrl+C or SIGTERM kills immediately. In-flight requests are lost. |
| Impact | Data loss on shutdown. No cleanup of running processes. |
| Recommended Fix | Add signal handler that drains in-flight requests before exit. |
| Complexity | Medium |

### RES-013: CORS Wildcard

| Field | Value |
|-------|-------|
| Severity | P2 Medium |
| Component | `server.py:174-178` |
| Issue | `allow_origins=["*"]` allows any origin to make requests. Combined with no auth by default, this is an open endpoint. |
| Impact | Unauthorized access from any origin. |
| Recommended Fix | Restrict to configured origins. Default to localhost only. |
| Complexity | Low |

### RES-014: No Rate Limiting

| Field | Value |
|-------|-------|
| Severity | P2 Medium |
| Component | `server.py` |
| Issue | No rate limiting on incoming requests. Agent can flood server with unlimited concurrent tool calls. |
| Impact | Resource exhaustion. Server becomes unresponsive. |
| Recommended Fix | Add rate limiting middleware (e.g., slowapi). |
| Complexity | Low |

### RES-015: Log File Unbounded Growth

| Field | Value |
|-------|-------|
| Severity | P2 Medium |
| Component | `logging_utils.py:36-40` |
| Issue | Log files grow indefinitely. No rotation, no size limits, no cleanup. |
| Impact | Disk fills up. Server crashes on write. |
| Recommended Fix | Use `RotatingFileHandler` or `TimedRotatingFileHandler` with max size. |
| Complexity | Low |

---

## Low Findings

### RES-016: No Input Schema for Extra Args

| Field | Value |
|-------|-------|
| Severity | P3 Low |
| Component | All tools with `extra_args` |
| Issue | `extra_args` accepts arbitrary string. No validation of what gets appended. |
| Impact | Agent can inject unexpected flags. |
| Recommended Fix | Log extra_args usage. Consider allowlist for critical tools. |
| Complexity | Low |

### RES-017: No Process Zombie Protection

| Field | Value |
|-------|-------|
| Severity | P3 Low |
| Component | `utils/process.py:10-47` |
| Issue | `kill_process_tree` catches all exceptions silently. Zombie processes may persist if kill fails. |
| Impact | Resource leak over time. |
| Recommended Fix | Log warnings when kill fails. Add periodic zombie reaper. |
| Complexity | Low |

### RES-018: Tool Timeout Not Per-Tool Configurable

| Field | Value |
|-------|-------|
| Severity | P3 Low |
| Component | All tools |
| Issue | `default_timeout` is hardcoded per tool class. Cannot adjust without code change. |
| Impact | Inflexible for different environments. |
| Recommended Fix | Allow timeout override via env var per tool (e.g., `MCP_NMAP_TIMEOUT`). |
| Complexity | Low |

### RES-019: No Startup Health Verification

| Field | Value |
|-------|-------|
| Severity | P3 Low |
| Component | `server.py:32-37` |
| Issue | Lifespan only logs. Does not verify tools are available (e.g., check `which nmap`). |
| Impact | Server starts but tools fail at runtime. |
| Recommended Fix | Add startup check that verifies critical binaries exist. |
| Complexity | Low |

---

## Validation Gaps

| Location | Missing Validation | Risk |
|----------|-------------------|------|
| `config.py:16-23` | No type validation on env vars | Server crash on bad config |
| `tools/generic_command.py:62` | No command blocklist | Destructive command execution |
| `tools/file_write.py:53` | No path containment check | Arbitrary file write |
| `tools/file_read.py` | No path traversal check | Arbitrary file read |
| `tools/farsight.py:112` | No file integrity check | Partial/corrupt report returned |
| `tools/searchsploit.py:75` | None value handling (fixed) | AttributeError crash |
| `server.py:174` | No origin restriction | Open CORS |

---

## Exception Handling

| Location | Issue | Recommendation |
|----------|-------|----------------|
| `execution.py:44-52` | Subprocess creation not specifically caught | Catch `FileNotFoundError`, `PermissionError` |
| `server.py:93-95` | Raw exception message returned | Sanitize error before returning |
| `logging_utils.py:51-66` | `log_execution` has no try/except | Wrap in try/except to prevent logging failure from crashing handler |
| `utils/process.py:46` | Silent exception swallowing | Log warning on failure |
| `tools/base.py` | No default exception handling | Add safety net in base class |

---

## Failure Isolation

| Component | Weakness | Suggested Improvement |
|-----------|----------|----------------------|
| Execution Engine | Single global semaphore | Per-tool or priority-based concurrency |
| Tool Registration | No lazy loading | Lazy import to prevent one bad tool from breaking all |
| Logging | No handler isolation | Use separate loggers per component |
| Process Management | No resource tracking | Track active processes, enforce limits |

---

## Recovery

| Component | Missing Recovery | Recommendation |
|-----------|-----------------|----------------|
| Tool Execution | No retry | Add configurable retry with backoff |
| Network Tools | No reconnect | Add reconnect logic for API-dependent tools |
| File Operations | No atomic write | Use temp file + rename pattern |
| Process Cleanup | No zombie reaper | Add periodic process cleanup |
| Server | No graceful shutdown | Add signal handler for clean exit |

---

## Security Risks

| Risk | Evidence | Priority |
|------|----------|----------|
| Open CORS | `allow_origins=["*"]` in `server.py:175` | P2 |
| No auth by default | `server.py:180-185` — auth optional | P1 |
| Arbitrary command execution | `generic_command.py` — no blocklist | P1 |
| Path traversal | `file_write.py:53-62` — no containment | P1 |
| Error info leakage | `server.py:95` — `str(e)` returned | P1 |
| No rate limiting | `server.py` — no throttle | P2 |
| Log file permissions | No chmod on log files | P3 |

---

## Production Risks

| Component | Failure Scenario | Priority |
|-----------|-----------------|----------|
| Config | Bad env var crashes server | P0 |
| Execution | Missing binary causes unhandled exception | P0 |
| Farsight | Partial report returned to agent | P0 |
| Logging | Duplicate handlers on re-init | P1 |
| Concurrency | Semaphore starvation blocks all tools | P1 |
| Disk | Log files fill disk | P2 |
| Network | No retry on transient failures | P2 |
| Shutdown | In-flight requests lost | P2 |

---

## Reliability Roadmap

| Priority | Task | Reason |
|----------|------|--------|
| P0 | Add subprocess creation exception handling | Prevents unhandled crashes |
| P0 | Add config env var validation | Prevents startup failures |
| P0 | Add farsight report integrity check | Prevents garbage output |
| P1 | Sanitize error messages returned to agent | Prevents info leakage |
| P1 | Add path containment for file_write/file_read | Prevents arbitrary file access |
| P1 | Fix logging handler duplication | Prevents log bloat |
| P1 | Add request correlation IDs | Enables debugging |
| P2 | Add rate limiting | Prevents resource exhaustion |
| P2 | Add log rotation | Prevents disk fill |
| P2 | Add circuit breaker pattern | Prevents cascade failures |
| P2 | Add graceful shutdown | Prevents data loss |
| P3 | Add startup health checks | Prevents silent failures |
| P3 | Add per-tool timeout config | Improves flexibility |

---

## Acceptance Criteria

- [x] Every tool has try/except in execute()
- [x] Every tool validates required parameters
- [x] Timeout enforcement on all subprocess calls
- [x] Structured JSON error responses
- [x] No stack traces returned to client
- [x] Process cleanup on timeout
- [x] Output size limits enforced
- [ ] No uncaught exceptions in subprocess creation
- [ ] Config env vars validated with fallbacks
- [ ] Path traversal protection on file operations
- [ ] Request correlation IDs
- [ ] Rate limiting enabled
- [ ] Log rotation configured
- [ ] Graceful shutdown handling
- [ ] Circuit breaker for repeated failures

---

*Report generated by resilience-architect. No code was modified.*
