#!/usr/bin/env python
# coding=utf-8
from typing import List
from .utils import remove_suffix

CFG_KEY_CLIENTS = 'clients'

CFG_KEY_DNS = 'dns'
CFG_KEY_DNS_DOMAIN = 'domain'
CFG_KEY_DNS_VENDOR = 'vendor'
CFG_KEY_DNS_RECORDS = 'records'
CFG_KEY_DNS_RECORD_RR = 'rr'
CFG_KEY_DNS_RECORD_TYPE = 'type'
CFG_KEY_DNS_RECORD_VALUE = 'value'
CFG_KEY_DNS_RECORD_TTL = 'ttl'

# Cloudflare DNS
CFG_KEY_DNS_RECORD_CF_PROXIED = 'proxied'
CFG_KEY_DNS_RECORD_CF_PRIORITY = 'priority'

# Namecheap DNS
CFG_KEY_DNS_RECORD_NC_MX_PREF = 'mx_pref'

DEFAULT_DNS_TTL = 300


class DnsRecord:
    id = None
    name = str
    type = str
    value = str
    ttl = int

    def __init__(self, id=None, name=None, type=None, value=None, ttl=None):
        self.id = id
        self.name = name
        self.type = type
        self.value = value
        self.ttl = ttl

    def sprint_with_domain(self, domain: str) -> str:
        return '[{}] {}.{} -> {} TTL {}'.format(self.type, self.name, domain, self.value, self.ttl)

    def equals(self, other) -> bool:
        return self._matches(other)

    def _matches(self, other, bypass_ttl_check=False) -> bool:
        return self.name == other.name and self.type == other.type \
            and (self.value == other.value
                 or self.type == 'CNAME' and remove_suffix(self.value, '.') == remove_suffix(other.value, '.')) \
            and (bypass_ttl_check or self.ttl is None or other.ttl is None or self.ttl == other.ttl)


def parse_dns_record_from_config(config: dict) -> List[DnsRecord]:
    name = config[CFG_KEY_DNS_RECORD_RR]
    type = config[CFG_KEY_DNS_RECORD_TYPE]
    raw_values = config[CFG_KEY_DNS_RECORD_VALUE]
    values = raw_values if isinstance(raw_values, List) else [raw_values]
    ttl = config.get(CFG_KEY_DNS_RECORD_TTL, DEFAULT_DNS_TTL)
    return [DnsRecord(name=name, type=type, value=value, ttl=ttl) for value in values]


class CloudflareDnsRecord(DnsRecord):
    """
    DNS record type for CloudFlare DNS
    """
    proxiable = bool
    proxied = bool
    priority = int
    zone_id = str
    zone_name = str

    def __init__(self, id=None, name=None, type=None, value=None, ttl=None, proxiable=None,
                 proxied=None, priority=None, zone_id=None, zone_name=None):
        super(CloudflareDnsRecord, self).__init__(id=id, name=name, type=type, value=value, ttl=ttl)
        self.proxiable = proxiable
        self.proxied = proxied
        self.priority = priority
        self.zone_id = zone_id
        self.zone_name = zone_name

    def sprint_with_domain(self, domain: str) -> str:
        return '{}{}'.format(super(CloudflareDnsRecord, self).sprint_with_domain(domain),
                             ' [proxied]' if self.proxied else '')

    def equals(self, other) -> bool:
        return self.proxied == other.proxied \
            and super(CloudflareDnsRecord, self)._matches(other, bypass_ttl_check=self.proxied) \
            and (self.priority is None or other.priority is None or self.priority == other.priority)


def parse_cloudflare_dns_record_from_config(config: dict) -> List[CloudflareDnsRecord]:
    records = parse_dns_record_from_config(config)
    proxied = config.get(CFG_KEY_DNS_RECORD_CF_PROXIED, False)
    priority = config.get(CFG_KEY_DNS_RECORD_CF_PRIORITY)
    return [CloudflareDnsRecord(id=record.id, name=record.name, type=record.type,
                                value=record.value, ttl=record.ttl,
                                proxied=proxied, priority=priority) for record in records]


class NamecheapDnsRecord(DnsRecord):
    mx_pref = int

    def __init__(self, id=None, name=None, type=None, value=None, ttl=None, mx_pref=None):
        super(NamecheapDnsRecord, self).__init__(id=id, name=name, type=type, value=value, ttl=ttl)
        self.mx_pref = mx_pref

    def sprint_with_domain(self, domain: str) -> str:
        return '{}{}'.format(super(NamecheapDnsRecord, self).sprint_with_domain(domain),
                             ' mx_pref={}'.format(self.mx_pref) if self.mx_pref else '')

    def equals(self, other) -> bool:
        return super(NamecheapDnsRecord, self).equals(other) and self.mx_pref == other.mx_pref


def parse_namecheap_dns_record_from_config(config: dict) -> List[NamecheapDnsRecord]:
    records = parse_dns_record_from_config(config)
    mx_pref = config.get(CFG_KEY_DNS_RECORD_NC_MX_PREF)
    return [NamecheapDnsRecord(id=record.id, name=record.name, type=record.type,
                               value=record.value, ttl=record.ttl,
                               mx_pref=mx_pref) for record in records]


class DnsManipulationException(Exception):
    pass
