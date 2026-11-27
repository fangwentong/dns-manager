from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

from .utils import remove_suffix

CFG_KEY_CLIENTS = "clients"

CFG_KEY_DNS = "dns"
CFG_KEY_DNS_DOMAIN = "domain"
CFG_KEY_DNS_VENDOR = "vendor"
CFG_KEY_DNS_RECORDS = "records"
CFG_KEY_DNS_RECORD_RR = "rr"
CFG_KEY_DNS_RECORD_TYPE = "type"
CFG_KEY_DNS_RECORD_VALUE = "value"
CFG_KEY_DNS_RECORD_TTL = "ttl"

# Cloudflare DNS
CFG_KEY_DNS_RECORD_CF_PROXIED = "proxied"
CFG_KEY_DNS_RECORD_CF_PRIORITY = "priority"

# Namecheap DNS
CFG_KEY_DNS_RECORD_NC_MX_PREF = "mx_pref"

DEFAULT_DNS_TTL = 300
TRAILING_DOT_TYPES = frozenset({"CNAME", "NS", "MX", "ALIAS"})


def parse_optional_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        raise ValueError(f"Expected integer, got bool: {val!r}")
    return int(val)


def normalize_record_value(record_type: str, value: str) -> str:
    val = str(value).strip()
    rtype = record_type.upper()
    if rtype in TRAILING_DOT_TYPES:
        return remove_suffix(val, ".").lower()
    if rtype == "AAAA":
        try:
            return str(ipaddress.IPv6Address(val))
        except ValueError:
            return val.lower()
    return val


@dataclass
class DnsRecord:
    id: str | None = None
    name: str = ""
    type: str = ""
    value: str = ""
    ttl: int | None = None
    line: str | None = None

    def __post_init__(self) -> None:
        self.name = str(self.name).strip().lower() if self.name is not None else ""
        self.type = str(self.type).strip().upper() if self.type is not None else ""
        self.value = str(self.value).strip() if self.value is not None else ""
        self.ttl = parse_optional_int(self.ttl)

    def normalized_value(self) -> str:
        return normalize_record_value(self.type, self.value)

    def sprint_with_domain(self, domain: str) -> str:
        return f"[{self.type}] {self.name}.{domain} -> {self.value} TTL {self.ttl}"

    def matches(self, other: DnsRecord) -> bool:
        return self._matches(other)

    def _matches(self, other: DnsRecord, bypass_ttl_check: bool = False) -> bool:
        return (
            self.name == other.name
            and self.type == other.type
            and self.normalized_value() == other.normalized_value()
            and (bypass_ttl_check or self.ttl is None or other.ttl is None or self.ttl == other.ttl)
        )


def parse_dns_record_from_config(config: dict[str, Any]) -> list[DnsRecord]:
    name = config[CFG_KEY_DNS_RECORD_RR]
    rec_type = config[CFG_KEY_DNS_RECORD_TYPE]
    raw_values = config[CFG_KEY_DNS_RECORD_VALUE]
    values = raw_values if isinstance(raw_values, list) else [raw_values]
    ttl = config.get(CFG_KEY_DNS_RECORD_TTL, DEFAULT_DNS_TTL)
    return [DnsRecord(name=name, type=rec_type, value=value, ttl=ttl) for value in values]


@dataclass
class CloudflareDnsRecord(DnsRecord):
    """DNS record type for Cloudflare DNS."""

    proxiable: bool | None = None
    proxied: bool | None = None
    priority: int | None = None
    zone_id: str | None = None
    zone_name: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.proxied = bool(self.proxied) if self.proxied is not None else None
        self.priority = parse_optional_int(self.priority)

    def sprint_with_domain(self, domain: str) -> str:
        suffix = " [proxied]" if self.proxied else ""
        return f"{super().sprint_with_domain(domain)}{suffix}"

    def matches(self, other: DnsRecord) -> bool:
        if not isinstance(other, CloudflareDnsRecord):
            return super().matches(other)
        proxied_match = self.proxied is None or other.proxied is None or self.proxied == other.proxied
        effective_proxied = bool(other.proxied) if other.proxied is not None else bool(self.proxied)
        return (
            proxied_match
            and super()._matches(other, bypass_ttl_check=effective_proxied)
            and (self.priority is None or other.priority is None or self.priority == other.priority)
        )


def parse_cloudflare_dns_record_from_config(config: dict[str, Any]) -> list[CloudflareDnsRecord]:
    records = parse_dns_record_from_config(config)
    raw_proxied = config.get(CFG_KEY_DNS_RECORD_CF_PROXIED)
    proxied = bool(raw_proxied) if raw_proxied is not None else None
    priority = config.get(CFG_KEY_DNS_RECORD_CF_PRIORITY)
    return [
        CloudflareDnsRecord(
            id=record.id,
            name=record.name,
            type=record.type,
            value=record.value,
            ttl=record.ttl,
            proxied=proxied,
            priority=priority,
        )
        for record in records
    ]


@dataclass
class NamecheapDnsRecord(DnsRecord):
    mx_pref: int | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.mx_pref = parse_optional_int(self.mx_pref)

    def sprint_with_domain(self, domain: str) -> str:
        suffix = f" mx_pref={self.mx_pref}" if self.mx_pref is not None else ""
        return f"{super().sprint_with_domain(domain)}{suffix}"

    def matches(self, other: DnsRecord) -> bool:
        if not isinstance(other, NamecheapDnsRecord):
            return super().matches(other)
        mx_match = True
        if self.type == "MX" or other.type == "MX":
            mx_match = self.mx_pref is None or other.mx_pref is None or self.mx_pref == other.mx_pref
        return super().matches(other) and mx_match


def parse_namecheap_dns_record_from_config(config: dict[str, Any]) -> list[NamecheapDnsRecord]:
    records = parse_dns_record_from_config(config)
    mx_pref = config.get(CFG_KEY_DNS_RECORD_NC_MX_PREF)
    return [
        NamecheapDnsRecord(
            id=record.id,
            name=record.name,
            type=record.type,
            value=record.value,
            ttl=record.ttl,
            mx_pref=mx_pref,
        )
        for record in records
    ]
