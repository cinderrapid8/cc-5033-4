"""Legacy v1 raw I/O surface, kept as a thin compatibility shim.

The v1 contract was two functions returning bare pixel planes.  As of the
rawdecode v2 upgrade both are thin wrappers over the versioned decoder; the
shim exists so older callers and the golden-reference migration script keep
running while the kernel itself goes through :mod:`rawproc.raw_adapter`.

Contract versions:
  * v1 (``rawio``, LEGACY_API_VERSION 1.0.0): bare list-of-lists, loose meta.
  * v2 (``rawdecode`` 2.0.0): structured ``RawFrame`` with explicit levels,
    active-pixel window and as-shot white-balance coefficients.
"""

from __future__ import annotations

from .errors import RawIOError
from .metadata import RawMeta
from .rawdecode import (
    DECODER_VERSION,
    LEGACY_API_VERSION,
    write_uint16_plane,
)
from .rawdecode.stream import read_uint16_plane

__all__ = ["read_raw", "write_raw", "API_VERSION", "DECODER_VERSION"]

#: Contract version of this legacy surface.
API_VERSION = LEGACY_API_VERSION


def read_raw(meta: RawMeta) -> list[list[int]]:
    """v1 entry point: read the sensor plane exactly as the v2 decoder would.

    Geometry/type validation is performed by the v2 stream reader; the
    metadata-level contracts (levels, window, WB) are enforced when a full
    frame is decoded through the adapter, not on this low-level path.
    """
    try:
        return read_uint16_plane(meta.raw_file, meta.height, meta.width)
    except Exception as exc:  # rawdecode errors are all DecodeError subclasses
        raise RawIOError(
            f"[rawdecode {DECODER_VERSION}] {exc}") from exc


def write_raw(path: str, plane: list[list[int]]) -> None:
    """Write a little-endian uint16 sensor plane (synthesizer use)."""
    write_uint16_plane(path, plane)
