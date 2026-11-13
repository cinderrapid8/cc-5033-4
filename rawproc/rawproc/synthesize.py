"""Synthetic Bayer sensor samples for verifying the development chain.

These are *sensor-level* mosaiced uint16 dumps plus honest sidecars — not
camera JPEGs.  Five scenarios are produced:

  handcalc    tiny 4x4 frame with integer-friendly levels, hand-verifiable
  phase       non-trivial crop origin and orientation to prove the CFA phase
              is tracked rather than guessed from width/height
  chart       solid colors, slanted edge, high-frequency checkerboard and
              deliberate saturated / under-black points on one sensor
  edge45      45-degree slanted edge for interpolation inspection
  checker     high-frequency 1px checkerboard (worst case for demosaicing)
"""

from __future__ import annotations

import json
import os

from . import rawio
from .metadata import RawMeta

# RGGB base repeat keyed by (row%2, col%2): 0=R 1=G1 2=G2 3=B
_RGGB = ((0, 1), (2, 3))
_CH_NAMES = ("r", "g1", "g2", "b")


def _index_at(r: int, c: int, origin: tuple[int, int]) -> int:
    orow, ocol = origin
    return _RGGB[(r - orow) % 2][(c - ocol) % 2]


def _mosaic_from_rgb(width: int, height: int, origin: tuple[int, int],
                     rgb_fn) -> list[list[int]]:
    # CFA index -> RGB component: R->0, both greens->1, B->2
    _to_rgb = {0: 0, 1: 1, 2: 1, 3: 2}
    plane = [[0] * width for _ in range(height)]
    for r in range(height):
        for c in range(width):
            rgb = rgb_fn(r, c)
            plane[r][c] = int(rgb[_to_rgb[_index_at(r, c, origin)]])
    return plane


def _sidecar(path_raw: str, width: int, height: int, origin,
             black: dict, white: int, crop_origin, crop_size,
             orientation: int, description: str) -> str:
    meta = {
        "width": width,
        "height": height,
        "dtype": "<u2",
        "cfa_layout": "rggb",
        "cfa_origin": list(origin),
        "black_levels": black,
        "white_level": white,
        "crop_origin": list(crop_origin),
        "crop_size": list(crop_size),
        "orientation": orientation,
        "raw_file": os.path.basename(path_raw),
        "description": description,
        "synthetic": True,
    }
    path_json = os.path.splitext(path_raw)[0] + ".json"
    with open(path_json, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    return path_json


def make_handcalc(out_dir: str) -> tuple[str, str]:
    """4x4 RGGB, origin (0,0), black 256/260/256/264, white 4096.

    Each channel receives a constant raw value so hand normalization is
    trivial; one pixel is under black and one is saturated.
    """
    width = height = 4
    origin = (0, 0)
    black = {"r": 256, "g1": 260, "g2": 256, "b": 264}
    white = 4096
    # Constant per-channel raw values; chosen so normalized values are exact:
    #   R: (1216-256)/3840 = 0.25 ; G1: (2178-260)/3836 = 0.5
    #   G2: (2176-256)/3840 = 0.5 ; B: (3138-264)/3832 = 0.75
    const = {0: 1216, 1: 2178, 2: 2176, 3: 3138}

    def rgb_fn(r, c):
        idx = _index_at(r, c, origin)
        rgb = [0, 0, 0]
        rgb[{0: 0, 1: 1, 2: 1, 3: 2}[idx]] = const[idx]
        return rgb

    plane = _mosaic_from_rgb(width, height, origin, rgb_fn)
    plane[0][0] = 100       # R pixel below black (256)
    plane[3][3] = 4096      # B pixel at/over white

    raw_path = os.path.join(out_dir, "handcalc.raw")
    rawio.write_raw(raw_path, plane)
    json_path = _sidecar(
        raw_path, width, height, origin, black, white,
        crop_origin=(0, 0), crop_size=(4, 4), orientation=1,
        description="4x4 hand-calculation reference with under-black and "
                    "saturated pixels",
    )
    return raw_path, json_path


def make_chart(out_dir: str) -> tuple[str, str]:
    """24x24 sensor: solid patches, slanted edge, checkerboard, extremes."""
    width = height = 24
    origin = (0, 0)
    black = {"r": 512, "g1": 520, "g2": 512, "b": 528}
    white = 16383

    def solid(v):
        return lambda r, c: (v, v, v)

    def rgb_fn(r, c):
        # Left 8 columns: two wide solid color bars (pure R then pure B),
        # wide enough that bar centers have same-channel demosaic neighbors.
        if c < 4:
            return (12000, 520, 528)          # red bar
        if c < 8:
            return (512, 520, 12000)          # blue bar
        # Middle third: slanted edge, dark below the diagonal, bright above.
        if c < 16:
            bright = r > (c - 8)
            v = 14000 if bright else 900
            return (v, v, v)
        # Right third: high-frequency checkerboard (per output-pixel phase).
        checker = 13000 if (r + c) % 2 == 0 else 700
        return (checker, checker, checker)

    plane = _mosaic_from_rgb(width, height, origin, rgb_fn)
    # Explicit extremes inside the active crop [2:22, 2:22]: an under-black
    # cluster near the crop corner and a saturated sensor pixel.
    plane[2][2] = 100
    plane[21][21] = white

    raw_path = os.path.join(out_dir, "chart.raw")
    rawio.write_raw(raw_path, plane)
    json_path = _sidecar(
        raw_path, width, height, origin, black, white,
        crop_origin=(2, 2), crop_size=(20, 20), orientation=1,
        description="Solid colors, slanted edge, checkerboard, under-black "
                    "and saturated points; active crop offset (2,2)",
    )
    return raw_path, json_path


def make_phase(out_dir: str) -> tuple[str, str]:
    """Odd dimensions, off-grid crop and 90-degree rotation: phase torture."""
    width, height = 18, 14
    origin = (1, 0)  # top-left sensor pixel is G2, not R
    black = {"r": 256, "g1": 256, "g2": 256, "b": 256}
    white = 1024

    def rgb_fn(r, c):
        # Flat neutral field: after correct channel handling every output
        # pixel reconstructs the same normalized gray regardless of phase.
        return (768, 768, 768)

    plane = _mosaic_from_rgb(width, height, origin, rgb_fn)
    raw_path = os.path.join(out_dir, "phase.raw")
    rawio.write_raw(raw_path, plane)
    json_path = _sidecar(
        raw_path, width, height, origin, black, white,
        crop_origin=(1, 1), crop_size=(11, 13), orientation=6,
        description="Off-origin CFA, odd crop and EXIF orientation 6 "
                    "(90 CW) to validate color-position tracking",
    )
    return raw_path, json_path


def make_edge45(out_dir: str) -> tuple[str, str]:
    width = height = 16
    origin = (0, 0)
    black = {"r": 0, "g1": 0, "g2": 0, "b": 0}
    white = 65535

    def rgb_fn(r, c):
        v = 50000 if r + c >= width else 4000
        return (v, v, v)

    plane = _mosaic_from_rgb(width, height, origin, rgb_fn)
    raw_path = os.path.join(out_dir, "edge45.raw")
    rawio.write_raw(raw_path, plane)
    json_path = _sidecar(
        raw_path, width, height, origin, black, white,
        crop_origin=(0, 0), crop_size=(16, 16), orientation=1,
        description="45-degree slanted neutral edge for interpolation check",
    )
    return raw_path, json_path


def make_checker(out_dir: str) -> tuple[str, str]:
    width = height = 16
    origin = (0, 1)  # shifted CFA phase
    black = {"r": 100, "g1": 100, "g2": 100, "b": 100}
    white = 4000

    def rgb_fn(r, c):
        v = 3500 if (r + c) % 2 == 0 else 600
        return (v, v, v)

    plane = _mosaic_from_rgb(width, height, origin, rgb_fn)
    raw_path = os.path.join(out_dir, "checker.raw")
    rawio.write_raw(raw_path, plane)
    json_path = _sidecar(
        raw_path, width, height, origin, black, white,
        crop_origin=(0, 0), crop_size=(16, 16), orientation=3,
        description="One-pixel checkerboard with shifted CFA and 180 rotation",
    )
    return raw_path, json_path


def make_all(out_dir: str) -> dict[str, tuple[str, str]]:
    os.makedirs(out_dir, exist_ok=True)
    return {
        "handcalc": make_handcalc(out_dir),
        "chart": make_chart(out_dir),
        "phase": make_phase(out_dir),
        "edge45": make_edge45(out_dir),
        "checker": make_checker(out_dir),
    }
