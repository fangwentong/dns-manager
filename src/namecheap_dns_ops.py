#!/usr/bin/env python
# coding=utf-8

from namecheap import Api
from .model import DnsRecord
from typing import List


class NamecheapDnsOps:
    def __init__(self, api_key, username, ip_address, sandbox, debug):
        self.api = Api(username, api_key, username, ip_address, sandbox=sandbox, debug=debug)

    def get_domain_records(self, domain: str) -> List[DnsRecord]:
        records = self.api.domains_dns_getHosts(domain)
        return [self._convert_to_dns_record(record) for record in records]

    @staticmethod
    def _convert_to_dns_record(dict_record) -> DnsRecord:
        record = DnsRecord()
        record.id = dict_record['HostId']
        record.name = dict_record['Name']
        record.type = dict_record['Type']
        record.value = dict_record['Address']
        record.ttl = dict_record['TTL']
        return record

    # rr, record_type, value, ttl=300
    def add_domain_record(self, domain: str, record: DnsRecord):
        record = {
            'Type': record.type,
            'Name': record.name,
            'Address': record.value,
            'TTL': str(record.ttl)
        }
        return self.api.domains_dns_addHost(domain, record)

    def delete_domain_record(self, domain, record: DnsRecord):
        record = {
            'Type': record.type,
            'Name': record.name,
            'Address': record.value
        }
        return self.api.domains_dns_delHost(domain, record)


def build_namecheap_dns_client_from_config(namecheap_conf: dict) -> NamecheapDnsOps:
    api_key = namecheap_conf.get('api_key')
    username = namecheap_conf.get('username')
    ip = namecheap_conf.get('ip')
    sandbox = namecheap_conf.get('sandbox')
    debug = namecheap_conf.get('debug')
    return NamecheapDnsOps(api_key, username, ip, sandbox, debug)
