#!/usr/bin/env python

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from typing import Any

from .aliyun_dns_ops import build_aliyun_dns_client_from_config
from .cloudflare_rest import build_cloudflare_dns_client_from_config
from .config_loader import load_dns_config
from .executor import apply_domain_plan, is_zone_replace_provider
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
from .namecheap_dns_ops import NamecheapZoneSnapshot, build_namecheap_dns_client_from_config
from .planner import DomainPlan, format_plan, plan_domain_changes


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


def build_dns_clients(clients_conf: dict[str, Any]) -> Mapping[str, DnsProvider]:
    clients_cfg = clients_conf.get(CFG_KEY_CLIENTS) or {}
    clients: dict[str, DnsProvider] = {}
    for vendor, factory in client_factories.items():
        client_conf = clients_cfg.get(vendor)
        if client_conf is not None:
            record_parser = record_parsers.get(vendor, default_record_parser)
            clients[vendor] = DnsProvider(client=factory(client_conf), record_parser=record_parser)
    return clients


def _get_provider(clients: Mapping[str, DnsProvider], vendor: str, domain: str) -> DnsProvider:
    if vendor not in clients:
        raise ValueError(f"Vendor '{vendor}' required for domain '{domain}' is not configured under 'clients'")
    return clients[vendor]


def _fetch_online_state(provider: DnsProvider, domain: str) -> tuple[list[DnsRecord], NamecheapZoneSnapshot | None]:
    if is_zone_replace_provider(provider.client):
        snapshot = provider.client.get_zone_snapshot(domain)
        return provider.client.convert_raw_records(snapshot.raw_records), snapshot
    return provider.client.get_domain_records(domain), None


def _parse_desired_records(provider: DnsProvider, entry: dict[str, Any]) -> list[DnsRecord]:
    desired_records: list[DnsRecord] = []
    for raw_rec in entry.get(CFG_KEY_DNS_RECORDS, []):
        desired_records.extend(provider.record_parser(raw_rec))
    return desired_records


def plan_dns_config(cfg_path: str) -> list[DomainPlan]:
    """Read-only diff planning across all configured domains (no writes performed)."""
    dns_conf = load_dns_config(cfg_path)
    clients = build_dns_clients(dns_conf)
    plans: list[DomainPlan] = []

    for entry in dns_conf.get(CFG_KEY_DNS, []):
        domain = entry[CFG_KEY_DNS_DOMAIN]
        vendor = entry[CFG_KEY_DNS_VENDOR]
        provider = _get_provider(clients, vendor, domain)
        online_records, _ = _fetch_online_state(provider, domain)
        desired_records = _parse_desired_records(provider, entry)
        plan = plan_domain_changes(domain, vendor, desired_records, online_records)
        plans.append(plan)
        print(format_plan(plan))

    return plans


def load_and_update_dns_config(cfg_path: str, *, allow_empty_zone: bool = False) -> list[DomainPlan]:
    """Plan and apply DNS changes across all configured domains."""
    dns_conf = load_dns_config(cfg_path)
    clients = build_dns_clients(dns_conf)
    plans: list[DomainPlan] = []

    for entry in dns_conf.get(CFG_KEY_DNS, []):
        domain = entry[CFG_KEY_DNS_DOMAIN]
        vendor = entry[CFG_KEY_DNS_VENDOR]
        provider = _get_provider(clients, vendor, domain)
        online_records, snapshot = _fetch_online_state(provider, domain)
        desired_records = _parse_desired_records(provider, entry)
        plan = plan_domain_changes(domain, vendor, desired_records, online_records)
        plans.append(plan)
        print(format_plan(plan))
        apply_domain_plan(
            provider.client,
            domain,
            plan,
            desired_records,
            zone_snapshot=snapshot,
            allow_empty_zone=allow_empty_zone,
        )

    print("Done.")
    return plans


def show_online_config(cfg_path: str) -> None:
    dns_conf = load_dns_config(cfg_path)
    clients = build_dns_clients(dns_conf)

    for entry in dns_conf.get(CFG_KEY_DNS, []):
        domain = entry[CFG_KEY_DNS_DOMAIN]
        vendor = entry[CFG_KEY_DNS_VENDOR]
        provider = _get_provider(clients, vendor, domain)
        online_records, _ = _fetch_online_state(provider, domain)

        for r in entry.get(CFG_KEY_DNS_RECORDS, []):
            parsed = provider.record_parser(r)
            _print_matches_records(online_records, domain, parsed[0].name, parsed[0].type)

    print("End.")


def _print_matches_records(records: list[DnsRecord], domain: str, rr: str, record_type: str) -> None:
    matches_records = [record for record in records if record.name == rr and record.type == record_type]
    if not matches_records:
        print(f"status now [{record_type}] {rr}.{domain} -> nil")

    for record in matches_records:
        print(f"status now {record.sprint_with_domain(domain)}")


GUIDE_DOC = """\
Usage:
    dns-manager <command> [/path/to/dns/config] [--dry-run] [--allow-empty-zone]

Commands:
    status    show current dns status
    plan      show planned dns changes without modifying remote records (read-only)
    update    load dns config from local, flush local config to name server
              (--dry-run: plan only; --allow-empty-zone: allow Namecheap write on 0 existing hosts)
"""


def main(argv: list[str] | None = None) -> None:
    params = sys.argv[1:] if argv is None else list(argv)
    dry_run = "--dry-run" in params
    allow_empty_zone = "--allow-empty-zone" in params
    params = [p for p in params if p not in ("--dry-run", "--allow-empty-zone")]

    if len(params) < 2:
        print(GUIDE_DOC)
        return

    command = params[0]
    cfg_path = params[1]

    if command == "plan" or (command == "update" and dry_run):
        plan_dns_config(cfg_path)
    elif command == "update":
        load_and_update_dns_config(cfg_path, allow_empty_zone=allow_empty_zone)
    elif command == "status":
        show_online_config(cfg_path)
    else:
        print("unknown command", command)


if __name__ == "__main__":
    main()
