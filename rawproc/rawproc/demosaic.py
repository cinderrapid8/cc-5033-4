"""Bilinear Bayer demosaicing (RGGB family, phase taken from metadata).

No guessed patterns: the channel index plane produced by
:mod:`rawproc.cfa` drives every interpolation, so crop-origin and rotation
phase shifts are respected automatically.

Standard bilinear rules on the RGGB 2x2 repeat:

* at a pixel's own channel, keep its measured sample;
* a missing channel is the arithmetic mean of every same-channel pixel in
  the 3x3 neighborhood.  For interior red/blue sites those are the four
  diagonals and for green sites the four axial neighbors; at borders the
  available subset is used, so no output pixel is ever filled with zero
  merely because an offset fell outside the frame.
"""

from __future__ import annotations

from .arrayops import Plane

# CFA index -> output RGB component: 0=R, 1/2=G, 3=B
_TO_RGB = {0: 0, 1: 1, 2: 1, 3: 2}
_NEIGHBORS = tuple(
    (dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)
    if not (dr == 0 and dc == 0)
)


def _channel_index_map(cfa_origin: tuple[int, int]) -> dict:
    """Map (row%2, col%2) -> CFA index (0=R,1=G1,2=G2,3=B)."""
    orow, ocol = cfa_origin
    base = ((0, 1), (2, 3))
    return {
        (rr, cc): base[(rr - orow) % 2][(cc - ocol) % 2]
        for rr in (0, 1) for cc in (0, 1)
    }


def demosaic(mosaic: Plane, cfa_origin: tuple[int, int],
             index_plane: list[list[int]] | None = None
             ) -> tuple[Plane, Plane, Plane]:
    height = len(mosaic)
    width = len(mosaic[0])
    if index_plane is None:
        # Convenience for unit tests on canonical-origin planes.
        index_plane = [
            [_channel_index_map(cfa_origin)[(r % 2, c % 2)]
             for c in range(width)]
            for r in range(height)
        ]

    r_plane = [[0.0] * width for _ in range(height)]
    g_plane = [[0.0] * width for _ in range(height)]
    b_plane = [[0.0] * width for _ in range(height)]
    outs = (r_plane, g_plane, b_plane)

    def mean_matching(row: int, col: int, target_rgb: int) -> float:
        total, count = 0.0, 0
        for dr, dc in _NEIGHBORS:
            nr, nc = row + dr, col + dc
            if 0 <= nr < height and 0 <= nc < width and \
                    _TO_RGB[index_plane[nr][nc]] == target_rgb:
                total += mosaic[nr][nc]
                count += 1
        return total / count if count else 0.0

    for r in range(height):
        for c in range(width):
            own = _TO_RGB[index_plane[r][c]]
            outs[own][r][c] = mosaic[r][c]
            for ch in (0, 1, 2):
                if ch != own:
                    outs[ch][r][c] = mean_matching(r, c, ch)

    return r_plane, g_plane, b_plane
