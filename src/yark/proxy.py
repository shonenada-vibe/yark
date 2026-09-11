"""Honor HTTPS_PROXY / HTTP_PROXY / ALL_PROXY and NO_PROXY."""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse


def proxy_for_url(url: str) -> str | None:
    """Proxy URL to use for this request, or None to connect directly."""
    host = (urlparse(url).hostname or "").lower()
    if not host or bypass_proxy(host):
        return None
    scheme = (urlparse(url).scheme or "").lower()
    names: tuple[str, ...]
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
