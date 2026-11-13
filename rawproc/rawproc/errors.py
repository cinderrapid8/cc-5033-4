"""Exceptions raised by the raw development pipeline.

The GUI turns every :class:`RawDevError` into a visible user-facing
message instead of a crash traceback.
"""


class RawDevError(Exception):
    """Base class for all expected, user-reportable errors."""


class MetadataError(RawDevError):
    """The sidecar metadata is missing, malformed or inconsistent."""


class RawIOError(RawDevError):
    """The raw sample cannot be read (truncated, wrong dtype/endianness)."""


class UnsupportedLayoutError(RawDevError):
    """A CFA layout other than the single implemented one was requested."""
