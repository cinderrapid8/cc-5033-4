"""Bayer CFA phase, per-channel black subtraction and white normalization.

The Bayer pattern is never guessed from the frame dimensions: every pixel is
assigned a color channel from the explicit ``cfa_origin`` carried in the
metadata (after crop/orientation have moved it).
"""

from __future__ import annotations

from .arrayops import Plane, Mask
from .metadata import RawMeta


def build_index_plane(height: int, width: int,
                      cfa_origin: tuple[int, int]) -> list[list[int]]:
    """RGGB index plane (0=R, 1=G1, 2=G2, 3=B) for a given R-pixel origin."""
    orow, ocol = cfa_origin
    base = ((0, 1), (2, 3))
    out = [[0] * width for _ in range(height)]
    for r in range(height):
        for c in range(width):
            out[r][c] = base[(r - orow) % 2][(c - ocol) % 2]
    return out


def channel_name_plane(index_plane: list[list[int]],
                       names: tuple[str, ...]) -> list[list[str]]:
    return [[names[i] for i in row] for row in index_plane]


def correct(raw_plane: list[list[int]], index_plane: list[list[int]],
            meta: RawMeta) -> tuple[Plane, Mask, Mask]:
    """Black-subtract and white-normalize a mosaiced sensor plane.

    Returns ``(mosaic, under_black_mask, saturated_mask)`` where ``mosaic``
    holds linear normalized values per sensor pixel (clamped to [0, 1]) and
    both masks are computed from the *original integer* samples so the
    sensor's dynamic-range extremes stay flagged instead of being silently
    folded into an 8-bit value.
    """
    height = len(raw_plane)
    width = len(raw_plane[0])
    mosaic = [[0.0] * width for _ in range(height)]
    under = [[False] * width for _ in range(height)]
    saturated = [[False] * width for _ in range(height)]

    for r in range(height):
        for c in range(width):
            idx = index_plane[r][c]
            value = raw_plane[r][c]
            black = meta.black_for_index(idx)
            white = meta.white_for_index(idx)

            if value < black:
                under[r][c] = True
            if value >= white:
                saturated[r][c] = True

            norm = (value - black) / (white - black)
            if norm < 0.0:
                norm = 0.0
            elif norm > 1.0:
                norm = 1.0
            mosaic[r][c] = norm

    return mosaic, under, saturated


def per_channel_stats(raw_plane: list[list[int]],
                      index_plane: list[list[int]], meta: RawMeta
                      ) -> list[dict]:
    """Raw integer statistics per CFA channel, useful in the GUI."""
    stats = []
    for idx, name in enumerate(meta.channels):
        vals = [raw_plane[r][c]
                for r in range(len(raw_plane))
                for c in range(len(raw_plane[0]))
                if index_plane[r][c] == idx]
        stats.append({
            "channel": name,
            "count": len(vals),
            "min": min(vals),
            "max": max(vals),
            "mean": sum(vals) / len(vals),
            "black": meta.black_for_index(idx),
            "white": meta.white_for_index(idx),
        })
    return stats
