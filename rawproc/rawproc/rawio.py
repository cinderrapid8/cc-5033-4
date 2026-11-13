"""Minimal raw sensor dump I/O (little-endian uint16, no external libraries)."""

from __future__ import annotations

import struct

from .errors import RawIOError
from .metadata import RawMeta


def read_raw(meta: RawMeta) -> list[list[int]]:
    """Read the sensor dump into a ``height`` x ``width`` list of uint16."""
    expected = meta.width * meta.height
    try:
        with open(meta.raw_file, "rb") as fh:
            blob = fh.read()
    except OSError as exc:
        raise RawIOError(f"cannot read raw file {meta.raw_file}: {exc}") from exc

    if len(blob) != expected * 2:
        raise RawIOError(
            f"raw file size {len(blob)} bytes does not match "
            f"{meta.width}x{meta.height} uint16 samples "
            f"(expected {expected * 2} bytes)"
        )

    try:
        flat = struct.unpack("<%dH" % expected, blob)
    except struct.error as exc:
        raise RawIOError(f"failed to decode uint16 samples: {exc}") from exc

    return [list(flat[r * meta.width:(r + 1) * meta.width])
            for r in range(meta.height)]


def write_raw(path: str, plane: list[list[int]]) -> None:
    """Write a sensor plane as little-endian uint16 (used by the synthesizer)."""
    height = len(plane)
    width = len(plane[0]) if height else 0
    with open(path, "wb") as fh:
        fh.write(struct.pack(
            "<%dH" % (height * width),
            *(v for row in plane for v in row),
        ))
