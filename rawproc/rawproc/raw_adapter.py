"""RAW upgrade adapter: development-kernel contract on top of rawdecode v2.

The pipeline was written against the v1 contract (a :class:`RawMeta` plus a
bare pixel plane).  Rather than scatter v2-specific accesses through the
kernel, every translation lives here and is deliberately narrow:

* black/white levels  : ``RawLevels`` (four explicit channel values) ->
  the per-index lookup the CFA stage uses;
* white balance       : v2 ``WhiteBalanceCoeffs`` are *as-shot* metadata and
  stay separate from the kernel's working gains (manual / gray-world);
* active-pixel window : ``ActiveWindow`` -> the ``(origin, size)`` crop pair,
  with the window's in-sensor guarantee re-checked rather than trusted.

No adapter function invents a fallback.  If a v2 frame lacks data the kernel
requires, a :class:`RawDevError` is raised at the boundary.
"""

from __future__ import annotations

from .errors import RawIOError, UnsupportedLayoutError
from .metadata import RawMeta
from .rawdecode import (
    CHANNELS,
    DECODER_NAME,
    DECODER_VERSION,
    LEGACY_API_VERSION,
    DecodeError,
    RawFrame,
    WhiteBalanceCoeffs,
    decode_sidecar,
)

SUPPORTED_CFA_LAYOUT = "rggb"


def decode_frame(sidecar_path: str) -> RawFrame:
    """Run the v2 decoder, translating its errors to the kernel's error type."""
    try:
        return decode_sidecar(sidecar_path)
    except DecodeError as exc:
        raise RawIOError(f"[{DECODER_NAME} {DECODER_VERSION}] {exc}") from exc


def frame_to_meta(frame: RawFrame) -> RawMeta:
    """Project a v2 frame back onto the v1 :class:`RawMeta` shape.

    The kernel's geometry/CFA stages still consume ``RawMeta``; this is the
    only place that shape is constructed, and every field is copied from a
    validated v2 value rather than freshly parsed.
    """
    if frame.decoder != DECODER_NAME:
        raise UnsupportedLayoutError(
            f"unknown decoder {frame.decoder!r}; expected {DECODER_NAME}")

    return RawMeta(
        width=frame.sensor_width,
        height=frame.sensor_height,
        dtype="<u2",
        cfa_layout=SUPPORTED_CFA_LAYOUT,
        cfa_origin=frame.cfa_origin,
        black_levels=frame.levels.as_black_dict(),
        white_level=_common_white(frame),
        white_levels=frame.levels.as_white_dict(),
        crop_origin=frame.window.origin,
        crop_size=frame.window.size,
        orientation=frame.orientation,
        raw_file=frame.source_path,
        extra={"decoder": frame.decoder,
               "decoder_version": frame.decoder_version},
    )


def _common_white(frame: RawFrame) -> int:
    """The single fallback white level v1 metadata expects.

    v2 stores per-channel whites explicitly; the v1 ``white_level`` scalar is
    only consulted when a channel is absent from its override dict.  The
    adapter always supplies all four overrides, so any channel value is a
    valid scalar fallback here.
    """
    return frame.levels.white[0]


def levels_for_index(frame: RawFrame, channel_index: int) -> tuple[int, int]:
    """Contract check 1 — black level for a CFA index comes straight from v2."""
    if not 0 <= channel_index < len(CHANNELS):
        raise RawIOError(
            f"CFA index {channel_index} has no level entry (channels={CHANNELS})")
    return (frame.levels.black_for(channel_index),
            frame.levels.white_for(channel_index))


def working_window(frame: RawFrame) -> tuple[tuple[int, int], tuple[int, int]]:
    """Contract check 3 — active window, re-validated against the sensor."""
    r0, c0 = frame.window.origin
    h, w = frame.window.size
    if r0 < 0 or c0 < 0 or h <= 0 or w <= 0:
        raise RawIOError(f"decoder returned a degenerate window: {frame.window}")
    if r0 + h > frame.sensor_height or c0 + w > frame.sensor_width:
        raise RawIOError(
            f"active window {frame.window} escapes the "
            f"{frame.sensor_height}x{frame.sensor_width} sensor — refusing to "
            "slice with implicit padding")
    return frame.window.origin, frame.window.size


def as_shot_white_balance(
        frame: RawFrame) -> tuple[float, float, float] | None:
    """Contract check 2 — as-shot WB, or ``None`` when the sample advertises none.

    ``None`` means *absent on purpose*.  The caller must not treat it as
    (1, 1, 1); neutralization defaults are a kernel decision made elsewhere.
    """
    wb: WhiteBalanceCoeffs | None = frame.as_shot_wb
    if wb is None:
        return None
    coeffs = wb.as_tuple()
    if any(v <= 0.0 for v in coeffs):
        raise RawIOError(
            f"decoder returned non-positive as-shot WB {coeffs}")
    return coeffs


def version_banner() -> str:
    return (f"raw-decode dependency: {DECODER_NAME} "
            f"{DECODER_VERSION} (legacy contract {LEGACY_API_VERSION})")
