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
