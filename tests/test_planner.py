from __future__ import annotations

import pytest

from dns_manager.model import (
    CloudflareDnsRecord,
    DnsRecord,
    NamecheapDnsRecord,
)
from dns_manager.planner import format_plan, plan_domain_changes


def test_planner_no_substring_match_bug():
    # Regression test: old code passed str to `in`, so "1.2.3" matched "1.2.3.4".
    desired = [DnsRecord(name="www", type="A", value="1.2.3.4", ttl=300)]
    online = [DnsRecord(id="old1", name="www", type="A", value="1.2.3", ttl=300)]
    plan = plan_domain_changes("example.com", "aliyun", desired, online)
    assert [(c.action, c.desired.value if c.desired else c.existing.value) for c in plan.changes] == [
        ("create", "1.2.3.4"),
        ("delete_stale", "1.2.3"),
    ]


def test_planner_multivalue_a_records_create_update_delete_stale():
    desired = [
        DnsRecord(name="*.wire", type="A", value="10.0.1.1", ttl=600),
        DnsRecord(name="*.wire", type="A", value="10.0.1.2", ttl=600),
        DnsRecord(name="*.wire", type="A", value="10.0.1.3", ttl=600),
    ]
    online = [
        DnsRecord(id="id1", name="*.wire", type="A", value="10.0.1.1", ttl=600),  # unchanged
        DnsRecord(id="id2", name="*.wire", type="A", value="10.0.1.2", ttl=300),  # TTL changed -> update with id2
        DnsRecord(id="id9", name="*.wire", type="A", value="10.0.9.9", ttl=600),  # stale -> delete
    ]
    plan = plan_domain_changes("example.com", "aliyun", desired, online)
    assert [(c.action, c.desired.value if c.desired else c.existing.value) for c in plan.changes] == [
        ("update", "10.0.1.2"),
        ("create", "10.0.1.3"),
        ("delete_stale", "10.0.9.9"),
    ]
    update_change = plan.changes[0]
    assert update_change.desired is not None and update_change.desired.id == "id2"


def test_planner_cname_trailing_dot_and_conflict_ordering():
    # Online has A record for blog; desired changes blog to CNAME.
    # Conflict MUST be deleted before CNAME is created (Cloudflare requirement).
    desired = [DnsRecord(name="blog", type="CNAME", value="user.gitlab.io.", ttl=300)]
    online = [
        DnsRecord(id="a1", name="blog", type="A", value="1.2.3.4", ttl=300),
        DnsRecord(id="u1", name="docs", type="TXT", value="v=spf1", ttl=300),
    ]
    plan = plan_domain_changes("example.com", "cloudflare", desired, online)
    assert [c.action for c in plan.changes] == ["delete_conflict", "create"]
    assert plan.changes[0].existing is not None and plan.changes[0].existing.id == "a1"
    assert len(plan.unmanaged_records) == 1 and plan.unmanaged_records[0].name == "docs"

    # CNAME with/without trailing dot matches identically (no-op).
    online_same = [DnsRecord(id="c1", name="blog", type="CNAME", value="user.gitlab.io", ttl=300)]
    noop = plan_domain_changes("example.com", "cloudflare", desired, online_same)
    assert not noop.has_changes


def test_planner_cloudflare_proxied_ignores_ttl_and_preserves_zone_id():
    desired = [CloudflareDnsRecord(name="blog", type="CNAME", value="target.io.", ttl=60, proxied=True)]
    online_same = [
        CloudflareDnsRecord(id="cf1", name="blog", type="CNAME", value="target.io", ttl=1, proxied=True, zone_id="z1")
    ]
    assert not plan_domain_changes("demo.com", "cloudflare", desired, online_same).has_changes

    online_unproxied = [
        CloudflareDnsRecord(
            id="cf1", name="blog", type="CNAME", value="target.io", ttl=300, proxied=False, zone_id="z1"
        )
    ]
    plan = plan_domain_changes("demo.com", "cloudflare", desired, online_unproxied)
    assert len(plan.changes) == 1 and plan.changes[0].action == "update"
    updated = plan.changes[0].desired
    assert isinstance(updated, CloudflareDnsRecord)
    assert updated.id == "cf1" and updated.zone_id == "z1" and updated.proxied is True


@pytest.mark.parametrize(
    ("online_ttl", "online_mx", "desired_mx", "expect_changes"),
    [
        ("360", "10", 10, False),  # Namecheap string TTL/MXPref normalized -> no-op
        ("360", "10", None, False),  # Unspecified mx_pref in config skips comparison
        ("600", "10", 10, True),
        ("360", "20", 10, True),
    ],
)
def test_planner_namecheap_string_ttl_and_mx_pref_normalization(online_ttl, online_mx, desired_mx, expect_changes):
    desired = [NamecheapDnsRecord(name="mail", type="MX", value="mail.example.com", ttl=360, mx_pref=desired_mx)]
    online = [
        NamecheapDnsRecord(
            id="h1", name="mail", type="MX", value="mail.example.com", ttl=online_ttl, mx_pref=online_mx
        )
    ]
    plan = plan_domain_changes("example.com", "namecheap", desired, online)
    assert plan.has_changes is expect_changes
    assert "example.com" in format_plan(plan)


def test_planner_rfc1034_cname_conflicts_with_txt_and_cname_value_change():
    # CNAME conflicts with TXT on same name, and CNAME value change deletes old CNAME before creating new one.
    desired = [DnsRecord(name="app", type="CNAME", value="new.target.io.", ttl=300)]
    online = [
        DnsRecord(id="t1", name="app", type="TXT", value="verify=1", ttl=300),
        DnsRecord(id="c1", name="app", type="CNAME", value="old.target.io", ttl=300),
    ]
    plan = plan_domain_changes("example.com", "cloudflare", desired, online)
    assert [c.action for c in plan.changes] == ["delete_conflict", "delete_conflict", "create"]
    assert {plan.changes[0].existing.id, plan.changes[1].existing.id} == {"t1", "c1"}


def test_planner_aaaa_ipv6_canonicalization_and_case_insensitive_name():
    desired = [DnsRecord(name="WWW", type="AAAA", value="2001:0db8:0000:0000::1", ttl=300)]
    online = [DnsRecord(id="v6", name="www", type="AAAA", value="2001:db8::1", ttl=300)]
    assert not plan_domain_changes("Example.COM", "cloudflare", desired, online).has_changes
