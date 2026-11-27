from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from dns_manager.aliyun_dns_ops import AliyunDnsOps
from dns_manager.cloudflare_rest import CloudflareAPIError, CloudflareRestClient
from dns_manager.namecheap_dns_ops import NamecheapDnsOps


def _json_response(status_code: int, payload: dict, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = payload
    resp.text = json.dumps(payload)
    return resp


def test_aliyun_get_domain_records_default_args_and_exact_rr_filter():
    ops = AliyunDnsOps.__new__(AliyunDnsOps)
    ops.clt = MagicMock()
    ops.clt.do_action_with_exception.return_value = json.dumps(
        {
            "TotalCount": 2,
            "PageNumber": 1,
            "PageSize": 20,
            "DomainRecords": {
                "Record": [
                    {"RecordId": "1", "RR": "blog", "Type": "CNAME", "Value": "a.io", "TTL": 600},
                    {"RecordId": "2", "RR": "blog2", "Type": "CNAME", "Value": "b.io", "TTL": 600},
                ]
            },
        }
    )

    # Default call with only `domain` must not raise TypeError and must not send RRKeyWord!
    all_records = ops.get_domain_records("example.com")
    assert len(all_records) == 2
    sent_req = ops.clt.do_action_with_exception.call_args[0][0]
    assert sent_req.get_query_params().get("RRKeyWord") is None
    assert sent_req.get_query_params().get("TypeKeyWord") is None

    # Filtering rr="blog" must exclude fuzzy match "blog2".
    exact = ops.get_domain_records("example.com", rr="blog", record_type="cname")
    assert len(exact) == 1 and exact[0].name == "blog" and exact[0].id == "1"


def test_cloudflare_rest_pagination_and_429_retry():
    session = MagicMock()
    sleeps: list[float] = []
    session.request.side_effect = [
        _json_response(200, {"success": True, "result": [{"id": "z1", "name": "demo.com"}]}),
        _json_response(429, {"success": False, "errors": []}, headers={"Retry-After": "1"}),
        _json_response(
            200,
            {
                "success": True,
                "result": [
                    {
                        "id": "r1",
                        "name": "demo.com",
                        "type": "A",
                        "content": "1.1.1.1",
                        "ttl": 300,
                        "proxied": False,
                        "zone_id": "z1",
                    }
                ],
                "result_info": {"page": 1, "total_pages": 2},
            },
        ),
        _json_response(
            200,
            {
                "success": True,
                "result": [
                    {
                        "id": "r2",
                        "name": "www.demo.com",
                        "type": "CNAME",
                        "content": "demo.com",
                        "ttl": 1,
                        "proxied": True,
                        "zone_id": "z1",
                    }
                ],
                "result_info": {"page": 2, "total_pages": 2},
            },
        ),
    ]

    client = CloudflareRestClient(token="cf_tok", session=session, sleep_fn=sleeps.append)
    records = client.get_domain_records("demo.com")
    assert len(records) == 2
    assert records[0].name == "@" and records[0].value == "1.1.1.1"
    assert records[1].name == "www" and records[1].proxied is True
    assert sleeps == [1.0]


def test_cloudflare_rest_raises_on_success_false():
    session = MagicMock()
    session.request.return_value = _json_response(
        200,
        {"success": False, "errors": [{"code": 9109, "message": "Unauthorized to access requested resource"}]},
    )
    client = CloudflareRestClient(token="bad", session=session)
    with pytest.raises(CloudflareAPIError, match="9109"):
        client.get_zone_id("demo.com")


def test_namecheap_converts_string_ttl_and_mx_pref_and_preserves_raw():
    ops = NamecheapDnsOps.__new__(NamecheapDnsOps)
    ops.api = MagicMock()
    raw_hosts = [
        {"HostId": "10", "Name": "mail", "Type": "MX", "Address": "mx.demo.com", "TTL": "360", "MXPref": "10"},
        {"HostId": "11", "Name": "go", "Type": "URL301", "Address": "https://target.io", "TTL": "1800", "MXPref": ""},
    ]
    ops.api.domains_dns_getHosts.return_value = raw_hosts

    assert ops.get_raw_domain_records("demo.com") == raw_hosts
    parsed = ops.get_domain_records("demo.com")
    assert parsed[0].ttl == 360 and parsed[0].mx_pref == 10
    assert parsed[1].type == "URL301" and parsed[1].ttl == 1800 and parsed[1].mx_pref is None


def test_cli_update_dry_run_never_calls_write_methods(tmp_path, monkeypatch):
    from dns_manager import dns_cli
    from dns_manager.model import DnsRecord

    cfg = tmp_path / "dns.yml"
    cfg.write_text(
        """
clients:
  aliyun:
    id: k
    secret: s
dns:
  - domain: example.com
    vendor: aliyun
    records:
      - rr: www
        type: A
        value: 1.2.3.4
        ttl: 300
""",
        encoding="utf-8",
    )
    fake_client = MagicMock()
    fake_client.get_domain_records.return_value = [DnsRecord(id="1", name="www", type="A", value="9.9.9.9", ttl=300)]
    monkeypatch.setitem(dns_cli.readonly_client_factories, "aliyun", lambda _c: fake_client)

    dns_cli.main(["update", str(cfg), "--dry-run"])
    fake_client.get_domain_records.assert_called_once_with("example.com")
    fake_client.add_domain_record.assert_not_called()
    fake_client.update_domain_record.assert_not_called()
    fake_client.delete_domain_record.assert_not_called()
