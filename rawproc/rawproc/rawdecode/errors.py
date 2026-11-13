"""Exceptions raised by the versioned raw-decode dependency (rawdecode v2).

A decode failure is always explicit: missing levels, an out-of-sensor active
window or a truncated byte stream raise here instead of being papered over
with fallback numbers.
"""


class DecodeError(Exception):
    """Base class for every rawdecode failure."""


class StreamError(DecodeError):
    """The sensor byte stream cannot be read or does not match the metadata."""


class LevelError(DecodeError):
    """Black/white levels are missing, malformed or inconsistent."""


class WindowError(DecodeError):
    """The active-pixel window is missing or falls outside the sensor."""


class WhiteBalanceError(DecodeError):
    """The as-shot white-balance coefficients are malformed or non-positive."""
