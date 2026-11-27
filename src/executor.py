from __future__ import annotations

import logging
from typing import Any, Protocol

from .model import DnsRecord
from .namecheap_dns_ops import NamecheapZoneSnapshot
from .planner import DomainPlan


class RecordProvider(Protocol):
    """DNS provider that supports per-record CRUD operations (e.g. Cloudflare, Aliyun)."""

    def get_domain_records(self, domain: str) -> list[Any]: ...
    def add_domain_record(self, domain: str, record: Any) -> Any: ...
    def update_domain_record(self, domain: str, record: Any) -> Any: ...
    def delete_domain_record(self, domain: str, record: Any) -> Any: ...


class ZoneReplaceProvider(Protocol):
    """DNS provider that updates a domain by replacing the full host list (e.g. Namecheap)."""

    write_mode: str

    def get_zone_snapshot(self, domain: str) -> NamecheapZoneSnapshot: ...
    def convert_raw_records(self, raw_records: list[dict[str, Any]]) -> list[Any]: ...
    def replace_domain_records(
        self,
        domain: str,
        desired_records: list[DnsRecord],
        snapshot: NamecheapZoneSnapshot,
        plan: DomainPlan,
        *,
        allow_empty_zone: bool = False,
    ) -> Any: ...


def is_zone_replace_provider(client: Any) -> bool:
    """Explicit write-mode check (never relies on duck-typing that matches MagicMock)."""
    return getattr(client, "write_mode", None) == "zone_replace"


def apply_domain_plan(
    client: Any,
    domain: str,
    plan: DomainPlan,
    desired_records: list[DnsRecord],
    *,
    zone_snapshot: NamecheapZoneSnapshot | None = None,
    allow_empty_zone: bool = False,
) -> int:
    """Execute a DomainPlan against either a ZoneReplaceProvider or a RecordProvider.

    Returns the number of planned changes applied.
    """
    if not plan.has_changes:
        return 0

    if is_zone_replace_provider(client):
        if zone_snapshot is None:
            raise RuntimeError(f"ZoneReplaceProvider requires zone_snapshot for {domain}")
        print(
            f"applying zone replace for {domain}: "
            f"{len(plan.changes)} change(s), preserving {len(plan.unmanaged_records)} unmanaged record(s)"
        )
        client.replace_domain_records(
            domain,
            desired_records,
            zone_snapshot,
            plan,
            allow_empty_zone=allow_empty_zone,
        )
        return len(plan.changes)

    applied = 0
    total = len(plan.changes)
    try:
        for change in plan.changes:
            if change.action in ("delete_conflict", "delete_stale"):
                if change.existing is None:
                    raise RuntimeError(f"Missing existing record for {change.action} on {domain}")
                reason = "conflict" if change.action == "delete_conflict" else "stale"
                print(f"deleting ({reason}) {change.existing.sprint_with_domain(domain)}")
                client.delete_domain_record(domain, change.existing)
                applied += 1
            elif change.action == "create":
                if change.desired is None:
                    raise RuntimeError(f"Missing desired record for create on {domain}")
                print(f"creating {change.desired.sprint_with_domain(domain)}")
                client.add_domain_record(domain, change.desired)
                applied += 1
            elif change.action == "update":
                if change.desired is None:
                    raise RuntimeError(f"Missing desired record for update on {domain}")
                old_desc = change.existing.sprint_with_domain(domain) if change.existing else "<unknown>"
                print(f"updating {old_desc} => {change.desired.sprint_with_domain(domain)}")
                client.update_domain_record(domain, change.desired)
                applied += 1
    except Exception:
        logging.error(
            "Partial apply failure on %s: %d/%d change(s) applied before error; %d remaining.",
            domain,
            applied,
            total,
            total - applied,
        )
        raise
    return applied
