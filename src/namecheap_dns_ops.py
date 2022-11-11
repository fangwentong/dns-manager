#!/usr/bin/env python
# coding=utf-8

from namecheap import Api
from .model import NamecheapDnsRecord
from typing import List


class NamecheapDnsOps:
    def __init__(self, api_key, username, ip_address, sandbox, debug):
        self.api = Api(username, api_key, username, ip_address, sandbox=sandbox, debug=debug)

    def get_domain_records(self, domain: str) -> List[NamecheapDnsRecord]:
        records = self.api.domains_dns_getHosts(domain)
        return [self._convert_to_dns_record(record) for record in records]

    @staticmethod
    def _convert_to_dns_record(dict_record: dict) -> NamecheapDnsRecord:
        record = NamecheapDnsRecord()
        record.id = dict_record['HostId']
        record.name = dict_record['Name']
        record.type = dict_record['Type']
        record.value = dict_record['Address']
        record.ttl = dict_record['TTL']
        record.mx_pref = dict_record.get('MXPref', None)
        return record

    # https://www.namecheap.com/support/api/methods/domains-dns/set-hosts/
    def add_domain_record(self, domain: str, record: NamecheapDnsRecord):
        data = {
            'RecordType': record.type,
            'HostName': record.name,
            'Address': record.value,
            'MXPref': str(record.mx_pref),
            'TTL': str(record.ttl)
        }
        return self.api.domains_dns_addHost(domain, data)

    def update_domain_record(self, domain: str, record: NamecheapDnsRecord):
        host_records_remote = self.api.domains_dns_getHosts(domain)

        host_records_new = []
        for r in host_records_remote:
            cond_type = r['Type'] == record.type
            cond_name = r['Name'] == record.name
            cond_addr = r['Address'] == record.value

            if cond_type and cond_name and cond_addr:
                # skipping this record as it is the one we want to delete
                pass
            else:
                host_records_new.append(r)

        host_records_new.append({
            'RecordType': record.type,
            'HostName': record.name,
            'Address': record.value,
            'MXPref': str(record.mx_pref),
            'TTL': str(record.ttl)
        })
        return self.api.domains_dns_setHosts(domain, host_records_new)

    def delete_domain_record(self, domain, record: NamecheapDnsRecord):
        data = {
            'RecordType': record.type,
            'HostName': record.name,
            'Address': record.value
        }
        return self.api.domains_dns_delHost(domain, data)


def build_namecheap_dns_client_from_config(namecheap_conf: dict) -> NamecheapDnsOps:
    api_key = namecheap_conf.get('api_key')
    username = namecheap_conf.get('username')
    ip = namecheap_conf.get('ip')
    sandbox = namecheap_conf.get('sandbox')
    debug = namecheap_conf.get('debug')
    return NamecheapDnsOps(api_key, username, ip, sandbox, debug)
