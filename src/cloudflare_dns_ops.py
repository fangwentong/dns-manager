#!/usr/bin/env python
# coding=utf-8

import CloudFlare
from .model import CloudflareDnsRecord
from .utils import remove_suffix
from typing import List


class CloudflareDnsOps:

    def __init__(self, email=None, token=None, certtoken=None, debug=False):
        self.cf = CloudFlare.CloudFlare(email=email, token=token, certtoken=certtoken, debug=debug)

    def get_domain_records(self, domain: str, record: CloudflareDnsRecord = None) -> List[CloudflareDnsRecord]:
        if record is None:
            record = CloudflareDnsRecord()

        if record.zone_id is None:
            record.zone_id = self._get_zone_id(domain)

        # https://api.cloudflare.com/#dns-records-for-a-zone-list-dns-records
        params = {
            'match': 'all',
            'page': 1,
            'per_page': 1000,
        }
        if record.name == '@':
            params['name'] = domain
        elif record.name is not None:
            params['name'] = record.name + '.' + domain

        if record.value is not None:
            params['content'] = record.value
        if record.type is not None:
            params['type'] = record.type
        if record.proxied is not None:
            params['proxied'] = record.proxied

        dns_records = self.cf.zones.dns_records.get(record.zone_id, params=params)
        return [self._convert_resp_to_dns_record(record) for record in dns_records]

    @staticmethod
    def _convert_resp_to_dns_record(dict_record: dict) -> CloudflareDnsRecord:
        record = CloudflareDnsRecord()
        record.id = dict_record.get('id')
        record.type = dict_record.get('type')
        record.value = dict_record.get('content')
        record.ttl = dict_record.get('ttl')
        record.proxiable = dict_record.get('proxiable')
        record.proxied = dict_record.get('proxied', False)
        record.priority = dict_record.get('priority')
        record.zone_id = dict_record.get('zone_id')
        record.zone_name = dict_record.get('zone_name')

        record_name = remove_suffix(dict_record['name'], '.' + record.zone_name)
        if record_name == record.zone_name:
            record_name = '@'
        record.name = record_name
        return record

    def _get_zone_id(self, domain: str) -> str:
        params = {'name': domain}
        zones = self.cf.zones.get(params=params)
        if len(zones) == 0:
            raise 'zone not found for domain {}'.format(domain)
        return zones[0]['id']

    # https://api.cloudflare.com/#dns-records-for-a-zone-create-dns-record
    def add_domain_record(self, domain: str, record: CloudflareDnsRecord):
        if record.zone_id is None:
            record.zone_id = self._get_zone_id(domain)
        data = {
            'type': record.type,
            'name': record.name,
            'content': record.value,
            'ttl': record.ttl,
            'priority': record.priority,
            'proxied': record.proxied,
        }
        return self.cf.zones.dns_records.post(record.zone_id, data=data)

    # https://api.cloudflare.com/#dns-records-for-a-zone-update-dns-record
    def update_domain_record(self, domain: str, record: CloudflareDnsRecord):
        if record.zone_id is None:
            record.zone_id = self._get_zone_id(domain)
        if record.id is None:
            records = self.get_domain_records(domain, CloudflareDnsRecord(name=record.name, zone_id=record.zone_id))
            if len(records) == 0:
                raise 'record not exist for {}.{}'.format(record.name, domain)
            if len(records) > 1:
                raise 'multiple records for {}.{}'.format(record.name, domain)
            record.id = records[0].id
        data = {
            'type': record.type,
            'name': record.name,
            'content': record.value,
            'ttl': record.ttl,
            'priority': record.priority,
            'proxied': record.proxied,
        }
        return self.cf.zones.dns_records.put(record.zone_id, record.id, data=data)

    # https://api.cloudflare.com/#dns-records-for-a-zone-delete-dns-record
    def delete_domain_record(self, domain: str, record: CloudflareDnsRecord):
        if record.zone_id is None:
            record.zone_id = self._get_zone_id(domain)
        if record.id is not None:
            return self.cf.zones.dns_records.delete(record.zone_id, record.id)

        records = self.get_domain_records(domain, record)
        if len(records) == 0:
            raise 'delete failed: record {} not exist for domain {}'.format(record, domain)
        if len(records) > 1:
            raise 'delete failed: multiple records for {} in domain {}'.format(record, domain)
        return self.cf.zones.dns_records.delete(record.zone_id, records[0].id)


def build_cloudflare_dns_client_from_config(config: dict) -> CloudflareDnsOps:
    # email=None, token=None, certtoken=None, debug=False
    email = config.get('email')
    token = config.get('token')
    certtoken = config.get('certtoken')
    debug = config.get('debug')
    return CloudflareDnsOps(email, token, certtoken, debug)
