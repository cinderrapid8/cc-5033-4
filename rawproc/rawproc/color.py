"""Independent color steps: white balance and display transfer.

Both operate on the linear demosaiced image and are kept as separate,
explicit stages so the saved linear result never has display encoding baked
into it.
"""

from __future__ import annotations

from .arrayops import Plane


def gray_world_gains(r: Plane, g: Plane, b: Plane) -> tuple[float, float, float]:
    """Per-channel means normalized so the green gain is 1.0."""
    means = []
    for plane in (r, g, b):
        vals = [v for row in plane for v in row]
        means.append(sum(vals) / len(vals))
    mr, mg, mb = means
    if mr <= 0.0 or mg <= 0.0 or mb <= 0.0:
        return 1.0, 1.0, 1.0
    return mg / mr, 1.0, mg / mb


def apply_white_balance(r: Plane, g: Plane, b: Plane,
                        gains: tuple[float, float, float]
                        ) -> tuple[Plane, Plane, Plane]:
    gr, gg, gb = gains
    if gr <= 0 or gg <= 0 or gb <= 0:
        raise ValueError("white-balance gains must be positive")
    r2 = [[v * gr for v in row] for row in r]
    g2 = [[v * gg for v in row] for row in g]
    b2 = [[v * gb for v in row] for row in b]
    return r2, g2, b2


def srgb_encoded(r: Plane, g: Plane, b: Plane
                 ) -> tuple[Plane, Plane, Plane]:
    """Apply the sRGB opto-electronic transfer curve (display step)."""
    def enc(v: float) -> float:
        v = min(max(v, 0.0), 1.0)
        return 1.055 * v ** (1.0 / 2.4) - 0.055 if v > 0.0031308 else 12.92 * v

    return (
        [[enc(v) for v in row] for row in r],
        [[enc(v) for v in row] for row in g],
        [[enc(v) for v in row] for row in b],
    )


def linear_preview(r: Plane, g: Plane, b: Plane
                   ) -> tuple[Plane, Plane, Plane]:
    """Clamp-only preview: documents the saved result without a curve."""
    def cl(v: float) -> float:
        return min(max(v, 0.0), 1.0)

    return (
        [[cl(v) for v in row] for row in r],
        [[cl(v) for v in row] for row in g],
        [[cl(v) for v in row] for row in b],
    )
