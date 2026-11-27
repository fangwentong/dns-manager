#!/usr/bin/env python

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from namecheap import Api

from .model import DnsRecord, NamecheapDnsRecord
from .planner import DomainPlan
from .utils import log_api_call

_NAMECHEAP_MX_TYPES = frozenset({"MX", "MXE"})


@dataclass(frozen=True)
class NamecheapZoneSnapshot:
    raw_records: list[dict[str, Any]]
    email_type: str | None = None
    is_using_our_dns: bool | None = None


def _split_domain_sld_tld(domain: str) -> tuple[str, str]:
    parts = domain.strip().lower().split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid Namecheap domain '{domain}': expected '<sld>.<tld>'")
    return parts[0], parts[1]


class NamecheapDnsOps:
    """Zone-replace DNS provider for Namecheap (via namecheap.domains.dns.setHosts)."""

    write_mode = "zone_replace"

    def __init__(self, api_key, username, ip_address, sandbox, debug):
        self.api = Api(username, api_key, username, ip_address, sandbox=sandbox, debug=debug)

    @log_api_call
    def get_zone_snapshot(self, domain: str) -> NamecheapZoneSnapshot:
        """Fetch raw host records plus zone-level metadata (EmailType, IsUsingOurDNS)."""
        sld, tld = _split_domain_sld_tld(domain)
        xml = self.api._call("namecheap.domains.dns.getHosts", {"SLD": sld, "TLD": tld})
        result_elem = None
        for elem in xml.iter():
            if elem.tag.endswith("DomainDNSGetHostsResult"):
                result_elem = elem
                break
        if result_elem is None:
            raise RuntimeError(f"Namecheap getHosts response missing DomainDNSGetHostsResult for {domain}")

        email_type = result_elem.attrib.get("EmailType") or None
        raw_using = result_elem.attrib.get("IsUsingOurDNS")
        is_using_our_dns: bool | None = None
        if raw_using is not None:
            is_using_our_dns = str(raw_using).strip().lower() == "true"

        raw_records = [dict(child.attrib) for child in list(result_elem)]
        return NamecheapZoneSnapshot(
            raw_records=raw_records,
            email_type=email_type,
            is_using_our_dns=is_using_our_dns,
        )

    @log_api_call
    def get_raw_domain_records(self, domain: str) -> list[dict[str, Any]]:
        return list(self.api.domains_dns_getHosts(domain))

    def convert_raw_records(self, raw_records: list[dict[str, Any]]) -> list[NamecheapDnsRecord]:
        return [self._convert_to_dns_record(record) for record in raw_records]

    @log_api_call
    def get_domain_records(self, domain: str) -> list[NamecheapDnsRecord]:
        records = self.get_raw_domain_records(domain)
        return self.convert_raw_records(records)

    @staticmethod
    def _convert_to_dns_record(dict_record: dict[str, Any]) -> NamecheapDnsRecord:
        return NamecheapDnsRecord(
            id=dict_record.get("HostId"),
            name=dict_record["Name"],
            type=dict_record["Type"],
            value=dict_record["Address"],
            ttl=dict_record.get("TTL"),
            mx_pref=dict_record.get("MXPref"),
        )

    @staticmethod
    def _raw_host_to_set_hosts_entry(raw: dict[str, Any]) -> dict[str, str]:
        """Convert a getHosts raw dict into valid Namecheap setHosts params (stripping read-only attrs)."""
        host_name = raw.get("HostName") if "HostName" in raw else raw.get("Name", "")
        record_type = str(raw.get("RecordType") if "RecordType" in raw else raw.get("Type", "")).upper()
        address = raw.get("Address", "")
        entry: dict[str, str] = {
            "HostName": str(host_name),
            "RecordType": record_type,
            "Address": str(address),
        }
        ttl = raw.get("TTL")
        if ttl is not None and str(ttl) != "":
            entry["TTL"] = str(ttl)
        mx_pref = raw.get("MXPref")
        if record_type in _NAMECHEAP_MX_TYPES and mx_pref is not None and str(mx_pref) != "":
            entry["MXPref"] = str(mx_pref)
        return entry

    @staticmethod
    def _record_to_set_hosts_entry(record: NamecheapDnsRecord) -> dict[str, str]:
        entry: dict[str, str] = {
            "HostName": record.name,
            "RecordType": record.type,
            "Address": record.value,
        }
        if record.ttl is not None:
            entry["TTL"] = str(record.ttl)
        if record.type in _NAMECHEAP_MX_TYPES and record.mx_pref is not None:
            entry["MXPref"] = str(record.mx_pref)
        return entry

    # https://www.namecheap.com/support/api/methods/domains-dns/set-hosts/
    @log_api_call
    def replace_domain_records(
        self,
        domain: str,
        desired_records: list[DnsRecord],
        snapshot: NamecheapZoneSnapshot,
        plan: DomainPlan,
        *,
        allow_empty_zone: bool = False,
    ) -> Any:
        """Apply a DomainPlan atomically via domains.dns.setHosts with strict safety guardrails."""
        if not plan.has_changes:
            return None
        if snapshot is None:
            raise RuntimeError(f"Namecheap safety guardrail: missing zone snapshot for {domain}")
        if snapshot.is_using_our_dns is False:
            raise RuntimeError(
                f"Namecheap safety guardrail: {domain} is not using Namecheap DNS (IsUsingOurDNS=false); "
                "refusing to call setHosts"
            )
        if not snapshot.raw_records and not allow_empty_zone:
            raise RuntimeError(
                f"Namecheap safety guardrail: getHosts returned 0 records for {domain}; "
                "refusing to overwrite zone unless --allow-empty-zone is explicitly set"
            )

        # Single source of truth: use the exact unmanaged indices computed by plan_domain_changes.
        preserved_unmanaged: list[dict[str, str]] = []
        if len(plan.unmanaged_indices) != len(plan.unmanaged_records):
            raise RuntimeError(
                f"Namecheap safety guardrail: unmanaged index metadata mismatch for {domain}"
            )
        for pos, raw_idx in enumerate(plan.unmanaged_indices):
            if raw_idx < 0 or raw_idx >= len(snapshot.raw_records):
                raise RuntimeError(
                    f"Namecheap safety guardrail: unmanaged index {raw_idx} out of range for {domain}"
                )
            raw = snapshot.raw_records[raw_idx]
            planned_rec = plan.unmanaged_records[pos]
            if planned_rec.id is not None and raw.get("HostId") != planned_rec.id:
                raise RuntimeError(
                    f"Namecheap safety guardrail: HostId mismatch at index {raw_idx} "
                    f"(raw={raw.get('HostId')!r}, planned={planned_rec.id!r})"
                )
            preserved_unmanaged.append(self._raw_host_to_set_hosts_entry(raw))

        managed_entries: list[dict[str, str]] = []
        for rec in desired_records:
            if not isinstance(rec, NamecheapDnsRecord):
                raise TypeError(
                    f"Namecheap replace_domain_records requires NamecheapDnsRecord, got {type(rec).__name__}"
                )
            managed_entries.append(self._record_to_set_hosts_entry(rec))

        final_hosts = [*preserved_unmanaged, *managed_entries]
        if not final_hosts:
            raise RuntimeError(
                f"Namecheap safety guardrail: refusing to call setHosts with empty record list for {domain}"
            )

        sld, tld = _split_domain_sld_tld(domain)
        extra_payload = self.api._list_of_dictionaries_to_numbered_payload(final_hosts)
        extra_payload["SLD"] = sld
        extra_payload["TLD"] = tld
        if snapshot.email_type:
            extra_payload["EmailType"] = snapshot.email_type
        return self.api._call("namecheap.domains.dns.setHosts", extra_payload)


def build_namecheap_dns_client_from_config(namecheap_conf: dict) -> NamecheapDnsOps:
    api_key = namecheap_conf.get("api_key")
    username = namecheap_conf.get("username")
    ip = namecheap_conf.get("ip")
    sandbox = namecheap_conf.get("sandbox")
    debug = namecheap_conf.get("debug")
    if debug:
        logging.warning(
            "Namecheap debug=True logs raw HTTP request URLs (including ApiKey); avoid enabling in shared logs."
        )
    return NamecheapDnsOps(api_key, username, ip, sandbox, debug)
