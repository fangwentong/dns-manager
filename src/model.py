#!/usr/bin/env python
# coding=utf-8

class DnsRecord:
    id = None
    name: str
    type: str
    value: str
    ttl: int


class CloudflareDnsRecord(DnsRecord):
    proxiable: bool
    proxied: bool
    zone_id: str
    zone_name: str
