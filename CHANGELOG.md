# Changelog

## 0.2.0

### Breaking Changes
- Removed the legacy `cloudflare<3.0` Python SDK dependency in favor of `CloudflareRestClient` (`requests.Session`).
  Legacy Cloudflare config options `certtoken` and `debug` are now ignored (with a warning).
- `NamecheapDnsOps` switched from per-record `addHost`/`delHost` to atomic zone-level `replace_domain_records`
  (`domains.dns.setHosts`). Refuses `setHosts` when `IsUsingOurDNS=false`, and refuses to overwrite a zone where
  `getHosts` returns 0 records unless `--allow-empty-zone` is explicitly passed.

### Highlights
- **Pure-function Planner & Executor**: Replaced the legacy imperative update loop with deterministic
  `plan_domain_changes` (`delete_conflict` → `create`/`update` → `delete_stale`) and `apply_domain_plan` with explicit
  `write_mode` dispatch and partial-failure logging.
- **Read-only `plan` and `update --dry-run`**: Inspect exact planned diffs with zero remote writes.
- **Direct Cloudflare v4 REST API**: Supports scoped API Tokens (`Bearer`) and legacy `X-Auth-Email`/`X-Auth-Key`,
  full pagination (`per_page=100`), `429 Retry-After` backoff, `PATCH` updates (preserving Cloudflare comments/tags/settings),
  and `proxied=None` inheritance when omitted in config.
- **Safe Namecheap Zone Replacement**: Preserves unmanaged records (`URL`/`URL301`/`FRAME`, etc.) using `DomainPlan`
  indices as a single source of truth, strips read-only `getHosts` attributes before `setHosts`, preserves zone-level
  `EmailType`, and omits `MXPref` on non-MX records.

### Bug Fixes
- Fixed substring value matching bug in record reconciliation (`1.2.3.4` vs `11.2.3.4`).
- Fixed RFC 1034 CNAME conflict detection and IPv6 / case-insensitive normalization.
- Fixed `AliyunDnsOps.update_domain_record` dropping `TTL` and `Line` updates, and `get_domain_records` substring RR matching.
- Fixed `NamecheapDnsOps` passing `'MXPref': 'None'` on non-MX records and raw `Name`/`Type` keys to `setHosts`.
- Fixed `yaml.load` unsafe deserialization (`yaml.safe_load`) and added schema validation with `${ENV_VAR}` expansion for `clients`.
- Redacted sensitive keys, kwargs, and exception secrets in `log_api_call` and warned when Namecheap `debug=True` is set.
