import re


class YarkError(Exception):
    """Base error for yark."""


class ConfigError(YarkError):
    """Missing or invalid configuration."""


class AuthError(YarkError):
    """Volcengine authentication failed."""


class SttError(YarkError):
    """Streaming ASR protocol or server error."""


class MacPermissionError(YarkError):
    """macOS microphone or accessibility permission is missing."""


_ASR_CODE = re.compile(r"code=(-?\d+)")


def format_hud_error(exc: BaseException, *, action: str | None = None) -> str:
    """One-line message for the on-screen HUD."""
    detail = _hud_error_detail(exc)
    if action:
        title = action[0].upper() + action[1:] if action else action
        return f"{title} failed · {detail}" if detail else f"{title} failed"
    return detail


def _hud_error_detail(exc: BaseException) -> str:
    if isinstance(exc, AuthError):
        return "Volcengine authentication failed"
    if isinstance(exc, ConfigError):
        return _clip(str(exc) or "Invalid config")
    if isinstance(exc, MacPermissionError):
        return _clip(str(exc) or "Permission needed")
    text = " ".join(str(exc).split())
    lower = text.lower()
    if isinstance(exc, SttError):
        if "401" in text or "403" in text or "unauthorized" in lower:
            return "Volcengine authentication failed"
        if "timed out" in lower:
            return "Speech recognition timed out"
        if "cannot reach" in lower:
            return "Cannot reach Volcengine"
        if "handshake" in lower:
            return "Cannot connect to Volcengine"
        match = _ASR_CODE.search(text)
        if match:
            return f"Speech recognition error {match.group(1)}"
        return _clip(text) or "Speech recognition failed"
    if text.startswith("LLM HTTP"):
        status = text.split(":", 1)[0].strip()
        return _clip(status, 40)
    if isinstance(exc, TimeoutError) or "timed out" in lower:
        return "Request timed out"
    return _clip(text) or exc.__class__.__name__


def _clip(text: str, limit: int = 72) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)].rstrip() + "…"
