"""Adaptive scheduler — constructs execution graphs from discoveries."""

from __future__ import annotations

from typing import Any


class AdaptiveScheduler:
    """Given a base playbook and discovered assets, append relevant modules."""

    def __init__(self, playbook_def: dict[str, Any]) -> None:
        self.playbook_def = playbook_def

    def branch_on_discovery(
        self, steps: list[dict[str, Any]], assets: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Append conditional steps based on discovered assets/services."""
        extended = list(steps)

        http_services = [
            a for a in assets if a.get("type") == "service" and "http" in str(a.get("protocol", "")).lower()
        ]
        tls_services = [a for a in assets if a.get("type") == "certificate"]
        ssh_services = [a for a in assets if a.get("type") == "service" and a.get("protocol") == "ssh"]

        if http_services:
            extended.append({
                "id": "web_recon_branch",
                "module": "web.http_probe",
                "depends_on": ["network_discovery"],
                "only_if": {"field": "network_discovery.http_services_count", "op": ">", "value": 0},
                "inputs": {},
            })

        if tls_services:
            extended.append({
                "id": "tls_branch",
                "module": "tls.certificate_audit",
                "depends_on": ["network_discovery"],
                "only_if": {"field": "network_discovery.tls_services_count", "op": ">", "value": 0},
                "inputs": {},
            })

        if ssh_services:
            extended.append({
                "id": "ssh_branch",
                "module": "protocols.ssh_audit",
                "depends_on": ["network_discovery"],
                "only_if": {"field": "network_discovery.ssh_services_count", "op": ">", "value": 0},
                "inputs": {},
            })

        return extended
