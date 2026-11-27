#!/usr/bin/env python

from __future__ import annotations

import functools
import logging
import re
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

_SENSITIVE_KEY_FRAGMENTS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "password",
    "auth",
    "access_key",
    "private_key",
)
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)(ApiKey|api_key|token|secret|X-Auth-Key)\s*([=:])\s*([^\s&,'\";]+)"),
    re.compile(r"(?i)(Bearer)\s+([^\s,'\";]+)"),
)


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def redact_text(text: str) -> str:
    redacted = text
    redacted = _SECRET_TEXT_PATTERNS[0].sub(r"\1\2***", redacted)
    redacted = _SECRET_TEXT_PATTERNS[1].sub(r"\1 ***", redacted)
    return redacted


def redact_for_log(value: Any, key_hint: str | None = None) -> Any:
    """Recursively mask sensitive fields (tokens/secrets/api keys) before logging."""
    if key_hint is not None and _is_sensitive_key(key_hint):
        return "***"
    if isinstance(value, dict):
        return {k: redact_for_log(v, key_hint=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_log(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def log_api_call(func):
    """Wrap an API method in try/except and log redacted inputs and exceptions on failure."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        class_name = args[0].__class__.__name__ if args else ""
        func_name = func.__name__
        try:
            return func(*args, **kwargs)
        except Exception as e:
            arg_details = [repr(redact_for_log(arg)) for arg in args[1:]]
            kwarg_details = [f"{k}={redact_for_log(v, key_hint=k)!r}" for k, v in kwargs.items()]
            all_args = ", ".join(arg_details + kwarg_details)

            logging.error(
                f"[{class_name}.{func_name}] API call failed.\n"
                f">> INPUT: ({all_args})\n"
                f">> EXCEPTION: {redact_text(str(e))}"
            )
            raise

    return wrapper


def remove_suffix(s: str, suffix: str) -> str:
    if suffix and s.endswith(suffix):
        return s[: -len(suffix)]
    return s
