from __future__ import annotations

import time
from typing import Any

import requests

from .model import CloudflareDnsRecord
from .utils import log_api_call, remove_suffix

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareAPIError(RuntimeError):
    """Raised when the Cloudflare v4 REST API returns success=false or an HTTP error."""


class CloudflareRestClient:
    """Lightweight Cloudflare v4 REST API client built on requests.Session."""

    def __init__(
        self,
        *,
        token: str | None = None,
        email: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        session: requests.Session | None = None,
        base_url: str = CLOUDFLARE_API_BASE,
        sleep_fn=time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep_fn
        self.session = session if session is not None else requests.Session()
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if email and token:
            self._headers["X-Auth-Email"] = email
            self._headers["X-Auth-Key"] = token
        elif token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._zone_id_cache: dict[str, str] = {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            resp = self.session.request(
                method,
                url,
                headers=self._headers,
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
            if resp.status_code == 429 and attempt < self.max_retries:
                retry_after = resp.headers.get("Retry-After")
                delay: float | None = None
                if retry_after is not None:
                    try:
                        parsed = float(retry_after)
                        if parsed >= 0:
                            delay = parsed
                    except ValueError:
                        delay = None
                if delay is None:
                    delay = (2.0**attempt) * 0.5
                self._sleep(delay)
                continue
            try:
                payload = resp.json()
            except ValueError as exc:
                last_exc = CloudflareAPIError(f"Cloudflare API returned non-JSON ({resp.status_code}): {resp.text}")
                raise last_exc from exc
            if resp.status_code >= 400 or not payload.get("success", False):
                errors = payload.get("errors") or []
                msg = "; ".join(f"[{e.get('code')}] {e.get('message')}" for e in errors) or resp.text
                raise CloudflareAPIError(f"Cloudflare API error ({resp.status_code}) on {method} {path}: {msg}")
            return payload
        raise CloudflareAPIError(f"Cloudflare API rate-limited (429) on {method} {path}")

    @log_api_call
    def get_zone_id(self, domain: str) -> str:
        if domain in self._zone_id_cache:
            return self._zone_id_cache[domain]
        payload = self._request("GET", "/zones", params={"name": domain})
        zones = payload.get("result") or []
        if not zones:
            raise CloudflareAPIError(f"Zone not found for domain {domain}")
        zone_id = str(zones[0]["id"])
        self._zone_id_cache[domain] = zone_id
        return zone_id

    @log_api_call
    def get_domain_records(self, domain: str, record: CloudflareDnsRecord | None = None) -> list[CloudflareDnsRecord]:
        zone_id = record.zone_id if (record is not None and record.zone_id) else self.get_zone_id(domain)
        base_params: dict[str, Any] = {"match": "all", "per_page": 100}
        if record is not None:
            if record.name == "@":
                base_params["name"] = domain
            elif record.name:
                base_params["name"] = f"{record.name}.{domain}"
            if record.value:
                base_params["content"] = record.value
            if record.type:
                base_params["type"] = record.type

        page = 1
        results: list[CloudflareDnsRecord] = []
        while True:
            params = {**base_params, "page": page}
            payload = self._request("GET", f"/zones/{zone_id}/dns_records", params=params)
            items = payload.get("result") or []
            results.extend(self._convert_resp_to_dns_record(item, domain) for item in items)
            info = payload.get("result_info") or {}
            total_pages = int(info.get("total_pages", 1) or 1)
            if page >= total_pages or not items:
                break
            page += 1
        return results

    @staticmethod
    def _convert_resp_to_dns_record(dict_record: dict[str, Any], domain: str) -> CloudflareDnsRecord:
        norm_domain = domain.strip().lower()
        raw_name = str(dict_record["name"]).strip().lower()
        record_name = remove_suffix(raw_name, "." + norm_domain)
        if record_name == norm_domain:
            record_name = "@"
        return CloudflareDnsRecord(
            id=dict_record.get("id"),
            name=record_name,
            type=dict_record.get("type", ""),
            value=dict_record.get("content", ""),
            ttl=dict_record.get("ttl"),
            proxiable=dict_record.get("proxiable"),
            proxied=bool(dict_record.get("proxied", False)),
            priority=dict_record.get("priority"),
            zone_id=dict_record.get("zone_id"),
        )
