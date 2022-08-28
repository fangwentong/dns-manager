#!/usr/bin/env python
# coding=utf-8

import CloudFlare
from .model import CloudflareDnsRecord
from .utils import remove_suffix


class CloudflareDnsOps:

    def __init__(self, email=None, token=None, certtoken=None, debug=False):
        self.cf = CloudFlare.CloudFlare(email=email, token=token, certtoken=certtoken, debug=debug)

    def get_domain_records(self, domain, rr=None, record_type=None, value=None, proxied=None, zone_id=None):
        if zone_id is None:
            zone_id = self._get_zone_id(domain)
        params = {
            'match': 'all',
        }
        if record_type is not None:
            params['type'] = record_type
        if rr == '@':
            params['name'] = domain
        elif rr is not None:
            params['name'] = rr + '.' + domain
        if value is not None:
            params['content'] = value
        if proxied is not None:
            params['proxied'] = proxied
        dns_records = self.cf.zones.dns_records.get(zone_id, params=params)
        return [self._convert_to_dns_record(record) for record in dns_records]

    def _convert_to_dns_record(self, dict_record):
        record = CloudflareDnsRecord()
        record.id = dict_record['id']
        record.type = dict_record['type']
        record.value = dict_record['content']
        record.ttl = dict_record['ttl']
        record.proxiable = dict_record['proxiable']
        record.proxied = dict_record['proxied']
        record.zone_id = dict_record['zone_id']
        record.zone_name = dict_record['zone_name']

        record_name = remove_suffix(dict_record['name'], '.' + record.zone_name)
        if record_name == record.zone_name:
            record_name = '@'
        record.name = record_name
        return record

    def _get_zone_id(self, domain):
        params = {'name': domain}
        zones = self.cf.zones.get(params=params)
        if len(zones) == 0:
            raise "zone not found for domain {}".format(domain)
        return zones[0]['id']

    def add_domain_record(self, domain, rr, record_type, value, ttl=300, priority=10, proxied=False, zone_id=None):
        if zone_id is None:
            zone_id = self._get_zone_id(domain)
        record = {
            'type': record_type,
            'name': rr,
            'content': value,
            'ttl': ttl,
            'priority': priority,
            'proxied': proxied,
        }
        return self.cf.zones.dns_records.post(zone_id, data=record)

    def update_domain_record(self, domain, rr, record_type, value, record_id=None, ttl=300, priority=10, proxied=False,
                             zone_id=None):
        if zone_id is None:
            zone_id = self._get_zone_id(domain)
        if record_id is None:
            records = self.get_domain_records(domain, rr=rr, zone_id=zone_id)
            if len(records) == 0:
                raise 'record not exist for {}.{}'.format(rr, domain)
            if len(records) > 1:
                raise 'multiple records for {}.{}'.format(rr, domain)
            record_id = records[0].id
        record = {
            'type': record_type,
            'name': rr,
            'content': value,
            'ttl': ttl,
            'priority': priority,
            'proxied': proxied,
        }
        return self.cf.zones.dns_records.put(zone_id, record_id, data=record)

    def delete_domain_record(self, domain, rr, record_type=None, value=None, proxied=None, zone_id=None):
        if zone_id is None:
            zone_id = self._get_zone_id(domain)
        records = self.get_domain_records(domain, rr=rr, record_type=record_type, value=value, proxied=proxied,
                                          zone_id=zone_id)
        for record in records:
            return self.cf.zones.dns_records.delete(zone_id, record.id)
