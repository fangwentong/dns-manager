from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dns_manager.config_loader import (
    ConfigValidationError,
    expand_env_vars,
    load_dns_config,
    validate_dns_config,
)


def test_load_sample_config_succeeds():
    sample = Path(__file__).resolve().parent.parent / "conf" / "dns_sample.yml"
    cfg = load_dns_config(sample)
    assert "clients" in cfg and cfg["clients"]
    assert "dns" in cfg and len(cfg["dns"]) >= 1


def test_load_dns_config_expands_clients_only_and_normalizes_type(tmp_path: Path):
    cfg_file = tmp_path / "dns.yml"
    cfg_file.write_text(
        """
clients:
  cloudflare:
    token: "${CF_TOKEN}"
dns:
  - domain: example.com
    vendor: cloudflare
    records:
      - rr: "@"
        type: txt
        value: "literal-${DO_NOT_EXPAND}"
      - rr: go
        type: URL301
        value: "https://example.org"
""",
        encoding="utf-8",
    )
    cfg = load_dns_config(cfg_file, env={"CF_TOKEN": "tok_123"})
    assert cfg["clients"]["cloudflare"]["token"] == "tok_123"
    assert cfg["dns"][0]["records"][0]["type"] == "TXT"
    assert cfg["dns"][0]["records"][0]["value"] == "literal-${DO_NOT_EXPAND}"
    assert cfg["dns"][0]["records"][1]["type"] == "URL301"


def test_expand_env_vars_missing_raises():
    with pytest.raises(ConfigValidationError, match="MISSING_SECRET"):
        expand_env_vars({"token": "${MISSING_SECRET}"}, env={})


@pytest.mark.parametrize(
    ("bad_cfg", "match"),
    [
        ([], "Root configuration"),
        ({"clients": {}, "dns": []}, "'clients'"),
        ({"clients": {"unknown": {}}, "dns": []}, "Unsupported client vendor"),
        ({"clients": {"aliyun": {}}, "dns": []}, "'dns'"),
        (
            {
                "clients": {"aliyun": {}},
                "dns": [
                    {
                        "domain": "a.com",
                        "vendor": "cloudflare",
                        "records": [{"rr": "@", "type": "A", "value": "1.1.1.1"}],
                    }
                ],
            },
            "not configured under 'clients'",
        ),
        (
            {
                "clients": {"aliyun": {}},
                "dns": [
                    {
                        "domain": "a.com",
                        "vendor": "aliyun",
                        "records": [{"rr": "@", "type": "BOGUS", "value": "1.1.1.1"}],
                    }
                ],
            },
            "unsupported",
        ),
        (
            {
                "clients": {"aliyun": {}},
                "dns": [
                    {
                        "domain": "a.com",
                        "vendor": "aliyun",
                        "records": [{"rr": "@", "type": "A", "value": []}],
                    }
                ],
            },
            "non-empty strings",
        ),
        (
            {
                "clients": {"aliyun": {}},
                "dns": [
                    {
                        "domain": "a.com",
                        "vendor": "aliyun",
                        "records": [{"rr": "@", "type": "A", "value": "1.1.1.1", "ttl": -10}],
                    }
                ],
            },
            "positive integer",
        ),
        (
            {
                "clients": {"cloudflare": {}},
                "dns": [
                    {
                        "domain": "a.com",
                        "vendor": "cloudflare",
                        "records": [{"rr": "@", "type": "A", "value": "1.1.1.1", "proxied": "yes"}],
                    }
                ],
            },
            "boolean",
        ),
        (
            {
                "clients": {"cloudflare": {}},
                "dns": [
                    {
                        "domain": "a.com",
                        "vendor": "cloudflare",
                        "records": [{"rr": "@", "type": "MX", "value": "mail.a.com", "priority": -1}],
                    }
                ],
            },
            "non-negative integer",
        ),
        (
            {
                "clients": {"namecheap": {}},
                "dns": [
                    {
                        "domain": "a.com",
                        "vendor": "namecheap",
                        "records": [{"rr": "@", "type": "MX", "value": "mail.a.com", "mx_pref": True}],
                    }
                ],
            },
            "non-negative integer",
        ),
    ],
)
def test_validate_dns_config_rejects_invalid_inputs(bad_cfg, match):
    with pytest.raises(ConfigValidationError, match=match):
        validate_dns_config(bad_cfg)


def test_yaml_safe_load_blocks_arbitrary_tags(tmp_path: Path):
    evil = tmp_path / "evil.yml"
    evil.write_text("!!python/object/apply:os.system ['echo pwned']\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        load_dns_config(evil)
