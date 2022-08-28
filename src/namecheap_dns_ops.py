#!/usr/bin/env python
# coding=utf-8

from namecheap import Api
from .model import DnsRecord


class NamecheapDnsOps:
    def __init__(self, api_key, username, ip_address, sandbox, debug):
        self.api = Api(username, api_key, username, ip_address, sandbox=sandbox, debug=debug)

    def get_domain_records(self, domain):
        records = self.api.domains_dns_getHosts(domain)
        return [self._convert_to_dns_record(record) for record in records]

    def _convert_to_dns_record(self, dictRecord):
        record = DnsRecord()
        record.id = dictRecord['HostId']
        record.name = dictRecord['Name']
        record.type = dictRecord['Type']
        record.value = dictRecord['Address']
        record.ttl = dictRecord['TTL']
        return record

    def add_domain_record(self, domain, rr, record_type, value, ttl=300):
        record = {
            'Type': record_type,
            'Name': rr,
            'Address': value,
            'TTL': str(ttl)
        }
        return self.api.domains_dns_addHost(domain, record)

    def delete_domain_record(self, domain, rr, record_type, value):
        record = {
            'Type': record_type,
            'Name': rr,
            'Address': value
        }
        return self.api.domains_dns_delHost(domain, record)
