#!/usr/bin/env python
# coding=utf-8

from __future__ import print_function

import sys
import yaml
from .namecheap_dns_ops import NamecheapDnsOps
from .aliyun_dns_ops import AliyunDnsOps
from .cloudflare_dns_ops import CloudflareDnsOps
from .utils import remove_suffix


def load_namecheap_conf(path):
    with open(path) as fp:
        return yaml.load(fp, Loader=yaml.FullLoader)


def build_dns_clients(conf):
    conf = conf.get('accessKey')
    clients = {}

    namecheap_conf = conf.get('namecheap')
    if namecheap_conf is not None:
        api_key = namecheap_conf.get('api_key')
        username = namecheap_conf.get('username')
        ip = namecheap_conf.get('ip')
        sandbox = namecheap_conf.get('sandbox')
        debug = namecheap_conf.get('debug')
        clients['namecheap'] = NamecheapDnsOps(api_key, username, ip, sandbox, debug)

    aliyun_conf = conf.get('aliyun')
    if aliyun_conf is not None:
        key_id = aliyun_conf.get('id')
        key_secret = aliyun_conf.get('secret')
        clients['aliyun'] = AliyunDnsOps(key_id, key_secret)

    cloudflare_conf = conf.get('cloudflare')
    if cloudflare_conf is not None:
        # email=None, token=None, certtoken=None, debug=False
        email = cloudflare_conf.get('email')
        token = cloudflare_conf.get('token')
        certtoken = cloudflare_conf.get('certtoken')
        debug = cloudflare_conf.get('debug')
        clients['cloudflare'] = CloudflareDnsOps(email, token, certtoken, debug)

    return clients


def load_and_update_dns_config(cfg_path):
    dns_conf = load_namecheap_conf(cfg_path)
    clients = build_dns_clients(dns_conf)

    for config in dns_conf.get('dns'):
        domain = config.get('domain')
        client = clients[config.get('vendor')]
        online_records = client.get_domain_records(domain)
        for record in config.get('records'):
            rr = record.get('rr')
            record_type = record.get('type')
            value = record.get('value')
            ttl = record.get('ttl')

            matches_records = _find_matches_records(online_records, rr, record_type)

            # create record if not exists
            while not matches_records or not _is_record_value_match(matches_records[0], record_type, value):
                print('try add record [{}] {}.{} -> {}'.format(record_type, rr, domain, value))
                print(client.add_domain_record(domain, rr, record_type, value, ttl))

                # delete records no longer needed
                for matches_record in matches_records:
                    if matches_record.value != value:
                        print('try delete old record [{}] {}.{} -> {}'
                              .format(record_type, rr, domain, matches_record.value))
                        deleted = client.delete_domain_record(domain, rr, record_type, matches_record.value,
                                                              record_id=matches_record.id)
                        print('delete response {}'.format(deleted))

                online_records = client.get_domain_records(domain)
                matches_records = _find_matches_records(online_records, rr, record_type)
            print('status now [{}] {}.{} -> {}'.format(record_type, rr, domain, value))

    print('Done.')


def show_online_config(cfg_path):
    namecheap_conf = load_namecheap_conf(cfg_path)
    clients = build_dns_clients(namecheap_conf)

    for config in namecheap_conf.get('dns'):
        domain = config.get('domain')
        client = clients[config.get('vendor')]
        online_records = client.get_domain_records(domain)

        for record in config.get('records'):
            rr = record.get('rr')
            record_type = record.get('type')
            _print_matches_records(online_records, domain, rr, record_type)

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
