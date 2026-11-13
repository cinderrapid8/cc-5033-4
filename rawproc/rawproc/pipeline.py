"""End-to-end raw development pipeline.

Stages, in order, each independently inspectable from the GUI:

  sensor dump -> active-area crop -> orientation -> per-channel black
  subtraction / white normalization (with under-black & saturation flags)
  -> bilinear demosaic -> *optional* white balance -> display curve (preview)

The saved high-bit-depth result stays linear; the sRGB curve exists only as
a separately stored preview.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import arrayops, cfa, color, imageio, raw_adapter
from .metadata import RawMeta
from .rawdecode import DECODER_NAME, DECODER_VERSION


@dataclass
class PipelineResult:
    meta: RawMeta
    raw_sensor: list[list[int]]
    cropped_raw: list[list[int]]
    oriented_raw: list[list[int]]
    index_plane: list[list[int]]
    channel_names: tuple[str, ...]
    mosaic: arrayops.Plane
    under_mask: arrayops.Mask
    saturated_mask: arrayops.Mask
    demosaiced: tuple[arrayops.Plane, arrayops.Plane, arrayops.Plane]
    wb_gains: tuple[float, float, float]
    linear_wb: tuple[arrayops.Plane, arrayops.Plane, arrayops.Plane]
    display_srgb: tuple[arrayops.Plane, arrayops.Plane, arrayops.Plane]
    display_linear: tuple[arrayops.Plane, arrayops.Plane, arrayops.Plane]
    channel_stats: list[dict]
    warnings: list[str] = field(default_factory=list)
    # rawdecode v2 contract evidence, surfaced so callers never have to assume
    # which decoder / which explicit levels and window produced the pixels.
    decoder_name: str = DECODER_NAME
    decoder_version: str = DECODER_VERSION
    as_shot_wb: tuple[float, float, float] | None = None
    active_window: tuple[tuple[int, int], tuple[int, int]] | None = None

    @property
    def width(self) -> int:
        return len(self.oriented_raw[0])

    @property
    def height(self) -> int:
        return len(self.oriented_raw)


def run_pipeline(sidecar_path: str,
                 wb_gains: tuple[float, float, float] | None = None,
                 auto_white_balance: bool = False) -> PipelineResult:
    # New decode path: the rawdecode v2 frame is the only thing that touches
    # the byte stream / sidecar.  The adapter re-checks the three contracts
    # (black levels, as-shot WB, active window) before any pixel math runs.
    frame = raw_adapter.decode_frame(sidecar_path)
    meta = raw_adapter.frame_to_meta(frame)
    as_shot_wb = raw_adapter.as_shot_white_balance(frame)
    active_window = raw_adapter.working_window(frame)
    warnings: list[str] = []

    raw_sensor = frame.pixels

    (oy, ox), (ch, cw) = active_window
    cropped_raw = arrayops.crop(raw_sensor, oy, ox, ch, cw)
    oriented_raw = arrayops.apply_orientation(cropped_raw, meta.orientation)

    # The CFA phase moves with the crop origin and the orientation transform.
    # Crop: red-pixel coordinates become (r-oy, c-ox), so the new top-left
    # phase is a coordinate shift, reduced modulo 2 only at the very end.
    shifted_origin = (
        meta.cfa_origin[0] - meta.crop_origin[0],
        meta.cfa_origin[1] - meta.crop_origin[1],
    )
    shifted_origin = (shifted_origin[0] % 2, shifted_origin[1] % 2)
    shifted_origin = arrayops.transform_cfa_origin(
        shifted_origin, meta.orientation, ch, cw
    )

    height = len(oriented_raw)
    width = len(oriented_raw[0])
    index_plane = cfa.build_index_plane(height, width, shifted_origin)

    mosaic, under_mask, saturated_mask = cfa.correct(
        oriented_raw, index_plane, meta
    )
    stats = cfa.per_channel_stats(oriented_raw, index_plane, meta)
    if arrayops.mask_any(under_mask):
        warnings.append(
            f"{arrayops.count_true(under_mask)} pixel(s) below per-channel "
            "black level — clamped to 0 and flagged (blue)"
        )
    if arrayops.mask_any(saturated_mask):
        warnings.append(
            f"{arrayops.count_true(saturated_mask)} saturated pixel(s) at/over "
            "white level — clamped to 1 and flagged (red)"
        )

    r, g, b = demosaic_dispatch(mosaic, shifted_origin, index_plane)

    if auto_white_balance and wb_gains is None:
        wb_gains = color.gray_world_gains(r, g, b)
        warnings.append(
            f"gray-world white balance applied: gains "
            f"R={wb_gains[0]:.4f} G={wb_gains[1]:.4f} B={wb_gains[2]:.4f}"
        )
    if wb_gains is None:
        wb_gains = (1.0, 1.0, 1.0)

    lr, lg, lb = color.apply_white_balance(r, g, b, wb_gains)
    srgb = color.srgb_encoded(lr, lg, lb)
    linprev = color.linear_preview(lr, lg, lb)

    return PipelineResult(
        meta=meta,
        raw_sensor=raw_sensor,
        cropped_raw=cropped_raw,
        oriented_raw=oriented_raw,
        index_plane=index_plane,
        channel_names=meta.channels,
        mosaic=mosaic,
        under_mask=under_mask,
        saturated_mask=saturated_mask,
        demosaiced=(r, g, b),
        wb_gains=wb_gains,
        linear_wb=(lr, lg, lb),
        display_srgb=srgb,
        display_linear=linprev,
        channel_stats=stats,
        warnings=warnings,
        decoder_name=frame.decoder,
        decoder_version=frame.decoder_version,
        as_shot_wb=as_shot_wb,
        active_window=active_window,
    )


def demosaic_dispatch(mosaic: arrayops.Plane,
                      cfa_origin: tuple[int, int],
                      index_plane: list[list[int]] | None = None
                      ) -> tuple[arrayops.Plane, arrayops.Plane, arrayops.Plane]:
    # Single explicit layout; anything else was already rejected at metadata
    # load time, but guard again at the processing boundary.
    from .demosaic import demosaic
    return demosaic(mosaic, cfa_origin, index_plane)


def save_outputs(result: PipelineResult, out_dir: str, stem: str) -> dict:
    """Persist linear high-bit-depth data separately from display previews."""
    os.makedirs(out_dir, exist_ok=True)
    paths: dict[str, str] = {}
    r, g, b = result.linear_wb

    # 1. High-bit-depth linear results (actual computed values, no curve).
    p16 = os.path.join(out_dir, f"{stem}_linear16.png")
    imageio.write_png(p16, [r, g, b], bitdepth=16)
    paths["linear16_png"] = p16

    ppm16 = os.path.join(out_dir, f"{stem}_linear16.ppm")
    _write_ppm16(ppm16, r, g, b)
    paths["linear16_ppm"] = ppm16

    raw_bin = os.path.join(out_dir, f"{stem}_linear_float32.bin")
    _write_float32(raw_bin, r, g, b)
    paths["linear_float32_bin"] = raw_bin

    # 2. Display previews (curve applied), stored apart from the result.
    sr, sg, sb = result.display_srgb
    prev = os.path.join(out_dir, f"{stem}_preview_srgb8.png")
    imageio.write_png(prev, [sr, sg, sb], bitdepth=8)
    paths["preview_srgb8_png"] = prev

    lp = os.path.join(out_dir, f"{stem}_preview_linear8.png")
    imageio.write_png(lp, list(result.display_linear), bitdepth=8)
    paths["preview_linear8_png"] = lp

    ov = os.path.join(out_dir, f"{stem}_preview_flags8.png")
    imageio.write_png(
        ov,
        imageio.mask_overlay(sr, sg, sb, result.saturated_mask,
                             result.under_mask),
        bitdepth=8,
    )
    paths["preview_flags_png"] = ov

    # 3. Sensor-level masks and the mosaiced sensor plane.
    su = os.path.join(out_dir, f"{stem}_mask_underblack8.png")
    imageio.write_mask_png(su, result.under_mask)
    paths["mask_under_png"] = su
    ss = os.path.join(out_dir, f"{stem}_mask_saturated8.png")
    imageio.write_mask_png(ss, result.saturated_mask)
    paths["mask_sat_png"] = ss
    mo = os.path.join(out_dir, f"{stem}_mosaic_gray16.png")
    imageio.write_png(mo, [result.mosaic], bitdepth=16)
    paths["mosaic_png"] = mo

    sidecar = os.path.join(out_dir, f"{stem}_result.json")
    with open(sidecar, "w", encoding="utf-8") as fh:
        json.dump({
            "source_raw": result.meta.raw_file,
            "raw_decoder": {
                "name": result.decoder_name,
                "version": result.decoder_version,
                "legacy_contract": "1.0.0",
            },
            "cfa_layout": result.meta.cfa_layout,
            "effective_cfa_origin_rgb_phase": _effective_origin(result),
            "orientation": result.meta.orientation,
            "crop_origin": list(result.meta.crop_origin),
            "crop_size": list(result.meta.crop_size),
            "active_window_origin": list(result.active_window[0])
            if result.active_window else None,
            "active_window_size": list(result.active_window[1])
            if result.active_window else None,
            "black_levels": result.meta.black_levels,
            "white_level": result.meta.white_level,
            "as_shot_white_balance": (list(result.as_shot_wb)
                                     if result.as_shot_wb is not None else None),
            "white_balance_gains": dict(
                zip(("r", "g", "b"), result.wb_gains)
            ),
            "linear_encoding": "float32 planar RGB, row-major, little-endian",
            "display_curve": "sRGB IEC 61966-2-1, applied to previews only",
            "bit_depth_saved": 16,
            "warnings": result.warnings,
            "files": paths,
        }, fh, indent=2)
    paths["result_json"] = sidecar
    return paths


def _effective_origin(result: PipelineResult) -> list[int]:
    oy, ox = result.meta.crop_origin
    ch, cw = result.meta.crop_size
    origin = ((result.meta.cfa_origin[0] - oy) % 2,
              (result.meta.cfa_origin[1] - ox) % 2)
    return list(arrayops.transform_cfa_origin(
        origin, result.meta.orientation, ch, cw))


def _write_ppm16(path: str, r: arrayops.Plane, g: arrayops.Plane,
                 b: arrayops.Plane) -> None:
    height, width = len(r), len(r[0])
    import struct
    with open(path, "wb") as fh:
        header = f"P6\n{width} {height}\n65535\n".encode("ascii")
        fh.write(header)
        buf = bytearray()
        for i in range(height):
            for j in range(width):
                for plane in (r, g, b):
                    v = int(round(min(max(plane[i][j], 0.0), 1.0) * 65535))
                    buf.append((v >> 8) & 0xFF)
                    buf.append(v & 0xFF)
        fh.write(bytes(buf))


def _write_float32(path: str, r: arrayops.Plane, g: arrayops.Plane,
                   b: arrayops.Plane) -> None:
    import struct
    height, width = len(r), len(r[0])
    with open(path, "wb") as fh:
        fh.write(struct.pack("<II", width, height))
        for plane in (r, g, b):
            fh.write(struct.pack(
                "<%df" % (width * height),
                *(v for row in plane for v in row),
            ))
