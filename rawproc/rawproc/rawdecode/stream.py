"""Little-endian uint16 sensor stream reader (rawdecode v2 internals).

The v1 reader returned a bare 2-D list and only checked the byte count.  v2
keeps the same on-disk format but validates the stream against the declared
sensor geometry before a single sample is handed out, and reports exactly
what was wrong through :class:`StreamError`.
"""

from __future__ import annotations

import struct

from .errors import StreamError

_UINT16_MAX = 0xFFFF


def read_uint16_plane(path: str, height: int,
                      width: int) -> list[list[int]]:
    """Read a little-endian uint16 sensor dump into a ``height`` x ``width`` plane."""
    if width <= 0 or height <= 0:
        raise StreamError(
            f"sensor geometry must be positive, got {height}x{width}")

    expected_samples = height * width
    expected_bytes = expected_samples * 2
    try:
        with open(path, "rb") as fh:
            blob = fh.read()
    except OSError as exc:
        raise StreamError(f"cannot read raw stream {path}: {exc}") from exc

    if len(blob) != expected_bytes:
        raise StreamError(
            f"raw stream {path!r} is {len(blob)} bytes but metadata declares "
            f"{height}x{width} uint16 samples ({expected_bytes} bytes)")

    try:
        flat = struct.unpack("<%dH" % expected_samples, blob)
    except struct.error as exc:  # pragma: no cover - length was already checked
        raise StreamError(f"failed to decode uint16 stream: {exc}") from exc

    plane = [
        list(flat[r * width:(r + 1) * width])
        for r in range(height)
    ]
    # struct 'H' cannot exceed uint16 range, but keep the contract explicit:
    # the kernel treats sensor values as unsigned 16-bit and nothing else.
    if any(v > _UINT16_MAX for row in plane for v in row):  # pragma: no cover
        raise StreamError("decoded sample outside the uint16 range")
    return plane


def write_uint16_plane(path: str, plane: list[list[int]]) -> None:
    """Write a sensor plane as little-endian uint16 (synthesizer use)."""
    height = len(plane)
    width = len(plane[0]) if height else 0
    for row in plane:
        if len(row) != width:
            raise StreamError("cannot write a ragged sensor plane")
        if any(not (0 <= v <= _UINT16_MAX) for v in row):
            raise StreamError("sensor values must fit in uint16")
    with open(path, "wb") as fh:
        fh.write(struct.pack(
            "<%dH" % (height * width),
            *(v for row in plane for v in row),
        ))
