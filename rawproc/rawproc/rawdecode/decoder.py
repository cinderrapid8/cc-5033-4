"""rawdecode v2 public decode entry point.

The single public function :func:`decode` turns validated sidecar metadata
plus a sensor byte stream into a :class:`~rawproc.rawdecode.models.RawFrame`.

Interface changes checked explicitly here, relative to the v1 ``rawio`` /
``RawMeta`` contract:

1. **Black level** — v1 exposed a dict and tolerated callers indexing it by
   name; v2 demands all four per-channel black levels up front and fails with
   :class:`LevelError` if any are missing or non-integer.  Nothing is ever
   substituted with zero.
2. **White-balance coefficients** — v1 had no decoder-side WB contract.  v2
   parses an explicit ``as_shot_wb`` ``[r, g, b]`` triple (positive floats);
   the field may be *absent* (meaning "not advertised", stored as ``None``)
   but when present it must be complete and valid — partial triples are an
   error, never silently completed with 1.0.
3. **Active-pixel window** — v1 stored crop origin/size as loose tuples; v2
   builds an :class:`ActiveWindow` and proves it lies inside the sensor
   rectangle before the pixel plane is sliced.
"""

from __future__ import annotations

import json
import os

from .errors import LevelError, StreamError, WhiteBalanceError, WindowError
from .models import (
    CHANNELS,
    ActiveWindow,
    RawFrame,
    RawLevels,
    WhiteBalanceCoeffs,
)
from .stream import read_uint16_plane

DECODER_NAME = "rawdecode"
DECODER_VERSION = "2.0.0"
LEGACY_API_VERSION = "1.0.0"

_SUPPORTED_DTYPES = ("<u2", "uint16")
_VALID_ORIENTATIONS = frozenset(range(1, 9))


def decode_sidecar(sidecar_path: str) -> RawFrame:
    """Decode a homemade RAW sample described by a JSON sidecar."""
    data = _load_json(sidecar_path)
    base_dir = os.path.dirname(os.path.abspath(sidecar_path))

    width, height = _require_geometry(data)
    dtype = str(data.get("dtype", "")).lower()
    if dtype not in _SUPPORTED_DTYPES:
        raise StreamError(
            f"unsupported dtype {dtype!r}; rawdecode {DECODER_VERSION} reads "
            "little-endian uint16 only")

    cfa_origin = _require_cfa_origin(data)
    levels = _require_levels(data)
    window = _require_window(data, width, height)
    as_shot_wb = _optional_wb(data)

    orientation = data.get("orientation", 1)
    if not isinstance(orientation, int) or isinstance(orientation, bool) \
            or orientation not in _VALID_ORIENTATIONS:
        raise WindowError(
            f"orientation must be an integer 1..8, got {orientation!r}")

    raw_file = data.get("raw_file")
    if not isinstance(raw_file, str) or not raw_file:
        raise StreamError("sidecar does not name a raw_file")
    raw_path = raw_file if os.path.isabs(raw_file) else os.path.normpath(
        os.path.join(base_dir, raw_file))

    pixels = read_uint16_plane(raw_path, height, width)

    return RawFrame(
        pixels=pixels,
        sensor_width=width,
        sensor_height=height,
        cfa_origin=cfa_origin,
        levels=levels,
        window=window,
        as_shot_wb=as_shot_wb,
        orientation=orientation,
        source_path=raw_path,
        decoder=DECODER_NAME,
        decoder_version=DECODER_VERSION,
    )


def _load_json(sidecar_path: str) -> dict:
    try:
        with open(sidecar_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        raise WindowError(f"sidecar not found: {sidecar_path}") from exc
    except json.JSONDecodeError as exc:
        raise WindowError(f"sidecar is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WindowError("sidecar root must be a JSON object")
    return data


def _require_geometry(data: dict) -> tuple[int, int]:
    for key in ("width", "height"):
        if key not in data:
            raise WindowError(f"sidecar missing {key}")
        if not isinstance(data[key], int) or isinstance(data[key], bool):
            raise WindowError(f"{key} must be an integer")
    width, height = data["width"], data["height"]
    if width <= 0 or height <= 0:
        raise WindowError("width/height must be positive")
    return width, height


def _require_cfa_origin(data: dict) -> tuple[int, int]:
    origin = data.get("cfa_origin")
    if not isinstance(origin, (list, tuple)) or len(origin) != 2:
        raise WindowError("cfa_origin must be a [row, col] pair")
    if any(not isinstance(v, int) or isinstance(v, bool) for v in origin):
        raise WindowError("cfa_origin entries must be integers 0 or 1")
    if any(v not in (0, 1) for v in origin):
        raise WindowError("cfa_origin entries must be 0 or 1 (2x2 CFA)")
    return int(origin[0]), int(origin[1])


def _require_levels(data: dict) -> RawLevels:
    """Contract 1: every per-channel black/white level must be explicit."""
    black_raw = data.get("black_levels")
    if not isinstance(black_raw, dict):
        raise LevelError(
            "black_levels must be an object with r, g1, g2 and b; no default "
            "black level is ever substituted")
    missing = [name for name in CHANNELS if name not in black_raw]
    if missing:
        raise LevelError(
            f"black_levels missing channel(s): {', '.join(missing)}; the "
            "decoder never fills a missing black level with a default")
    try:
        black = tuple(int(black_raw[name]) for name in CHANNELS)
    except (TypeError, ValueError) as exc:
        raise LevelError("black_levels entries must be integers") from exc
    if any(v < 0 for v in black):
        raise LevelError("black levels must be non-negative")

    if "white_level" not in data:
        raise LevelError(
            "white_level is required; no default white level is substituted")
    try:
        fallback_white = int(data["white_level"])
    except (TypeError, ValueError) as exc:
        raise LevelError("white_level must be an integer") from exc

    white_overrides = data.get("white_levels") or {}
    if not isinstance(white_overrides, dict):
        raise LevelError("white_levels must be an object when present")
    try:
        white = tuple(
            int(white_overrides[name]) if name in white_overrides
            else fallback_white
            for name in CHANNELS
        )
    except (TypeError, ValueError) as exc:
        raise LevelError("white_levels entries must be integers") from exc

    for name, bl, wl in zip(CHANNELS, black, white):
        if wl <= bl:
            raise LevelError(
                f"white level for {name} ({wl}) must exceed its black "
                f"level ({bl})")
    return RawLevels(black=black, white=white)


def _require_window(data: dict, sensor_height: int,
                    sensor_width: int) -> ActiveWindow:
    """Contract 3: the active-pixel window must be present and inside the sensor."""
    origin = data.get("crop_origin")
    size = data.get("crop_size")
    if not isinstance(origin, (list, tuple)) or len(origin) != 2:
        raise WindowError("crop_origin must be a [row, col] pair")
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        raise WindowError("crop_size must be a [height, width] pair")
    if any(not isinstance(v, int) or isinstance(v, bool)
           for v in (*origin, *size)):
        raise WindowError("crop origin/size entries must be integers")
    r0, c0, h, w = origin[0], origin[1], size[0], size[1]
    if h <= 0 or w <= 0:
        raise WindowError("crop_size entries must be positive")
    if r0 < 0 or c0 < 0:
        raise WindowError("crop_origin entries must be non-negative")
    if r0 + h > sensor_height or c0 + w > sensor_width:
        raise WindowError(
            f"active window [r={r0}:{r0 + h}, c={c0}:{c0 + w}] falls outside "
            f"the {sensor_height}x{sensor_width} sensor")
    return ActiveWindow(origin=(r0, c0), size=(h, w))


def _optional_wb(data: dict) -> WhiteBalanceCoeffs | None:
    """Contract 2: as-shot WB is either fully valid or explicitly absent."""
    if "as_shot_wb" not in data:
        return None
    coeffs = data["as_shot_wb"]
    if not isinstance(coeffs, (list, tuple)) or len(coeffs) != 3:
        raise WhiteBalanceError(
            "as_shot_wb must be a [r, g, b] triple; partial coefficients are "
            "rejected rather than completed with defaults")
    try:
        r, g, b = (float(v) for v in coeffs)
    except (TypeError, ValueError) as exc:
        raise WhiteBalanceError("as_shot_wb entries must be numbers") from exc
    if any(v <= 0.0 for v in (r, g, b)):
        raise WhiteBalanceError(
            f"as_shot_wb coefficients must be positive, got [{r}, {g}, {b}]")
    return WhiteBalanceCoeffs(r=r, g=g, b=b)
