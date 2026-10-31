# Kali MCP Server — New Tool Wrappers Plan

**Goal:** Add high-value Kali Linux tools as native MCP tools so AI pentester agents can call them directly with validated schemas, structured output, and per-tool normalization.

**Priority:** P0  
**Approach:** Hybrid — wrappers built in parallel with SQLite + vault infrastructure.

---

## Tools to Add

| Tool | Kali Binary | Primary Use for AI Agents | Schema Params |
|------|-------------|--------------------------|---------------|
| `msfconsole` | `msfconsole` | Metasploit exploitation framework — run modules, exploits, payloads | resource, action, module, target, rport, lhost, lport, payload, options |
| `hydra` | `hydra` | Brute-force / credential spraying across services (SSH, FTP, SMB, HTTP, etc.) | target, service, user_list, pass_list, port, threads, verbose |
| `hashcat` | `hashcat` | Password cracking from captured hashes | hash_file, hash_type, wordlist, rules, attack_mode, workload |
| `john` | `john` | John the Ripper password cracking | hash_file, wordlist, rules, format, session |
| `gobuster` | `gobuster` | Directory/file/DNS brute-forcing | url, wordlist, extensions, threads, status_codes, method |
| `masscan` | `masscan` | Internet-scale port scanning (faster than nmap for huge ranges) | target, ports, rate, interfaces, exclude |
| `bettercap` | `bettercap` | Network MITM, WiFi, HTTP proxying, sniffing | iface, target, module (arp.spoof, net.sniff, http.proxy, etc.) |
| `responder` | `responder` | LLMNR/NBT-NS/mDNS poisoning — internal network credential capture | iface, analyze, wpad |
| `zap` / `owasp-zap` | `zap-cli` / `owasp-zap` | Web app active/passive scanning, spider, active scan | target, spider, active_scan, auth, context |
| `wfuzz` | `wfuzz` | Web fuzzing — parameter, directory, vhost discovery | url, wordlist, headers, method, payload, filter |
| `dirb` | `dirb` | Directory brute-forcing | url, wordlist, extensions |
| `medusa` | `medusa` | Network brute-force (alternative to hydra) | target, service, user_list, pass_list, port, threads |

---

## Wrapper Pattern (consistent with existing tools)

Each wrapper extends `BaseTool` (`tools/base.py`):

```python
class MsFconsoleTool(BaseTool):
    @property
    def name(self) -> str: return "msfconsole"
    @property
    def description(self) -> str: ...
    @property
    def default_timeout(self) -> int: return 600

    def input_schema(self) -> dict[str, Any]:  # JSON schema with validated fields
    def validate(self, arguments: dict[str, Any]) -> None:  # required fields, ranges
    def build_command(self, arguments: dict[str, Any]) -> list[str]:  # binary + args (no shell)
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:  # engine.execute + normalize
```

**Key rules:**
- `build_command` returns a `list[str]` (no shell) — consistent with `nmap.py`, not `generic_command.py`
- `validate` uses `validation.py` helpers (validate_required, validate_ip, validate_domain, validate_timeout, validate_enum)
- `execute` calls `engine.execute(command=self.build_command(...), tool=self.name, timeout=...)`
- Output is wrapped in `success_response(result)` with `ExecutionResult`
- Each wrapper also calls per-tool normalization (see `docs/result-normalization-plan.md`)

---

## Per-Tool Wrapper Details

### msfconsole
- Runs `msfconsole -x "<commands>"` or `msfconsole -r <resource_script>`
- Params: `resource` (path to .rc script), `commands` (semicolon-separated msf commands), `timeout`
- Example: `{"resource": "/tmp/exploit.rc"}` or `{"commands": "use exploit/multi/handler; set PAYLOAD cmd/unix/reverse; run"}`
- Normalized output: module used, target, payload, session opened (yes/no), shell output

### hydra
- Runs `hydra -L <users> -P <passes> -s <port> <target> <service>`
- Params: `target`, `service` (ssh, ftp, smb, http-get, etc.), `user_list`, `pass_list`, `port`, `threads`
- Normalized output: credentials found (user:pass), service, target, port, attempts

### hashcat
- Runs `hashcat -m <hash_type> -a <attack_mode> <hash_file> <wordlist>`
- Params: `hash_file`, `hash_type`, `wordlist`, `rules` (optional), `attack_mode` (0=straight, 1=combo, 3=brute)
- Normalized output: cracked hashes (hash:plaintext), hash type, total cracked, runtime

### john
- Runs `john --wordlist=<wordlist> --rules=<rules> --format=<format> <hash_file>`
- Params: `hash_file`, `wordlist`, `rules`, `format`, `session`
- Normalized output: cracked passwords, format, session name, status

### gobuster
- Runs `gobuster dir -u <url> -w <wordlist> [options]`
- Params: `url`, `wordlist`, `extensions`, `threads`, `status_codes`, `method`
- Normalized output: discovered paths (url, status_code, size), total found

### masscan
- Runs `masscan <target> -p <ports> --rate <rate>`
- Params: `target` (IP/CIDR/range), `ports`, `rate`, `interfaces`, `exclude`
- Normalized output: open ports (ip, port, protocol), total hosts up

### bettercap
- Runs `bettercap -iface <iface> -eval "<module.commands>"`
- Params: `iface`, `target` (optional), `module` (arp.spoof, net.sniff, http.proxy, wol, etc.), `eval_commands`
- Normalized output: module started, packets captured, hosts discovered, credentials sniffed

### responder
- Runs `responder -I <iface> [-A] [-w]`
- Params: `iface`, `analyze` (bool), `wpad` (bool)
- Normalized output: captured hashes (ntlmv2, etc.), source IP, username, timestamp

### zap / owasp-zap
- Runs `zap-cli quick-scan <target>` or `zap-cli active-scan <target>`
- Params: `target` (URL), `spider` (bool), `active_scan` (bool), `auth` (optional), `context` (optional)
- Normalized output: alerts (name, risk, url, parameter, evidence), total alerts by risk level

### wfuzz
- Runs `wfuzz -w <wordlist> -f <output_format> <url>`
- Params: `url`, `wordlist`, `headers`, `method`, `payload`, `filter`, `threads`
- Normalized output: fuzz hits (payload, url, status_code, size, response_time), total hits

### dirb
- Runs `dirb <url> <wordlist>`
- Params: `url`, `wordlist`, `extensions`
- Normalized output: discovered directories/files, status codes, sizes

### medusa
- Runs `medusa -h <target> -u <users> -p <passes> -M <service> [options]`
- Params: `target`, `service`, `user_list`, `pass_list`, `port`, `threads`
- Normalized output: credentials found, service, target, attempts

---

## Registration

All new tools registered in `tools/__init__.py` `ALL_TOOLS` list, alphabetically integrated.

---

## Testing

Each wrapper gets:
- `validate()` rejects missing/invalid params → `isError: True`
- `build_command()` produces correct binary + arg structure
- `execute()` with `echo`-style mock or actual binary returns `isError: False` when binary exists
- Normalized output contains expected fields
