from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_VENDORS = frozenset({"aliyun", "cloudflare", "namecheap"})
SUPPORTED_RECORD_TYPES = frozenset(
    {"A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA", "URL", "URL301", "FRAME", "ALIAS"}
)

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigValidationError(ValueError):
    """Raised when a DNS YAML configuration file fails schema validation."""


def expand_env_vars(value: Any, env: Mapping[str, str] | None = None) -> Any:
    """Recursively expand `${ENV_VAR}` placeholders in string values."""
    source = os.environ if env is None else env
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            if var_name not in source:
                raise ConfigValidationError(f"Environment variable '{var_name}' is not set")
            return source[var_name]

        return _ENV_VAR_PATTERN.sub(_replace, value)
    if isinstance(value, list):
        return [expand_env_vars(item, source) for item in value]
    if isinstance(value, dict):
        return {k: expand_env_vars(v, source) for k, v in value.items()}
    return value


def validate_dns_config(raw: Any) -> dict[str, Any]:
    """Validate DNS manager configuration structure and field types."""
    if not isinstance(raw, dict):
        raise ConfigValidationError("Root configuration must be a YAML mapping")

    clients = raw.get("clients")
    if not isinstance(clients, dict) or not clients:
        raise ConfigValidationError("'clients' must be a non-empty mapping")

    for vendor, client_cfg in clients.items():
        if vendor not in SUPPORTED_VENDORS:
            raise ConfigValidationError(
                f"Unsupported client vendor '{vendor}' (supported: {sorted(SUPPORTED_VENDORS)})"
            )
        if not isinstance(client_cfg, dict):
            raise ConfigValidationError(f"Client config for '{vendor}' must be a mapping")

    dns_entries = raw.get("dns")
    if not isinstance(dns_entries, list) or not dns_entries:
        raise ConfigValidationError("'dns' must be a non-empty list")

    for idx, entry in enumerate(dns_entries):
        prefix = f"dns[{idx}]"
        if not isinstance(entry, dict):
            raise ConfigValidationError(f"{prefix} must be a mapping")
        domain = entry.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise ConfigValidationError(f"{prefix}.domain must be a non-empty string")
        vendor = entry.get("vendor")
        if vendor not in SUPPORTED_VENDORS:
            raise ConfigValidationError(f"{prefix}.vendor '{vendor}' is unsupported")
        if vendor not in clients:
            raise ConfigValidationError(f"{prefix}.vendor '{vendor}' is not configured under 'clients'")
        records = entry.get("records")
        if not isinstance(records, list) or not records:
            raise ConfigValidationError(f"{prefix}.records must be a non-empty list")

        for r_idx, rec in enumerate(records):
            r_prefix = f"{prefix}.records[{r_idx}]"
            if not isinstance(rec, dict):
                raise ConfigValidationError(f"{r_prefix} must be a mapping")
            rr = rec.get("rr")
            if not isinstance(rr, str) or not rr.strip():
                raise ConfigValidationError(f"{r_prefix}.rr must be a non-empty string")
            rec_type = rec.get("type")
            if not isinstance(rec_type, str) or rec_type.upper() not in SUPPORTED_RECORD_TYPES:
                raise ConfigValidationError(f"{r_prefix}.type '{rec_type}' is unsupported")
            rec["type"] = rec_type.upper()
            val = rec.get("value")
            if isinstance(val, list):
                if not val or not all(isinstance(v, str) and v.strip() for v in val):
                    raise ConfigValidationError(f"{r_prefix}.value list must contain non-empty strings")
            elif not isinstance(val, str) or not val.strip():
                raise ConfigValidationError(f"{r_prefix}.value must be a non-empty string or list of strings")
            if "ttl" in rec and rec["ttl"] is not None:
                ttl = rec["ttl"]
                if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
                    raise ConfigValidationError(f"{r_prefix}.ttl must be a positive integer")
            if "proxied" in rec and rec["proxied"] is not None and not isinstance(rec["proxied"], bool):
                raise ConfigValidationError(f"{r_prefix}.proxied must be a boolean")
            if "priority" in rec and rec["priority"] is not None:
                prio = rec["priority"]
                if isinstance(prio, bool) or not isinstance(prio, int) or prio < 0:
                    raise ConfigValidationError(f"{r_prefix}.priority must be a non-negative integer")
            if "mx_pref" in rec and rec["mx_pref"] is not None:
                mx = rec["mx_pref"]
                if isinstance(mx, bool) or not isinstance(mx, int) or mx < 0:
                    raise ConfigValidationError(f"{r_prefix}.mx_pref must be a non-negative integer")

    return raw


def load_dns_config(path: str | Path, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Safely load a DNS YAML config, expand `${ENV_VAR}` in `clients`, and validate its schema."""
    with open(path, encoding="utf-8") as fp:
        raw = yaml.safe_load(fp)
    validated = validate_dns_config(raw)
    # Expand environment placeholders only inside `clients` so literal `${...}` in DNS TXT records stays untouched.
    validated["clients"] = expand_env_vars(validated["clients"], env=env)
    return validated
