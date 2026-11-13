"""Pure-Python 2D array helpers and EXIF-style geometry transforms.

The same transforms are applied to data planes and boolean masks so that
saturated / under-black markers survive rotation and mirroring.
"""

from __future__ import annotations

from typing import Sequence

Plane = list[list[float]]
Mask = list[list[bool]]


def crop(plane: Sequence[Sequence], y0: int, x0: int,
         height: int, width: int) -> list[list]:
    return [row[x0:x0 + width] for row in plane[y0:y0 + height]]


def transpose(plane: Sequence[Sequence]) -> list[list]:
    return [list(col) for col in zip(*plane)]


def flip_horizontal(plane: Sequence[Sequence]) -> list[list]:
    return [list(reversed(row)) for row in plane]


def flip_vertical(plane: Sequence[Sequence]) -> list[list]:
    return [list(row) for row in reversed(plane)]


# EXIF orientation -> geometry transform applied to the sensor crop.
# Transposes swap the axes; flips keep them.  Only 1..8 are valid.
def apply_orientation(plane: Sequence[Sequence], orientation: int) -> list[list]:
    table = {
        1: lambda p: [list(r) for r in p],
        2: flip_horizontal,
        3: lambda p: flip_vertical(flip_horizontal(p)),
        4: flip_vertical,
        5: lambda p: transpose(flip_vertical(p)),
        6: lambda p: flip_horizontal(transpose(p)),
        7: lambda p: transpose(flip_horizontal(p)),
        8: lambda p: flip_vertical(transpose(p)),
    }
    if orientation not in table:
        raise ValueError(f"orientation must be 1..8, got {orientation}")
    return table[orientation](plane)


def transform_cfa_origin(origin: tuple[int, int], orientation: int,
                         height: int, width: int) -> tuple[int, int]:
    """Track the R-pixel phase through the orientation transform.

    Coordinates are reduced modulo 2.  Flips are ``dim-1-x`` (not ``1-x``),
    so the frame's parity matters; transposes swap the axes.  The mapping
    matches :func:`apply_orientation` exactly and is verified against a
    geometric transform of the full index plane for every 2x2 origin,
    orientation and several odd/even frame sizes.
    """
    r, c = origin
    h, w = height, width
    if orientation == 1:
        return r, c
    if orientation == 2:        # horizontal flip
        return r, (w - 1 - c) % 2
    if orientation == 3:        # 180
        return (h - 1 - r) % 2, (w - 1 - c) % 2
    if orientation == 4:        # vertical flip
        return (h - 1 - r) % 2, c
    if orientation == 5:        # transpose after vertical flip
        return c, (h - 1 - r) % 2
    if orientation == 6:        # horizontal flip of transpose
        return c, (h - 1 - r) % 2
    if orientation == 7:        # transpose after horizontal flip
        return (w - 1 - c) % 2, r
    if orientation == 8:        # vertical flip of transpose
        return (w - 1 - c) % 2, r
    raise ValueError(f"orientation must be 1..8, got {orientation}")


def mask_any(mask: Sequence[Sequence[bool]]) -> bool:
    return any(any(row) for row in mask)


def count_true(mask: Sequence[Sequence[bool]]) -> int:
    return sum(1 for row in mask for v in row if v)
