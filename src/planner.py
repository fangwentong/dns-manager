from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Literal

from .model import CloudflareDnsRecord, DnsRecord

ChangeAction = Literal["delete_conflict", "create", "update", "delete_stale"]


@dataclass(frozen=True)
class RecordChange:
    action: ChangeAction
    domain: str
    desired: DnsRecord | None = None
    existing: DnsRecord | None = None


@dataclass(frozen=True)
class DomainPlan:
    domain: str
    vendor: str
    changes: list[RecordChange]
    unmanaged_records: list[DnsRecord]
    unmanaged_indices: tuple[int, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)


def has_conflict(existing: DnsRecord, desired: DnsRecord) -> bool:
    if existing.name != desired.name:
        return False
    # Per RFC 1034, a CNAME cannot coexist with any other record type (or another CNAME value) on the same name.
    if desired.type == "CNAME":
        return existing.type != "CNAME" or existing.normalized_value() != desired.normalized_value()
    return existing.type == "CNAME"


def plan_domain_changes(
    domain: str,
    vendor: str,
    desired_records: list[DnsRecord],
    online_records: list[DnsRecord],
) -> DomainPlan:
    """Compute a deterministic, ordered change plan for a single domain.

    Execution order:
      1. delete_conflict (e.g. A/AAAA <-> CNAME mutual exclusion)
      2. create / update (with existing record id populated onto desired record for updates)
      3. delete_stale (online records within managed (name, type) pairs absent from desired)

    Any online record outside managed (name, type) keys (and not conflicting) is preserved
    in `unmanaged_records`.
    """
    managed_keys: set[tuple[str, str]] = {(r.name, r.type) for r in desired_records}
    desired_by_key: dict[tuple[str, str], list[DnsRecord]] = defaultdict(list)
    for rec in desired_records:
        desired_by_key[(rec.name, rec.type)].append(rec)

    online_by_key: dict[tuple[str, str], list[DnsRecord]] = defaultdict(list)
    for rec in online_records:
        online_by_key[(rec.name, rec.type)].append(rec)

    delete_conflicts: list[RecordChange] = []
    creates_and_updates: list[RecordChange] = []
    delete_stales: list[RecordChange] = []

    conflict_ids: set[int] = set()
    for idx, online in enumerate(online_records):
        if (online.name, online.type) in managed_keys:
            continue
        if any(has_conflict(online, desired) for desired in desired_records):
            conflict_ids.add(idx)
            delete_conflicts.append(RecordChange(action="delete_conflict", domain=domain, existing=online))

    for key, key_desired in desired_by_key.items():
        key_online = list(online_by_key.get(key, []))
        matched_online_indices: set[int] = set()

        for desired in key_desired:
            # Exact normalized value match only (never substring matching!).
            match_idx: int | None = None
            for i, candidate in enumerate(key_online):
                if i in matched_online_indices:
                    continue
                if candidate.normalized_value() == desired.normalized_value():
                    match_idx = i
                    break

            if match_idx is None:
                # If desired is CNAME and an existing CNAME with different value exists, delete conflict first.
                if desired.type == "CNAME":
                    for i, candidate in enumerate(key_online):
                        if i not in matched_online_indices and candidate.type == "CNAME":
                            matched_online_indices.add(i)
                            delete_conflicts.append(
                                RecordChange(action="delete_conflict", domain=domain, existing=candidate)
                            )
                creates_and_updates.append(RecordChange(action="create", domain=domain, desired=desired))
            else:
                matched_online_indices.add(match_idx)
                existing = key_online[match_idx]
                if not existing.matches(desired):
                    updated = replace(desired, id=existing.id)
                    if updated.line is None and existing.line is not None:
                        updated = replace(updated, line=existing.line)
                    if isinstance(updated, CloudflareDnsRecord) and isinstance(existing, CloudflareDnsRecord):
                        if updated.zone_id is None:
                            updated = replace(updated, zone_id=existing.zone_id)
                        if updated.proxied is None:
                            updated = replace(updated, proxied=existing.proxied)
                    creates_and_updates.append(
                        RecordChange(action="update", domain=domain, desired=updated, existing=existing)
                    )

        for i, candidate in enumerate(key_online):
            if i not in matched_online_indices:
                delete_stales.append(RecordChange(action="delete_stale", domain=domain, existing=candidate))

    unmanaged_pairs = [
        (idx, rec)
        for idx, rec in enumerate(online_records)
        if (rec.name, rec.type) not in managed_keys and idx not in conflict_ids
    ]

    return DomainPlan(
        domain=domain,
        vendor=vendor,
        changes=[*delete_conflicts, *creates_and_updates, *delete_stales],
        unmanaged_records=[rec for _, rec in unmanaged_pairs],
        unmanaged_indices=tuple(idx for idx, _ in unmanaged_pairs),
    )


def format_plan(plan: DomainPlan) -> str:
    lines = [f"=== {plan.domain} ({plan.vendor}) ==="]
    if not plan.changes:
        lines.append("  (no changes)")
        return "\n".join(lines)
    for ch in plan.changes:
        if ch.action == "delete_conflict" and ch.existing is not None:
            lines.append(f"  - DELETE (conflict): {ch.existing.sprint_with_domain(plan.domain)}")
        elif ch.action == "create" and ch.desired is not None:
            lines.append(f"  + CREATE: {ch.desired.sprint_with_domain(plan.domain)}")
        elif ch.action == "update" and ch.existing is not None and ch.desired is not None:
            lines.append(
                f"  ~ UPDATE: {ch.existing.sprint_with_domain(plan.domain)} "
                f"=> {ch.desired.sprint_with_domain(plan.domain)}"
            )
        elif ch.action == "delete_stale" and ch.existing is not None:
            lines.append(f"  - DELETE (stale): {ch.existing.sprint_with_domain(plan.domain)}")
    lines.append(f"  ({len(plan.changes)} change(s), {len(plan.unmanaged_records)} unmanaged record(s) preserved)")
    return "\n".join(lines)
