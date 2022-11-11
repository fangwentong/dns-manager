#!/usr/bin/env python
# coding=utf-8
import typing
from typing import List

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


def parse_dns_record_from_config(config: dict) -> List[DnsRecord]:
    name = config[CFG_KEY_DNS_RECORD_RR]
    type = config[CFG_KEY_DNS_RECORD_TYPE]
    raw_values = config[CFG_KEY_DNS_RECORD_VALUE]
    values = raw_values if isinstance(raw_values, List) else [raw_values]
    ttl = config.get(CFG_KEY_DNS_RECORD_TTL)
    return [DnsRecord(name=name, type=type, value=value, ttl=ttl) for value in values]


class CloudflareDnsRecord(DnsRecord):
    """
    DNS record type for CloudFlare DNS
    """
    proxiable: bool
    proxied: bool
    priority = int
    zone_id: str
    zone_name: str

    def __init__(self, id=None, name=None, type=None, value=None, ttl=None, proxiable=None,
                 proxied=None, priority=None, zone_id=None, zone_name=None):
        super().__init__(id=id, name=name, type=type, value=value, ttl=ttl)
        self.proxiable = proxiable
        self.proxied = proxied
        self.priority = priority
        self.zone_id = zone_id
        self.zone_name = zone_name

    def sprint_with_domain(self, domain: str) -> str:
        return '[{}] {}.{} -> {} TTL {}{}'.format(self.type, self.name, domain, self.value, self.ttl,
                                                  ' [proxied]' if self.proxied else '')


def parse_cloudflare_dns_record_from_config(config: dict) -> List[CloudflareDnsRecord]:
    records = parse_dns_record_from_config(config)
    proxied = config.get(CFG_KEY_DNS_RECORD_CF_PROXIED)
    priority = config.get(CFG_KEY_DNS_RECORD_CF_PRIORITY)
    return [CloudflareDnsRecord(id=record.id, name=record.name, type=record.type,
                                value=record.value, ttl=record.ttl,
                                proxied=proxied, priority=priority) for record in records]
