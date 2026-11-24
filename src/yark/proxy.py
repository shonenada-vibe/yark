"""Resolve an optional HTTP proxy. Default is a direct connection.

Local VPNs / Clash often export HTTPS_PROXY. Volcengine and other mainland
hosts then go through that tunnel and stall or drop TLS. yark therefore
ignores those variables unless proxy mode is ``env`` or an explicit URL.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

_DIRECT = frozenset({"direct", "none", "off", "false", "0", "no", ""})
_ENV = frozenset({"env", "auto", "system", "true", "1", "yes"})


def proxy_for_url(url: str, mode: str = "direct") -> str | None:
    """Proxy URL to use for this request, or None to connect directly.

    ``mode`` is ``direct`` (ignore env proxies), ``env`` (HTTPS_PROXY / …),
    or an explicit proxy URL such as ``http://127.0.0.1:7890``.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    resolved = _resolve_mode(mode)
    if resolved in _DIRECT:
        return None
    if bypass_proxy(host):
        return None
    if resolved in _ENV:
        return _env_proxy(url)
    return resolved


def _resolve_mode(mode: str) -> str:
    raw = (mode or "direct").strip()
    return raw.lower() if "://" not in raw else raw


def _env_proxy(url: str) -> str | None:
    scheme = (urlparse(url).scheme or "").lower()
    if scheme in {"https", "wss"}:
        names = (
            "HTTPS_PROXY",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
            "HTTP_PROXY",
            "http_proxy",
        )
    else:
        names = (
            "HTTP_PROXY",
            "http_proxy",
            "ALL_PROXY",
            "all_proxy",
        )
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def bypass_proxy(host: str) -> bool:
    raw = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    host = host.lower().rstrip(".")
    if not host or not raw.strip():
        return False
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item == "*":
            return True
        item_host = item.split("/")[0].split(":")[0].lstrip(".")
        if not item_host:
            continue
        if host == item_host or host.endswith("." + item_host):
            return True
    return False


def redact_proxy(url: str) -> str:
    parsed = urlparse(url)
    if parsed.username is None and parsed.password is None:
        return url
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    netloc = f"***@{host}"
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )
