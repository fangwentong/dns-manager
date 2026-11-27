# DNS Manager

DNS Manager is a Python command-line tool for declarative DNS record management across multiple vendors (Cloudflare, Alibaba Cloud / Aliyun, and Namecheap).

## Install

Requires Python 3.10+.

```bash
pip install git+https://github.com/fangwentong/dns-manager.git
```

## Usage

```bash
dns-manager <command> /path/to/dns.yml [--dry-run]
```

### Commands

- `status` — show current remote DNS records for all managed `(rr, type)` entries
- `plan` — compute and print the exact diff (`DELETE conflict` → `CREATE`/`UPDATE` → `DELETE stale`) without modifying remote records
- `update` — plan and apply changes to the DNS provider (pass `--dry-run` to behave identically to `plan`)

```bash
$ dns-manager plan conf/dns_sample.yml
=== example.com (cloudflare) ===
  + CREATE: [A] www.example.com -> 93.184.216.34 TTL 300
  (1 change(s), 2 unmanaged record(s) preserved)
```

### Configuration File

See [conf/dns_sample.yml](conf/dns_sample.yml) for a full YAML example.

- Credentials under `clients` support `${ENV_VAR}` interpolation (missing env vars fail fast before any API call).
- **Cloudflare** supports scoped API Tokens (`token` only, sent as `Authorization: Bearer <token>`) as well as legacy Global API Keys (`email` + `token`, sent via `X-Auth-Email` / `X-Auth-Key`).
- **Namecheap** uses zone-level `domains.dns.setHosts` replacement while preserving all unmanaged records (including `URL`, `URL301`, `FRAME`, `SRV`, etc.) verbatim from `getHosts`.

### Supported DNS Vendors

- Cloudflare (direct v4 REST API via `requests`)
- Alibaba Cloud (Aliyun DNS)
- Namecheap

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest -v
```

## License

This program is licensed under the MIT License. See [LICENSE](LICENSE) for details.
