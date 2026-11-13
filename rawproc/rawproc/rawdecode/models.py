"""Structured contracts for the rawdecode v2 API.

v1 handed the rest of the pipeline a loose :class:`~rawproc.metadata.RawMeta`
plus a plain 2-D list and let every consumer reach into metadata fields by
name.  v2 replaces that with narrow, validated value objects so the three
contracts that move between the decoder and the development kernel — black
level, white-balance coefficients and the active-pixel window — can each be
checked at one boundary instead of being assumed at every call site.
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical RGGB 2x2 repeat order, shared with the development kernel.
CHANNELS: tuple[str, ...] = ("r", "g1", "g2", "b")


@dataclass(frozen=True)
class RawLevels:
    """Per-CFA-channel black and white levels (sensor integer units).

    ``black`` and ``white`` are always full four-channel tuples in
    :data:`CHANNELS` order; no channel may ever fall back to a default.
    """

    black: tuple[int, int, int, int]
    white: tuple[int, int, int, int]

    def black_for(self, channel_index: int) -> int:
        return self.black[channel_index]

    def white_for(self, channel_index: int) -> int:
        return self.white[channel_index]

    def as_black_dict(self) -> dict[str, int]:
        return dict(zip(CHANNELS, self.black))

    def as_white_dict(self) -> dict[str, int]:
        return dict(zip(CHANNELS, self.white))


@dataclass(frozen=True)
class ActiveWindow:
    """Active-pixel window on the *sensor* grid, before orientation.

    ``origin`` is ``(row, col)`` and ``size`` is ``(height, width)``; both are
    guaranteed inside the sensor rectangle by the decoder.
    """

    origin: tuple[int, int]
    size: tuple[int, int]

    @property
    def row0(self) -> int:
        return self.origin[0]

    @property
    def col0(self) -> int:
        return self.origin[1]

    @property
    def height(self) -> int:
        return self.size[0]

    @property
    def width(self) -> int:
        return self.size[1]


@dataclass(frozen=True)
class WhiteBalanceCoeffs:
    """As-shot neutral multipliers ``(r, g, b)`` advertised by the decoder.

    v1 had no decoder-side white-balance contract at all; callers that wanted
    neutralization had to invent gains themselves.  v2 carries explicit
    coefficients, distinguished from the development kernel's *working* gains
    (manual or gray-world), so the two are never silently conflated.
    """

    r: float
    g: float
    b: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.r, self.g, self.b)


@dataclass(frozen=True)
class RawFrame:
    """A decoded sensor frame plus every contract the kernel needs.

    ``pixels`` is the full, uncropped sensor plane (height x width, uint16
    values); the active window, levels and CFA phase travel alongside it.  The
    decoder version is stamped on every frame so output artifacts can state
    which decoder produced them.
    """

    pixels: list[list[int]]
    sensor_width: int
    sensor_height: int
    cfa_origin: tuple[int, int]
    levels: RawLevels
    window: ActiveWindow
    as_shot_wb: WhiteBalanceCoeffs | None
    orientation: int
    source_path: str
    decoder: str
    decoder_version: str

    def active_pixels(self) -> list[list[int]]:
        """Slice the sensor plane down to the active-pixel window."""
        r0, c0 = self.window.origin
        h, w = self.window.size
        return [row[c0:c0 + w] for row in self.pixels[r0:r0 + h]]
