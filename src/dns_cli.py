#!/usr/bin/env python
# coding=utf-8

from __future__ import print_function
from typing import Callable, Mapping

import sys
import yaml
from .namecheap_dns_ops import build_namecheap_dns_client_from_config
from .aliyun_dns_ops import build_aliyun_dns_client_from_config
from .cloudflare_dns_ops import build_cloudflare_dns_client_from_config
from .model import *
from .utils import remove_suffix


class DnsProvider:
    client = any
    record_parser = Callable[[dict], DnsRecord]

    def __init__(self, client: any,
                 record_parser: Callable[[dict], DnsRecord] = parse_dns_record_from_config):
        self.client = client
        self.record_parser = record_parser


client_factories = {
    'namecheap': build_namecheap_dns_client_from_config,
    'aliyun': build_aliyun_dns_client_from_config,
    'cloudflare': build_cloudflare_dns_client_from_config,
}

default_record_parser = parse_dns_record_from_config
record_parsers = {
    'cloudflare': parse_cloudflare_dns_record_from_config,
}


def load_namecheap_conf(path):
    with open(path) as fp:
        return yaml.load(fp, Loader=yaml.FullLoader)


def build_dns_clients(clients_conf) -> Mapping[str, DnsProvider]:
    clients_conf = clients_conf.get(CFG_KEY_CLIENTS)
    clients = {}
    for vendor, factory in client_factories.items():
        client_conf = clients_conf.get(vendor)
        if client_conf is not None:
            record_parser = record_parsers.get(vendor, default_record_parser)
            clients[vendor] = DnsProvider(client=factory(client_conf), record_parser=record_parser)
    return clients


def load_and_update_dns_config(cfg_path):
    dns_conf = load_namecheap_conf(cfg_path)
    clients = build_dns_clients(dns_conf)

    for config in dns_conf.get(CFG_KEY_DNS):
        domain = config.get(CFG_KEY_DNS_DOMAIN)
        client = clients[config.get(CFG_KEY_DNS_VENDOR)]

        online_records = client.client.get_domain_records(domain)
        for r in config.get(CFG_KEY_DNS_RECORDS):
            record = client.record_parser(r)
            matches_records = _find_matches_records(online_records, record.name, record.type)

            # create record if not exists
            while not matches_records or not _is_record_value_match(matches_records[0], record.type, record.value):
                print('try add record [{}] {}.{} -> {}'.format(record.type, record.name, domain, record.value))
                print(client.client.add_domain_record(domain, record))

                # delete records no longer needed
                for matches_record in matches_records:
                    if matches_record.value != record.value:
                        print('try delete old record [{}] {}.{} -> {}'
                              .format(record.type, record.name, domain, matches_record.value))
                        client.client.delete_domain_record(domain, matches_record)

                online_records = client.client.get_domain_records(domain)
                matches_records = _find_matches_records(online_records, record.name, record.type)
            print('status now [{}] {}.{} -> {}'.format(record.type, record.name, domain, record.value))

    print('Done.')


def show_online_config(cfg_path):
    namecheap_conf = load_namecheap_conf(cfg_path)
    clients = build_dns_clients(namecheap_conf)

    for config in namecheap_conf.get(CFG_KEY_DNS):
        domain = config.get(CFG_KEY_DNS_DOMAIN)
        client = clients[config.get(CFG_KEY_DNS_VENDOR)]
        online_records = client.client.get_domain_records(domain)

        for r in config.get(CFG_KEY_DNS_RECORDS):
            record = client.record_parser(r)
            _print_matches_records(online_records, domain, record.name, record.type)

    print('End.')


def _print_matches_records(records, domain, rr, record_type):
    matches_records = _find_matches_records(records, rr, record_type)
    if not matches_records:
        print('status now [{}] {}.{} -> nil'.format(record_type, rr, domain))

    for record in matches_records:
        print('status now [{}] {}.{} -> {} TTL: {}s'
              .format(record_type, rr, domain, record.value, record.ttl))


def _find_matches_records(records, rr, record_type):
    return [record for record in records if record.type == record_type and record.name == rr]


def _is_record_value_match(record, record_type, value):
    if record.value == value:
        return True
    if record_type == 'CNAME':
        return remove_suffix(record.value, '.') == remove_suffix(value, '.')
    return False


GUIDE_DOC = '''\
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
