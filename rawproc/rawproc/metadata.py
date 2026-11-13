"""Sidecar metadata for homemade raw samples.

Every raw sample is a plain little-endian uint16 sensor dump accompanied by
a JSON sidecar.  The sidecar — not the file dimensions — decides where the
colors are: ``cfa_origin`` (R position), ``crop_origin`` and ``orientation``
all shift the Bayer phase and are consumed explicitly by the pipeline.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .errors import MetadataError

# The single Bayer data layout this prototype implements.
# CFA is described by the position of the red pixel in the 2x2 repeat:
#   "rggb" -> [[R,G],[G,B]],  "grbg" -> [[G,R],[B,G]], ...
SUPPORTED_CFA_LAYOUTS = ("rggb",)
_SUPPORTED_DTYPES = ("<u2", "uint16")
_VALID_ORIENTATIONS = tuple(range(1, 9))


@dataclass
class RawMeta:
    width: int
    height: int
    dtype: str                      # always little-endian uint16 in this build
    cfa_layout: str                 # Bayer pattern id, only "rggb" supported
    cfa_origin: tuple[int, int]     # (row, col) of the top-left R pixel
    black_levels: dict[str, int]    # per CFA channel: r, g1, g2, b
    white_level: int                # per-channel white levels may override
    white_levels: dict[str, int]
    crop_origin: tuple[int, int]    # active-area origin on the *sensor* grid
    crop_size: tuple[int, int]      # (height, width) of the active area
    orientation: int                # EXIF-style 1..8, applied after crop
    raw_file: str
    description: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def channels(self) -> tuple[str, ...]:
        # 2x2 repeat order matching cfa_layout == "rggb":
        # index 0 top-left, 1 top-right, 2 bottom-left, 3 bottom-right.
        return ("r", "g1", "g2", "b")

    def black_for_index(self, idx: int) -> int:
        return int(self.black_levels[self.channels[idx]])

    def white_for_index(self, idx: int) -> int:
        name = self.channels[idx]
        return int(self.white_levels.get(name, self.white_level))


def load_metadata(sidecar_path: str) -> RawMeta:
    try:
        with open(sidecar_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise MetadataError(f"metadata file not found: {sidecar_path}") from exc
    except json.JSONDecodeError as exc:
        raise MetadataError(f"metadata is not valid JSON: {exc}") from exc

    required = (
        "width", "height", "dtype", "cfa_layout", "cfa_origin",
        "black_levels", "white_level", "crop_origin", "crop_size",
        "orientation", "raw_file",
    )
    missing = [k for k in required if k not in data]
    if missing:
        raise MetadataError(f"metadata missing keys: {', '.join(missing)}")

    try:
        width = int(data["width"])
        height = int(data["height"])
    except (TypeError, ValueError) as exc:
        raise MetadataError("width/height must be integers") from exc
    if width <= 0 or height <= 0:
        raise MetadataError("width/height must be positive")

    dtype = str(data["dtype"]).lower()
    if dtype not in _SUPPORTED_DTYPES:
        raise MetadataError(
            f"unsupported dtype {dtype!r}; this build reads little-endian uint16"
        )

    cfa_layout = str(data["cfa_layout"]).lower()
    if cfa_layout not in SUPPORTED_CFA_LAYOUTS:
        raise MetadataError(
            f"unsupported CFA layout {cfa_layout!r}; "
            f"implemented layouts: {', '.join(SUPPORTED_CFA_LAYOUTS)}"
        )

    cfa_origin = _pair(data["cfa_origin"], "cfa_origin")
    if not all(v in (0, 1) for v in cfa_origin):
        raise MetadataError("cfa_origin entries must be 0 or 1 (2x2 CFA)")

    levels = data["black_levels"]
    if not isinstance(levels, dict) or not all(
        k in levels for k in ("r", "g1", "g2", "b")
    ):
        raise MetadataError("black_levels must contain r, g1, g2 and b")
    try:
        black_levels = {k: int(v) for k, v in levels.items()}
    except (TypeError, ValueError) as exc:
        raise MetadataError("black_levels must be integers") from exc

    try:
        white_level = int(data["white_level"])
    except (TypeError, ValueError) as exc:
        raise MetadataError("white_level must be an integer") from exc
    white_levels = {}
    if "white_levels" in data and data["white_levels"]:
        wl = data["white_levels"]
        if not isinstance(wl, dict):
            raise MetadataError("white_levels must be an object")
        try:
            white_levels = {k: int(v) for k, v in wl.items()}
        except (TypeError, ValueError) as exc:
            raise MetadataError("white_levels entries must be integers") from exc

    crop_origin = _pair(data["crop_origin"], "crop_origin")
    crop_size = _pair(data["crop_size"], "crop_size")
    ch, cw = crop_size
    oy, ox = crop_origin
    if ch <= 0 or cw <= 0:
        raise MetadataError("crop_size entries must be positive")
    if oy < 0 or ox < 0 or oy + ch > height or ox + cw > width:
        raise MetadataError(
            f"active crop [y={oy}:{oy + ch}, x={ox}:{ox + cw}] "
            f"falls outside the {height}x{width} sensor"
        )

    try:
        orientation = int(data["orientation"])
    except (TypeError, ValueError) as exc:
        raise MetadataError("orientation must be an integer 1..8") from exc
    if orientation not in _VALID_ORIENTATIONS:
        raise MetadataError(f"orientation must be 1..8, got {orientation}")

    if any(b < 0 for b in black_levels.values()):
        raise MetadataError("black levels must be non-negative")
    for name, bl in black_levels.items():
        wl = white_levels.get(name, white_level)
        if wl <= bl:
            raise MetadataError(
                f"white level for {name} ({wl}) must exceed its black level ({bl})"
            )

    raw_file = str(data["raw_file"])
    if not os.path.isabs(raw_file):
        raw_file = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(sidecar_path)), raw_file)
        )

    return RawMeta(
        width=width,
        height=height,
        dtype=dtype,
        cfa_layout=cfa_layout,
        cfa_origin=cfa_origin,
        black_levels=black_levels,
        white_level=white_level,
        white_levels=white_levels,
        crop_origin=crop_origin,
        crop_size=crop_size,
        orientation=orientation,
        raw_file=raw_file,
        description=str(data.get("description", "")),
        extra={k: v for k, v in data.items()
               if k not in required and k != "white_levels"},
    )


def _pair(value, name: str) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise MetadataError(f"{name} must be a [row, col] pair")
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError) as exc:
        raise MetadataError(f"{name} must contain integers") from exc
