import logging
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from namecheap import Api as NamecheapApi

from dns_manager.aliyun_dns_ops import AliyunDnsOps
from dns_manager.cloudflare_rest import (
    CloudflareAPIError,
    CloudflareRestClient,
    build_cloudflare_dns_client_from_config,
)
from dns_manager.dns_cli import load_and_update_dns_config
from dns_manager.executor import apply_domain_plan, is_zone_replace_provider
from dns_manager.model import (
    CloudflareDnsRecord,
    DnsRecord,
    NamecheapDnsRecord,
    parse_cloudflare_dns_record_from_config,
)
from dns_manager.namecheap_dns_ops import NamecheapDnsOps, NamecheapZoneSnapshot
from dns_manager.planner import DomainPlan, plan_domain_changes
from dns_manager.utils import log_api_call, redact_for_log, redact_text


def _fake_resp(status_code=200, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = json_data if json_data is not None else {"success": True, "result": {}}
    resp.text = str(json_data)
    return resp


def test_cloudflare_rest_write_crud_patch_and_429_retry():
    sleeps = []
    session = MagicMock()
    session.request.side_effect = [
        _fake_resp(200, {"success": True, "result": [{"id": "zone-1"}]}),
        _fake_resp(429, {"success": False}, headers={"Retry-After": "0.1"}),
        _fake_resp(200, {"success": True, "result": {"id": "rec-new"}}),
        _fake_resp(200, {"success": True, "result": {"id": "rec-1"}}),
        _fake_resp(200, {"success": True, "result": {"id": "rec-old"}}),
    ]
    client = CloudflareRestClient(token="cf-api-token", session=session, sleep_fn=sleeps.append)
    assert not is_zone_replace_provider(client)

    # 1. Create proxied apex A record with 429 retry -> ttl forced to 1, name = example.com
    add_res = client.add_domain_record(
        "example.com",
        CloudflareDnsRecord(name="@", type="A", value="1.2.3.4", ttl=600, proxied=True),
    )
    assert add_res == {"id": "rec-new"}
    assert sleeps == [0.1]
    method, url = session.request.call_args_list[2].args[:2]
    body = session.request.call_args_list[2].kwargs["json"]
    headers = session.request.call_args_list[2].kwargs["headers"]
    assert method == "POST"
    assert url.endswith("/zones/zone-1/dns_records")
    assert headers["Authorization"] == "Bearer cf-api-token"
    assert body == {"name": "example.com", "type": "A", "content": "1.2.3.4", "ttl": 1, "proxied": True}

    # 2. Update MX record uses PATCH (preserving comment/tags/settings) and explicit priority
    upd_res = client.update_domain_record(
        "example.com",
        CloudflareDnsRecord(
            id="rec-1",
            zone_id="zone-1",
            name="mail",
            type="MX",
            value="mx1.example.com",
            ttl=300,
            proxied=False,
            priority=10,
        ),
    )
    assert upd_res == {"id": "rec-1"}
    method, url = session.request.call_args_list[3].args[:2]
    body = session.request.call_args_list[3].kwargs["json"]
    assert method == "PATCH"
    assert url.endswith("/zones/zone-1/dns_records/rec-1")
    assert body == {
        "name": "mail.example.com",
        "type": "MX",
        "content": "mx1.example.com",
        "ttl": 300,
        "proxied": False,
        "priority": 10,
    }

    # 3. Delete record
    del_res = client.delete_domain_record(
        "example.com",
        CloudflareDnsRecord(id="rec-old", zone_id="zone-1", name="old", type="A", value="9.9.9.9"),
    )
    assert del_res == {"id": "rec-old"}
    method, url = session.request.call_args_list[4].args[:2]
    assert method == "DELETE"
    assert url.endswith("/zones/zone-1/dns_records/rec-old")

    # Missing record.id rejected before network call
    with pytest.raises(CloudflareAPIError, match="without record.id"):
        client.update_domain_record("example.com", CloudflareDnsRecord(name="www", type="A", value="1.2.3.4"))
    with pytest.raises(CloudflareAPIError, match="without record.id"):
        client.delete_domain_record("example.com", CloudflareDnsRecord(name="www", type="A", value="1.2.3.4"))


def test_cloudflare_proxied_omitted_preserves_existing_proxied_state(caplog):
    # Omitting 'proxied' in config yields proxied=None, never silently disabling proxy on an existing proxied record.
    parsed = parse_cloudflare_dns_record_from_config({"rr": "www", "type": "A", "value": "1.2.3.4", "ttl": 300})
    assert parsed[0].proxied is None

    existing = [
        CloudflareDnsRecord(id="r1", zone_id="z1", name="www", type="A", value="1.2.3.4", ttl=1, proxied=True),
    ]
    # Because existing is proxied=True and desired omits proxied, ttl=300 vs ttl=1 does not trigger a spurious diff.
    plan_noop = plan_domain_changes("example.com", "cloudflare", parsed, existing)
    assert not plan_noop.has_changes

    # When an update IS triggered (e.g. priority changed) while proxied is omitted, existing.proxied is inherited.
    existing_mx = [
        CloudflareDnsRecord(
            id="r2", zone_id="z1", name="www", type="A", value="1.2.3.4", ttl=1, proxied=True, priority=5
        ),
    ]
    desired_mx = parse_cloudflare_dns_record_from_config(
        {"rr": "www", "type": "A", "value": "1.2.3.4", "ttl": 300, "priority": 10}
    )
    plan_upd = plan_domain_changes("example.com", "cloudflare", desired_mx, existing_mx)
    assert len(plan_upd.changes) == 1
    assert plan_upd.changes[0].action == "update"
    assert plan_upd.changes[0].desired.proxied is True

    # Legacy certtoken/debug keys emit warning
    with caplog.at_level(logging.WARNING):
        build_cloudflare_dns_client_from_config({"token": "tok", "certtoken": "old", "debug": True})
    assert "certtoken" in caplog.text
    assert "debug" in caplog.text


def test_aliyun_update_sets_ttl_and_preserves_line_and_idempotency():
    ops = AliyunDnsOps.__new__(AliyunDnsOps)
    ops.clt = MagicMock()
    ops.clt.do_action_with_exception.return_value = '{"RecordId": "r-42"}'
    assert not is_zone_replace_provider(ops)

    online = [
        AliyunDnsOps._convert_to_dns_record(
            {"RecordId": "r-42", "RR": "www", "Type": "A", "Value": "1.2.3.4", "TTL": 600, "Line": "oversea"}
        )
    ]
    desired = [DnsRecord(name="www", type="A", value="1.2.3.4", ttl=900)]
    plan = plan_domain_changes("example.com", "aliyun", desired, online)
    assert len(plan.changes) == 1
    assert plan.changes[0].desired.line == "oversea"

    apply_domain_plan(ops, "example.com", plan, desired)
    req = ops.clt.do_action_with_exception.call_args.args[0]
    params = req.get_query_params()
    assert params["RecordId"] == "r-42"
    assert params["TTL"] == 900
    assert params["Line"] == "oversea"

    # Idempotency: re-planning after update produces zero changes.
    updated_online = [DnsRecord(id="r-42", name="www", type="A", value="1.2.3.4", ttl=900, line="oversea")]
    assert not plan_domain_changes("example.com", "aliyun", desired, updated_online).has_changes

    with pytest.raises(ValueError, match="without record.id"):
        ops.update_domain_record("example.com", DnsRecord(name="www", type="A", value="1.2.3.4", ttl=600))
    with pytest.raises(ValueError, match="without record.id"):
        ops.delete_domain_record("example.com", DnsRecord(name="www", type="A", value="1.2.3.4"))


def test_record_provider_executor_order_partial_failure_and_magicmock_dispatch(caplog):
    # A bare MagicMock must NOT accidentally match zone-replace mode.
    assert not is_zone_replace_provider(MagicMock())

    events = []

    class FakeRecordClient:
        def delete_domain_record(self, domain, record):
            events.append(("delete", record.id, record.name, record.type, record.value))

        def add_domain_record(self, domain, record):
            events.append(("add", record.name, record.type, record.value))

        def update_domain_record(self, domain, record):
            events.append(("update", record.id, record.name, record.type, record.value, record.ttl))

    online = [
        DnsRecord(id="id-cname", name="app", type="CNAME", value="old.target.com", ttl=300),
        DnsRecord(id="id-www-keep", name="www", type="A", value="1.1.1.1", ttl=600),
        DnsRecord(id="id-www-stale", name="www", type="A", value="2.2.2.2", ttl=300),
    ]
    desired = [
        DnsRecord(name="app", type="A", value="3.3.3.3", ttl=300),
        DnsRecord(name="www", type="A", value="1.1.1.1", ttl=300),
    ]
    plan = plan_domain_changes("example.com", "aliyun", desired, online)
    applied = apply_domain_plan(FakeRecordClient(), "example.com", plan, desired)
    assert applied == 4
    assert events == [
        ("delete", "id-cname", "app", "CNAME", "old.target.com"),
        ("add", "app", "A", "3.3.3.3"),
        ("update", "id-www-keep", "www", "A", "1.1.1.1", 300),
        ("delete", "id-www-stale", "www", "A", "2.2.2.2"),
    ]

    # Partial failure logs exact applied vs remaining count before re-raising.
    class FailingAddClient(FakeRecordClient):
        def add_domain_record(self, domain, record):
            raise RuntimeError("rate limit")

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="rate limit"):
        apply_domain_plan(FailingAddClient(), "example.com", plan, desired)
    assert "1/4 change(s) applied before error; 3 remaining" in caplog.text


def test_namecheap_xml_snapshot_email_type_and_numbered_sethosts_serialization():
    get_hosts_xml = ET.fromstring(
        """
        <ApiResponse xmlns="http://api.namecheap.com/xml.response" Status="OK">
          <CommandResponse Type="namecheap.domains.dns.getHosts">
            <DomainDNSGetHostsResult Domain="example.com" EmailType="MX" IsUsingOurDNS="true">
              <host HostId="101" Name="@" Type="URL301" Address="https://example.org"
                    MXPref="10" TTL="1800" AssociatedAppTitle="Redirect" IsActive="true" />
              <host HostId="102" Name="@" Type="MX" Address="mail.keep.org."
                    MXPref="20" TTL="1800" IsActive="true" />
              <host HostId="103" Name="www" Type="CNAME" Address="old.cdn.net."
                    MXPref="10" TTL="1800" IsActive="true" />
              <host HostId="104" Name="api" Type="A" Address="9.9.9.9"
                    MXPref="10" TTL="600" IsActive="true" />
            </DomainDNSGetHostsResult>
          </CommandResponse>
        </ApiResponse>
        """
    )

    ops = NamecheapDnsOps.__new__(NamecheapDnsOps)
    ops.api = MagicMock()
    ops.api._list_of_dictionaries_to_numbered_payload = NamecheapApi._list_of_dictionaries_to_numbered_payload
    ops.api._call.side_effect = [get_hosts_xml, ET.fromstring("<ApiResponse Status='OK'/>")]
    assert is_zone_replace_provider(ops)

    snapshot = ops.get_zone_snapshot("example.com")
    assert snapshot.email_type == "MX"
    assert snapshot.is_using_our_dns is True
    assert len(snapshot.raw_records) == 4

    online = ops.convert_raw_records(snapshot.raw_records)
    desired = [
        NamecheapDnsRecord(name="www", type="A", value="1.2.3.4", ttl=300),  # conflicts with www CNAME
        NamecheapDnsRecord(name="api", type="A", value="5.6.7.8", ttl=300),  # replaces api A
    ]
    plan = plan_domain_changes("example.com", "namecheap", desired, online)
    assert plan.unmanaged_indices == (0, 1)

    apply_domain_plan(ops, "example.com", plan, desired, zone_snapshot=snapshot)

    assert ops.api._call.call_count == 2
    cmd, payload = ops.api._call.call_args_list[1].args
    assert cmd == "namecheap.domains.dns.setHosts"
    assert payload["SLD"] == "example"
    assert payload["TLD"] == "com"
    assert payload["EmailType"] == "MX"

    # Verify exact numbered Namecheap query params (no HostId/IsActive/AssociatedAppTitle/MXPref='None' leaks!)
    assert payload["HostName1"] == "@"
    assert payload["RecordType1"] == "URL301"
    assert payload["Address1"] == "https://example.org"
    assert payload["TTL1"] == "1800"
    assert "MXPref1" not in payload
    assert "HostId1" not in payload
    assert "AssociatedAppTitle1" not in payload

    # Unmanaged MX record keeps MXPref
    assert payload["HostName2"] == "@"
    assert payload["RecordType2"] == "MX"
    assert payload["Address2"] == "mail.keep.org."
    assert payload["MXPref2"] == "20"

    # Managed A records omit MXPref
    assert payload["HostName3"] == "www"
    assert payload["RecordType3"] == "A"
    assert payload["Address3"] == "1.2.3.4"
    assert payload["TTL3"] == "300"
    assert "MXPref3" not in payload

    assert payload["HostName4"] == "api"
    assert payload["RecordType4"] == "A"
    assert payload["Address4"] == "5.6.7.8"
    assert payload["TTL4"] == "300"
    assert "None" not in payload.values()

    # Idempotency: re-planning against resulting zone state produces 0 changes.
    after_online = [
        NamecheapDnsRecord(id="201", name="@", type="URL301", value="https://example.org", ttl="1800"),
        NamecheapDnsRecord(id="202", name="@", type="MX", value="mail.keep.org.", ttl="1800", mx_pref="20"),
        NamecheapDnsRecord(id="203", name="www", type="A", value="1.2.3.4", ttl="300"),
        NamecheapDnsRecord(id="204", name="api", type="A", value="5.6.7.8", ttl="300"),
    ]
    assert not plan_domain_changes("example.com", "namecheap", desired, after_online).has_changes


def test_namecheap_guardrails_refuse_empty_zone_and_non_namecheap_dns():
    ops = NamecheapDnsOps.__new__(NamecheapDnsOps)
    ops.api = MagicMock()
    ops.api._list_of_dictionaries_to_numbered_payload = NamecheapApi._list_of_dictionaries_to_numbered_payload

    # 1. No changes -> never calls setHosts
    noop_plan = DomainPlan(domain="example.com", vendor="namecheap", changes=[], unmanaged_records=[])
    assert apply_domain_plan(ops, "example.com", noop_plan, [], zone_snapshot=NamecheapZoneSnapshot([])) == 0
    ops.api._call.assert_not_called()

    # 2. IsUsingOurDNS=false -> refuse setHosts!
    desired = [NamecheapDnsRecord(name="www", type="A", value="1.2.3.4", ttl=300)]
    non_nc_snapshot = NamecheapZoneSnapshot(
        raw_records=[{"HostId": "1", "Name": "@", "Type": "A", "Address": "9.9.9.9", "TTL": "1800"}],
        is_using_our_dns=False,
    )
    plan = plan_domain_changes(
        "example.com", "namecheap", desired, ops.convert_raw_records(non_nc_snapshot.raw_records)
    )
    with pytest.raises(RuntimeError, match="IsUsingOurDNS=false"):
        apply_domain_plan(ops, "example.com", plan, desired, zone_snapshot=non_nc_snapshot)
    ops.api._call.assert_not_called()

    # 3. Empty raw snapshot -> refused unless allow_empty_zone=True!
    empty_snapshot = NamecheapZoneSnapshot(raw_records=[], is_using_our_dns=True)
    empty_plan = plan_domain_changes("example.com", "namecheap", desired, [])
    with pytest.raises(RuntimeError, match="--allow-empty-zone"):
        apply_domain_plan(ops, "example.com", empty_plan, desired, zone_snapshot=empty_snapshot)
    ops.api._call.assert_not_called()

    # With allow_empty_zone=True -> proceeds cleanly
    apply_domain_plan(ops, "example.com", empty_plan, desired, zone_snapshot=empty_snapshot, allow_empty_zone=True)
    ops.api._call.assert_called_once()


def test_cli_update_end_to_end_mixed_providers(tmp_path, monkeypatch):
    cfg_file = tmp_path / "dns.yml"
    cfg_file.write_text(
        """
clients:
  cloudflare:
    token: cf-tok
  namecheap:
    username: u
    api_key: k
    ip: 127.0.0.1
    sandbox: true
    debug: false
dns:
  - domain: cf.example.com
    vendor: cloudflare
    records:
      - rr: www
        type: A
        value: 1.2.3.4
        ttl: 300
        proxied: false
  - domain: nc.example.com
    vendor: namecheap
    records:
      - rr: www
        type: A
        value: 5.6.7.8
        ttl: 300
""",
        encoding="utf-8",
    )

    cf_client = MagicMock(spec=CloudflareRestClient)
    cf_client.get_domain_records.return_value = []

    nc_ops = NamecheapDnsOps.__new__(NamecheapDnsOps)
    nc_ops.api = MagicMock()
    nc_ops.api._list_of_dictionaries_to_numbered_payload = NamecheapApi._list_of_dictionaries_to_numbered_payload
    nc_ops.api._call.side_effect = [
        ET.fromstring(
            """
            <ApiResponse Status="OK">
              <CommandResponse>
                <DomainDNSGetHostsResult Domain="nc.example.com" EmailType="FWD" IsUsingOurDNS="true">
                  <host HostId="1" Name="@" Type="URL" Address="https://nc.example.com" TTL="1800" />
                </DomainDNSGetHostsResult>
              </CommandResponse>
            </ApiResponse>
            """
        ),
        ET.fromstring("<ApiResponse Status='OK'/>"),
    ]

    monkeypatch.setattr(
        "dns_manager.dns_cli.build_dns_clients",
        lambda _conf: {
            "cloudflare": SimpleNamespace(
                client=cf_client,
                record_parser=lambda r: [
                    CloudflareDnsRecord(name=r["rr"], type=r["type"], value=r["value"], ttl=r["ttl"], proxied=False)
                ],
            ),
            "namecheap": SimpleNamespace(
                client=nc_ops,
                record_parser=lambda r: [
                    NamecheapDnsRecord(name=r["rr"], type=r["type"], value=r["value"], ttl=r["ttl"])
                ],
            ),
        },
    )

    plans = load_and_update_dns_config(str(cfg_file))
    assert len(plans) == 2
    cf_client.add_domain_record.assert_called_once()
    assert nc_ops.api._call.call_count == 2
    cmd, payload = nc_ops.api._call.call_args_list[1].args
    assert cmd == "namecheap.domains.dns.setHosts"
    assert payload["EmailType"] == "FWD"
    assert payload["RecordType1"] == "URL"
    assert payload["HostName2"] == "www"
    assert payload["Address2"] == "5.6.7.8"


def test_log_api_call_redacts_sensitive_inputs_and_exception_text(caplog):
    assert redact_for_log({"token": "secret123", "domain": "example.com", "record_key": "ok"}) == {
        "token": "***",
        "domain": "example.com",
        "record_key": "ok",
    }
    assert "supersecret" not in redact_text("GET https://api.namecheap.com?ApiKey=supersecret&UserName=u")
    assert "tok123" not in redact_text("Authorization: Bearer tok123")

    class DummyClient:
        @log_api_call
        def call(self, payload, api_key=None):
            raise RuntimeError("failed with ApiKey=leaked-key-123 and Bearer leaked-tok-456")

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        DummyClient().call({"access_secret": "topsecret", "domain": "a.com"}, api_key="key-999")

    assert "topsecret" not in caplog.text
    assert "key-999" not in caplog.text
    assert "leaked-key-123" not in caplog.text
    assert "leaked-tok-456" not in caplog.text
    assert "***" in caplog.text
