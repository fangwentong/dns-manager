#!/usr/bin/env python
# coding=utf-8


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
    name:str
    type:str
    value:int
    ttl = 300

    def __init__(self, id=None, name=None, type=None, value=None, ttl=None):
        self.id = id
        self.name = name
        self.type = type
        self.value = value
        self.ttl = ttl


def parse_dns_record_from_config(config: dict) -> DnsRecord:
    name = config[CFG_KEY_DNS_RECORD_RR]
    type = config[CFG_KEY_DNS_RECORD_TYPE]
    value = config[CFG_KEY_DNS_RECORD_VALUE]
    ttl = config.get(CFG_KEY_DNS_RECORD_TTL)
    return DnsRecord(name=name, type=type, value=value, ttl=ttl)


class CloudflareDnsRecord(DnsRecord):
    """
    DNS record type for CloudFlare DNS
    """
    proxiable:bool
    proxied:bool
    priority = None
    zone_id :str
    zone_name :str

    def __init__(self, id=None, name=None, type=None, value=None, ttl=None, proxiable=None,
                 proxied=None, priority=None, zone_id=None, zone_name=None):
        super().__init__(id=id, name=name, type=type, value=value, ttl=ttl)
        self.proxiable = proxiable
        self.proxied = proxied
        self.priority = priority
        self.zone_id = zone_id
        self.zone_name = zone_name


def parse_cloudflare_dns_record_from_config(config: dict) -> CloudflareDnsRecord:
    record = parse_dns_record_from_config(config)
    proxied = config.get(CFG_KEY_DNS_RECORD_CF_PROXIED)
    priority = config.get(CFG_KEY_DNS_RECORD_CF_PRIORITY)
    return CloudflareDnsRecord(id=record.id, name=record.name, type=record.type,
                               value=record.value, ttl=record.ttl,
                               proxied=proxied, priority=priority)
