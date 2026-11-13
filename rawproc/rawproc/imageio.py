"""Self-contained PNG writer (8/16-bit, grayscale/RGB/RGBA) using zlib only.

No third-party imaging library is available in this environment, so the PNG
chunks are emitted directly.  The 16-bit path keeps the full processed
dynamic range; the 8-bit path is for previews and boolean masks only.
"""

from __future__ import annotations

import struct
import zlib

from .arrayops import Plane, Mask

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _encode(planes: list[Plane], bitdepth: int, alpha: Plane | None) -> bytes:
    height = len(planes[0])
    width = len(planes[0][0])
    n_ch = len(planes) + (1 if alpha is not None else 0)
    color_type = {1: 0, 3: 2, 4: 6}[n_ch]

    maxv = (1 << bitdepth) - 1
    row_bytes = width * n_ch * (bitdepth // 8)
    raw = bytearray()
    for r in range(height):
        raw.append(0)  # filter type 0 (none)
        for c in range(width):
            samples = [planes[ch][r][c] for ch in range(len(planes))]
            if alpha is not None:
                samples.append(alpha[r][c])
            for v in samples:
                iv = int(round(min(max(v, 0.0), 1.0) * maxv))
                if bitdepth == 16:
                    raw.append((iv >> 8) & 0xFF)
                raw.append(iv & 0xFF)
    assert len(raw) == height * (1 + row_bytes)

    ihdr = struct.pack(
        ">IIBBBBB", width, height, bitdepth, color_type, 0, 0, 0
    )
    return (
        _SIGNATURE
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def png_bytes(planes: list[Plane], bitdepth: int = 8,
              alpha: Plane | None = None) -> bytes:
    if bitdepth not in (8, 16):
        raise ValueError("bitdepth must be 8 or 16")
    return _encode(planes, bitdepth, alpha)


def write_png(path: str, planes: list[Plane], bitdepth: int = 8,
              alpha: Plane | None = None) -> None:
    with open(path, "wb") as fh:
        fh.write(png_bytes(planes, bitdepth, alpha))


def write_mask_png(path: str, mask: Mask) -> None:
    """Save a boolean mask as an 8-bit grayscale PNG (255 = flagged)."""
    plane = [[255.0 if v else 0.0 for v in row] for row in mask]
    write_png(path, [plane], bitdepth=8)


def mask_overlay(r: Plane, g: Plane, b: Plane, saturated: Mask,
                 under: Mask) -> list[Plane]:
    """Tint flagged pixels on an 8-bit preview: red = saturated, blue = under."""
    ro, go, bo = [], [], []
    for i, row in enumerate(r):
        rr, gg, bb = [], [], []
        for j, _ in enumerate(row):
            if saturated[i][j]:
                rr.append(1.0); gg.append(0.0); bb.append(0.0)
            elif under[i][j]:
                rr.append(0.0); gg.append(0.4); bb.append(1.0)
            else:
                rr.append(r[i][j]); gg.append(g[i][j]); bb.append(b[i][j])
        ro.append(rr); go.append(gg); bo.append(bb)
    return [ro, go, bo]
