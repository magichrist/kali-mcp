"""MCP prompts — guided workflow templates for clients.

Each prompt renders a short instruction + tool-suggestions message so an
MCP client can drive a standard pentest workflow step by step.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("kali_mcp.prompts")


def _text(msg: str) -> dict:
    """Build an assistant/user content block."""
    return {"type": "text", "text": msg}


def _user(msg: str) -> dict:
    return {"role": "user", "content": _text(msg)}


def _assistant(msg: str) -> dict:
    return {"role": "assistant", "content": _text(msg)}


def _recon(target: str, depth: str = "standard", scope: str = "") -> list[dict]:
    msgs = [
        _user(
            "You are an expert penetration tester. Begin external reconnaissance "
            f"against the target **{target}**"
            + (f" with scope notes: {scope}" if scope else "")
            + ". Run one phase at a time and pause for my approval between phases."
        ),
        _assistant(
            "Phase 1 — asset discovery. I will resolve the target, identify "
            "infrastructure, and map services using the `dns_recon`, `whois_lookup`, "
            "and `ping_sweep` tools, then `nmap_scan` for open ports."
            + (
                " Given the 'deep' depth, I will also enumerate subdomains and "
                "technology fingerprints."
                if depth == "deep"
                else " I will keep verbosity low."
            )
            + "\nShall I start?"
        ),
    ]
    return msgs


def _webapp(url: str, auth: str = "no") -> list[dict]:
    msgs = [
        _user(
            "Perform a web application security assessment of "
            f"**{url}** (authenticated: {auth})."
        ),
        _assistant(
            "I will follow this checklist, running one item at a time and reporting "
            "evidence for each:\n"
            "1. `webapp_crawl` — enumerate endpoints, parameters, and tech stack\n"
            "2. `webapp_scan` — active vulnerability scan\n"
            "3. Manual review of findings before any exploitation\n"
            "4. Retest and summary report\n"
            f"Authenticated assessment: {auth}. Starting with the crawl."
        ),
    ]
    return msgs


def _ad(domain: str, credentials: str = "") -> list[dict]:
    msgs = [
        _user(
            "Assess the Active Directory environment for domain "
            f"**{domain}**"
            + (f" using credentials {credentials}" if credentials else "")
            + "."
        ),
        _assistant(
            "I will enumerate in this order:\n"
            "1. Domain and trust discovery\n"
            "2. User/group/computer enumeration\n"
            "3. ACL and delegation analysis\n"
            "4. Kerberos attack surface (AS-REP roast, Kerberoasting checks)\n"
            "5. Report with remediation\n"
            "Beginning with domain discovery."
        ),
    ]
    return msgs


def _osint(subject: str, sources: str = "default") -> list[dict]:
    msgs = [
        _user(
            f"Gather open-source intelligence on **{subject}** using the "
            f"'{sources}' source set."
        ),
        _assistant(
            "OSINT collection plan:\n"
            "1. Web/DNS footprint — `whois_lookup`, `dns_recon`, certificate search\n"
            "2. Data breach / credential exposure checks (with the target's consent)\n"
            "3. Social footprint review\n"
            "4. Organized intelligence report with sources\n"
            f"Sources: {sources}. Starting with the DNS/web footprint."
        ),
    ]
    return msgs


def _quick_scan(
    target: str, ports: str = "top1000", profile: str = "fast"
) -> list[dict]:
    msgs = [
        _user(
            f"Run a {profile} nmap scan of **{target}** on ports **{ports}** "
            "and summarize findings."
        ),
        _assistant(
            f"Using `nmap_scan` with target={target}, ports={ports}, profile={profile}. "
            "I'll run the scan and give you an open-port/service summary with "
            "next-step recommendations."
        ),
    ]
    return msgs


def _report(engagement: str, findings: str = "") -> list[dict]:
    msgs = [
        _user(
            f"Generate a professional penetration test report for **{engagement}**"
            + (f" from these findings: {findings}" if findings else ".")
        ),
        _assistant(
            "Report structure:\n"
            "1. Executive summary (business impact)\n"
            "2. Scope and methodology\n"
            "3. Findings with severity, evidence, and reproduction steps\n"
            "4. Remediation plan\n"
            "5. Appendix (raw data)\n"
            "I'll ask for each finding's evidence as I draft."
        ),
    ]
    return msgs


def register_prompts(mcp) -> None:
    """Register all workflow prompt templates on the FastMCP server."""

    @mcp.prompt(
        name="recon_workflow",
        description="Guided external reconnaissance workflow for a target host/domain",
    )
    def recon_workflow(
        target: str, depth: str = "standard", scope: str = ""
    ) -> list[dict]:
        return _recon(target, depth, scope)

    @mcp.prompt(
        name="webapp_assessment",
        description="Guided web application security assessment workflow",
    )
    def webapp_assessment(url: str, auth: str = "no") -> list[dict]:
        return _webapp(url, auth)

    @mcp.prompt(
        name="ad_assessment",
        description="Guided Active Directory security assessment workflow",
    )
    def ad_assessment(domain: str, credentials: str = "") -> list[dict]:
        return _ad(domain, credentials)

    @mcp.prompt(
        name="osint_harvest",
        description="Guided OSINT gathering workflow for a subject",
    )
    def osint_harvest(subject: str, sources: str = "default") -> list[dict]:
        return _osint(subject, sources)

    @mcp.prompt(
        name="quick_scan",
        description="Quick nmap scan with findings summary",
    )
    def quick_scan(
        target: str, ports: str = "top1000", profile: str = "fast"
    ) -> list[dict]:
        return _quick_scan(target, ports, profile)

    @mcp.prompt(
        name="report_template",
        description="Professional penetration test report generation",
    )
    def report_template(engagement: str, findings: str = "") -> list[dict]:
        return _report(engagement, findings)

    logger.info("Registered %d prompt templates", 6)
