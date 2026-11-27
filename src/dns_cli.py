#!/usr/bin/env python

import sys
from collections.abc import Callable, Mapping
from typing import Any

from .aliyun_dns_ops import build_aliyun_dns_client_from_config
from .cloudflare_dns_ops import build_cloudflare_dns_client_from_config
from .config_loader import load_dns_config
from .model import (
    CFG_KEY_CLIENTS,
    CFG_KEY_DNS,
    CFG_KEY_DNS_DOMAIN,
    CFG_KEY_DNS_RECORDS,
    CFG_KEY_DNS_VENDOR,
    DnsRecord,
    parse_cloudflare_dns_record_from_config,
    parse_dns_record_from_config,
    parse_namecheap_dns_record_from_config,
)
from .namecheap_dns_ops import build_namecheap_dns_client_from_config
from .utils import remove_suffix


class DnsProvider:
    client: Any
    record_parser: Callable[[dict], list[DnsRecord]]

    def __init__(
        self,
        client: Any,
        record_parser: Callable[[dict], list[DnsRecord]] = parse_dns_record_from_config,
    ):
        self.client = client
        self.record_parser = record_parser


client_factories = {
    "namecheap": build_namecheap_dns_client_from_config,
    "aliyun": build_aliyun_dns_client_from_config,
    "cloudflare": build_cloudflare_dns_client_from_config,
}

default_record_parser = parse_dns_record_from_config
record_parsers = {
    "namecheap": parse_namecheap_dns_record_from_config,
    "cloudflare": parse_cloudflare_dns_record_from_config,
}


def load_namecheap_conf(path):
    return load_dns_config(path)


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
            records = client.record_parser(r)
            values = [r.value for r in records]
            reserve_set = values.copy()

            # create record if not exists
            for record in records:
                matches_records = _find_matches_records(online_records, record.name, record.type)
                same_name_records = _find_matches_records(online_records, record.name)

                value_match_record = next(
                    (r for r in matches_records if _is_record_value_match_any(r, record.type, record.value)), None)

                if value_match_record is None:  # value not exist, create it
                    for same_name_record in same_name_records:  # resolve conflict record first
                        if has_conflict(same_name_record, record):
                            print(f'try delete old record due to conflict {same_name_record.sprint_with_domain(domain)}'
                                  )
                            client.client.delete_domain_record(domain, same_name_record)
                            if record.type == same_name_record.type:
                                reserve_set.append(same_name_record.value)
                    print(f'try add record {record.sprint_with_domain(domain)}')
                    print(client.client.add_domain_record(domain, record))
                elif not value_match_record.matches(record):
                    print(
                        f"try update record {value_match_record.sprint_with_domain(domain)} "
                        f"=> {record.sprint_with_domain(domain)}"
                    )
                    print(client.client.update_domain_record(domain, record))

                print(f'status now {record.sprint_with_domain(domain)}')

            # delete record which record's value not present at config file
            for record in records:
                matches_records = _find_matches_records(online_records, record.name, record.type)
                if any(not _is_record_value_match_any(r, record.type, values) for r in matches_records):
                    # delete records no longer needed
                    for matches_record in matches_records:
                        if matches_record.value not in reserve_set:
                            print(f'try delete old record {matches_record.sprint_with_domain(domain)}')
                            client.client.delete_domain_record(domain, matches_record)
                    online_records = client.client.get_domain_records(domain)

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
            _print_matches_records(online_records, domain, record[0].name, record[0].type)

    print('End.')


def _print_matches_records(records, domain, rr, record_type):
    matches_records = _find_matches_records(records, rr, record_type)
    if not matches_records:
        print(f'status now [{record_type}] {rr}.{domain} -> nil')

    for record in matches_records:
        print(f'status now {record.sprint_with_domain(domain)}')


def has_conflict(old_record: DnsRecord, new_record: DnsRecord) -> bool:
    if new_record.type == 'CNAME':
        return old_record.type in ['CNAME', 'A', 'AAAA']
    elif new_record.type in ['A', 'AAAA']:
        return old_record.type == 'CNAME'
    return new_record.type == old_record.type and new_record.value == old_record.value


def _find_matches_records(records, rr, record_type=None) -> list[DnsRecord]:
    return [record for record in records if record.name == rr
            and (record_type is None or record.type == record_type)]


def _is_record_value_match_any(record: DnsRecord, record_type: str, values: list[str]):
    if record.value in values:
        return True
    if record_type == 'CNAME':
        return any(remove_suffix(record.value, '.') == remove_suffix(value, '.') for value in values)
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
