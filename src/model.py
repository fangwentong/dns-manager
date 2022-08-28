#!/usr/bin/env python
# coding=utf-8

class DnsRecord:
    id = None
    name = None
    type = None
    value = None
    ttl = 300


class CloudflareDnsRecord(DnsRecord):
    proxiable = None
    proxied = None
    zone_id = None
    zone_name = None
