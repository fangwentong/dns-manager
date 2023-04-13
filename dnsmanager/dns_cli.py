#!/usr/bin/env python
# coding=utf-8

from __future__ import print_function

import sys
from typing import Callable, Mapping, List, Set

import yaml

from dnsmanager.aliyun_dns_ops import build_aliyun_dns_client_from_config
from dnsmanager.cloudflare_dns_ops import build_cloudflare_dns_client_from_config
from dnsmanager.model import DnsRecord, CFG_KEY_CLIENTS, CFG_KEY_DNS, CFG_KEY_DNS_DOMAIN, CFG_KEY_DNS_VENDOR, \
    CFG_KEY_DNS_RECORDS
from dnsmanager.model import parse_dns_record_from_config, parse_namecheap_dns_record_from_config, \
    parse_cloudflare_dns_record_from_config
from dnsmanager.namecheap_dns_ops import build_namecheap_dns_client_from_config
from dnsmanager.utils import remove_suffix


class DnsProvider:
    client = any
    record_parser = Callable[[dict], List[DnsRecord]]

    def __init__(self, client: any,
                 record_parser: Callable[[dict], List[DnsRecord]] = parse_dns_record_from_config):
        self.client = client
        self.record_parser = record_parser


client_factories = {
    'namecheap': build_namecheap_dns_client_from_config,
    'aliyun': build_aliyun_dns_client_from_config,
    'cloudflare': build_cloudflare_dns_client_from_config,
}

default_record_parser = parse_dns_record_from_config
record_parsers = {
    'namecheap': parse_namecheap_dns_record_from_config,
    'cloudflare': parse_cloudflare_dns_record_from_config,
}


def load_dns_conf_from_file(path):
    with open(path) as fp:
        return yaml.safe_load(fp)


def build_dns_clients(clients_conf) -> Mapping[str, DnsProvider]:
    clients_conf = clients_conf.get(CFG_KEY_CLIENTS)
    clients = {}
    for vendor, factory in client_factories.items():
        client_conf = clients_conf.get(vendor)
        if client_conf:
            record_parser = record_parsers.get(vendor, default_record_parser)
            clients[vendor] = DnsProvider(client=factory(client_conf), record_parser=record_parser)
    return clients


def load_and_update_dns_config(cfg_path):
    dns_conf = load_dns_conf_from_file(cfg_path)
    clients = build_dns_clients(dns_conf)

    for config in dns_conf.get(CFG_KEY_DNS):
        domain = config.get(CFG_KEY_DNS_DOMAIN)
        client = clients[config.get(CFG_KEY_DNS_VENDOR)]

        remote_records = client.client.get_domain_records(domain)
        for r in config.get(CFG_KEY_DNS_RECORDS):
            local_records = client.record_parser(r)

            # create record if not exists
            remote_records = upsert_records(client, domain, remote_records, local_records)

            # delete record which record's value not present at config file
            remote_records = cleanup_staled_records(client, domain, remote_records, local_records)

    print('Done.')


def upsert_records(client, domain, remote_records, local_records):
    has_diff = False
    for local_record in local_records:
        matches_remote_records = _find_matches_records(remote_records, local_record.name, local_record.type)
        same_name_remote_records = _find_matches_records(remote_records, local_record.name)

        value_match_record = next(
            (r for r in matches_remote_records if _is_record_value_match_any(r, local_record.type, local_record.value)),
            None)

        if value_match_record is None:  # value not exist, create it
            for same_name_remote_record in same_name_remote_records:  # resolve conflict record first
                if has_conflict(same_name_remote_record, local_record):
                    print('try delete old record due to conflict {}'
                          .format(same_name_remote_record.sprint_with_domain(domain)))
                    client.client.delete_domain_record(domain, same_name_remote_record)
            print('try add record {}'.format(local_record.sprint_with_domain(domain)))
            # create domain record
            print(client.client.add_domain_record(domain, local_record))
            has_diff = True
        elif not value_match_record.equals(local_record):
            # value matches but other configuration not equals, such as ttl, priority.
            print('try update record {} => {}'.format(value_match_record.sprint_with_domain(domain),
                                                      local_record.sprint_with_domain(domain)))
            print(client.client.update_domain_record(domain, local_record))
            has_diff = True

        print('status now {}'.format(local_record.sprint_with_domain(domain)))

    return client.client.get_domain_records(domain) if has_diff else remote_records


def cleanup_staled_records(client, domain, remote_records, local_records):
    local_values = {r.value for r in local_records}
    has_diff = False
    for record in local_records:
        matches_remote_records = _find_matches_records(remote_records, record.name, record.type)
        for matches_remote_record in matches_remote_records:
            if _is_record_value_match_any(matches_remote_record, record.type, local_values):
                continue
            print('try delete old record {}'.format(matches_remote_record.sprint_with_domain(domain)))
            print(client.client.delete_domain_record(domain, matches_remote_record))
            has_diff = True

    return client.client.get_domain_records(domain) if has_diff else remote_records


def show_online_config(cfg_path):
    dns_conf = load_dns_conf_from_file(cfg_path)
    clients = build_dns_clients(dns_conf)

    for config in dns_conf.get(CFG_KEY_DNS):
        domain = config.get(CFG_KEY_DNS_DOMAIN)
        client = clients[config.get(CFG_KEY_DNS_VENDOR)]
        online_records = client.client.get_domain_records(domain)

        for r in config.get(CFG_KEY_DNS_RECORDS):
            record = client.record_parser(r)
            _print_matches_records(online_records, domain, record[0].name, record[0].type)

    print('End.')


def _print_matches_records(records, domain, rr, record_type):
    matches_records = _find_matches_records(records, rr, record_type)
    if not matches_records:
        print('status now [{}] {}.{} -> nil'.format(record_type, rr, domain))

    for record in matches_records:
        print('status now {}'.format(record.sprint_with_domain(domain)))


def has_conflict(old_record: DnsRecord, new_record: DnsRecord) -> bool:
    if new_record.type == 'CNAME':
        return old_record.type in ['CNAME', 'A', 'AAAA']
    elif new_record.type in ['A', 'AAAA']:
        return old_record.type == 'CNAME'
    return new_record.type == old_record.type and new_record.value == old_record.value


def _find_matches_records(records, rr, record_type=None) -> List[DnsRecord]:
    return [record for record in records if record.name == rr
            and (record_type is None or record.type == record_type)]


def _is_record_value_match_any(record: DnsRecord, record_type: str, values: Set[str]):
    if record.value in values:
        return True
    if record_type == 'CNAME':
        return any(remove_suffix(record.value, '.') == remove_suffix(value, '.') for value in values)
    return False


GUIDE_DOC = '''
Usage:
    dns-manager <command> [/path/to/dns/config]

Commands:
    status    show current dns status
    update    load dns config from local, flush local config to name server
'''


def main():
    params = sys.argv[1:]

    if len(params) < 2:
        print(GUIDE_DOC)
        return

    command = params[0]
    cfg_path = params[1]

    if command == 'update':
        load_and_update_dns_config(cfg_path)
    elif command == 'status':
        show_online_config(cfg_path)
    else:
        print('unknown command', command)


if __name__ == '__main__':
    main()
