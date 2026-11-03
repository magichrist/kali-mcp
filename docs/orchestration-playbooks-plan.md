# Kali MCP Server — Workflow Orchestration / Playbooks Plan

**Goal:** Chain multiple Kali tools into orchestrated pipelines (playbooks) so AI agents can run full engagements — recon, web-app assessment, AD assessment — as a single MCP call with evidence collected automatically.

**Priority:** P1  
**Approach:** Hybrid — built after wrappers + SQLite + vault foundation (Phase 3)

---

## Playbook Pattern

Each playbook is a registered MCP tool that:
1. Takes a target + optional parameters
2. Executes a sequence of sub-tools (parallel where independent, sequential where dependent)
3. Writes each result to SQLite + vault
4. Aggregates findings into a unified report
5. Returns structured output to the agent

---

## Playbook 1: External Reconnaissance

**Goal:** Map a target's attack surface from the outside.

```
Phase 1 (parallel):   subfinder → httpx → masscan → whatweb
Phase 2 (sequential): nmap on discovered hosts → nuclei on discovered URLs
Phase 3 (sequential): sqlmap on interesting endpoints (if forms/params found)
```

**Tool:** `playbook_recon`  
**Params:** `target`, `depth` (fast/deep), `ports` (optional), `output_format` (json/summary)

**Steps:**
1. `subfinder -d <target>` → subdomains → write to SQLite targets + vault
2. `httpx -l <subdomains>` → live hosts + tech → write to SQLite
3. `masscan <target> --rate 1000` → open ports → write to SQLite
4. `whatweb <live_urls>` → tech fingerprints → write to findings
5. `nmap -sV -sC <live_hosts>` → service versions → write to findings
6. `nuclei -t vuln/ <live_urls>` → vulnerabilities → write to findings + vault
7. (deep) `sqlmap` on URLs with parameters → SQLi findings

---

## Playbook 2: Web Application Assessment

**Goal:** Assess a web application for vulnerabilities.

```
Phase 1:     katana (crawl) → arjun (params) → ffuf (dirs)
Phase 2:     commix/sqlmap on discovered params
Phase 3:     nuclei vuln templates on target
```

**Tool:** `playbook_webapp`  
**Params:** `url`, `auth` (optional), `depth` (fast/deep), `scan_xss`, `scan_sqli`, `scan_lfi`

**Steps:**
1. `katana -u <url>` → endpoints + parameters → write to findings
2. `arjun -u <url> -m GET,POST` → hidden parameters → write to findings
3. `ffuf -u <url>/FUZZ -w <wordlist>` → directories → write to findings
4. `nuclei -t vuln/ <url>` → vulnerabilities → write to findings + vault
5. `sqlmap -u "<url>?<param>"` on params with values → SQLi → write to findings + vault
6. `commix -u "<url>" --data="<param>=test"` on POST params → command injection → write to findings

---

## Playbook 3: Active Directory Assessment

**Goal:** Assess an internal AD environment.

```
Phase 1:     enum4linux (domain discovery)
Phase 2:     bloodhound (SharpHound data collection)
Phase 3:     netexec (credential spraying, session enumeration)
Phase 4:     crackmapexec (SMB enumeration, relay)
```

**Tool:** `playbook_ad`  
**Params:** `domain`, `credentials` (optional), `dc_ip` (domain controller), `depth`

**Steps:**
1. `enum4linux -a <dc_ip>` → domain info, users, groups, shares → write to findings
2. `bloodhound` / SharpHound → AD graph data → write to vault
3. `netexec smb <dc_ip> -u <user> -p <pass>` → session enumeration → write to findings
4. `crackmapexec smb <targets> --shares` → share enumeration → write to findings

---

## Playbook Execution Engine

```python
class PlaybookExecutor:
    async def run(self, playbook_name: str, target: str, params: dict) -> dict:
        results = []
        for step in self.playbooks[playbook_name]:
            if step.parallel:
                # Run independent sub-tools concurrently
                batch_results = await asyncio.gather(*[self._run_tool(t) for t in step.tools])
            else:
                # Run sequentially, passing output forward
                result = await self._run_tool(step.tool, context=results)
            results.extend(batch_results or [result])
        return self._aggregate(results)
```

- Progress reported per step via MCP `ctx.report_progress()`
- Each step's output written to SQLite + vault
- Failed steps don't abort the playbook; errors logged, continued with next step
- Resume support: re-run playbook, skip completed steps (tracked in SQLite `scans` table)

---

## MCP Tools

| Tool | Purpose | Params |
|------|---------|--------|
| `playbook_recon` | External reconnaissance pipeline | target, depth, ports |
| `playbook_webapp` | Web application assessment pipeline | url, auth, depth, scan flags |
| `playbook_ad` | Active Directory assessment pipeline | domain, credentials, dc_ip, depth |
| `playbook_list` | List available playbooks | none |
| `playbook_status` | Check status of a running/finished playbook | playbook_run_id |

---

## Integration

- Wrappers provide the atomic tools (nmap, nuclei, subfinder, etc.)
- SQLite stores targets, scans, findings
- Vault stores per-step evidence and cross-agent shareable results
- Normalization converts each tool's raw output into structured findings
