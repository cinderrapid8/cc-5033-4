"""Local browser GUI for the raw development pipeline (stdlib only).

Run::

    python -m rawproc.gui [--port 8765]

and open the printed URL.  The browser is the graphical front end; all pixel
math stays in this process.  Errors from the pipeline are returned as JSON
with ``ok: false`` and shown in the interface's status area instead of
crashing the page.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import arrayops, imageio, pipeline, raw_adapter, synthesize
from .errors import RawDevError
from .metadata import load_metadata
from .rawdecode import DECODER_NAME, DECODER_VERSION

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "web")
_cache_lock = threading.Lock()
_cache: dict[str, pipeline.PipelineResult] = {}


def _samples_index(samples_dir: str) -> list[dict]:
    items = []
    if not os.path.isdir(samples_dir):
        return items
    for name in sorted(os.listdir(samples_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(samples_dir, name)
        try:
            meta = load_metadata(path)
        except RawDevError:
            continue
        items.append({
            "sidecar": path,
            "name": os.path.splitext(name)[0],
            "description": meta.description,
            "width": meta.width,
            "height": meta.height,
            "cfa_layout": meta.cfa_layout,
            "cfa_origin": list(meta.cfa_origin),
            "crop_origin": list(meta.crop_origin),
            "crop_size": list(meta.crop_size),
            "orientation": meta.orientation,
            "black_levels": meta.black_levels,
            "white_level": meta.white_level,
        })
    return items


def _get_result(sidecar: str, wb, auto: bool) -> pipeline.PipelineResult:
    key = f"{sidecar}|{auto}|{wb}"
    with _cache_lock:
        if key not in _cache:
            _cache[key] = pipeline.run_pipeline(
                sidecar, wb_gains=None if auto else wb,
                auto_white_balance=auto,
            )
        return _cache[key]


def _gray16(plane) -> bytes:
    return imageio.png_bytes([plane], bitdepth=8)


def _raw_gray8(raw2d, black: float, white: float) -> bytes:
    span = max(white - black, 1)
    norm = [[(v - black) / span for v in row] for row in raw2d]
    return imageio.png_bytes([norm], bitdepth=8)


def _stage_png(result: pipeline.PipelineResult, stage: str) -> bytes:
    r, g, b = result.demosaiced
    lr, lg, lb = result.linear_wb
    sr, sg, sb = result.display_srgb
    if stage == "raw_sensor":
        m = result.meta
        return _raw_gray8(result.raw_sensor,
                          min(m.black_levels.values()), m.white_level)
    if stage == "cropped_raw":
        m = result.meta
        return _raw_gray8(result.cropped_raw,
                          min(m.black_levels.values()), m.white_level)
    if stage == "mosaic":
        return _gray16(result.mosaic)
    if stage == "demosaic":
        return imageio.png_bytes(list(
            color_clamped(result.demosaiced)), bitdepth=8)
    if stage == "linear_wb":
        return imageio.png_bytes(list(
            color_clamped(result.linear_wb)), bitdepth=8)
    if stage == "srgb":
        return imageio.png_bytes([sr, sg, sb], bitdepth=8)
    if stage == "flags":
        return imageio.png_bytes(
            imageio.mask_overlay(sr, sg, sb, result.saturated_mask,
                                 result.under_mask),
            bitdepth=8,
        )
    raise RawDevError(f"unknown view stage: {stage}")


def color_clamped(planes):
    out = []
    for p in planes:
        out.append([[min(max(v, 0.0), 1.0) for v in row] for row in p])
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "rawproc/1.0"

    def log_message(self, fmt, *args):  # quiet console
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_png(self, blob: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _parse_wb(self, qs) -> tuple[tuple[float, float, float], bool]:
        auto = qs.get("auto", ["0"])[0] in ("1", "true", "yes")
        if auto:
            return (1.0, 1.0, 1.0), True
        try:
            wb = tuple(float(qs.get(k, ["1"])[0]) for k in ("wr", "wg", "wb"))
        except ValueError as exc:
            raise RawDevError("white-balance gains must be numbers") from exc
        if any(v <= 0 for v in wb):
            raise RawDevError("white-balance gains must be positive")
        return wb, False

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                return self._serve_static("index.html", "text/html; charset=utf-8")
            if parsed.path == "/app.js":
                return self._serve_static("app.js", "application/javascript")
            if parsed.path == "/style.css":
                return self._serve_static("style.css", "text/css")
            if parsed.path == "/api/samples":
                return self._send_json(
                    {"ok": True,
                     "samples": _samples_index(self.server.samples_dir)})
            if parsed.path == "/api/process":
                return self._handle_process(qs)
            if parsed.path == "/api/image":
                return self._handle_image(qs)
            if parsed.path == "/api/pixel":
                return self._handle_pixel(qs)
            if parsed.path == "/api/save":
                return self._handle_save(qs)
            self._send_json({"ok": False, "error": "not found"}, 404)
        except RawDevError as exc:
            self._send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:  # surface unexpected failures in the GUI
            self._send_json(
                {"ok": False, "error": f"internal error: {exc}"}, 500)

    def _serve_static(self, name: str, ctype: str):
        path = os.path.join(_STATIC, name)
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _result_from_qs(self, qs) -> pipeline.PipelineResult:
        sidecar = qs.get("sidecar", [""])[0]
        if not sidecar:
            raise RawDevError("no sample selected")
        sidecar = urllib.parse.unquote(sidecar)
        wb, auto = self._parse_wb(qs)
        return _get_result(sidecar, wb, auto)

    def _handle_process(self, qs):
        result = self._result_from_qs(qs)
        self._send_json({
            "ok": True,
            "width": result.width,
            "height": result.height,
            "warnings": result.warnings,
            "wb_gains": dict(zip(("r", "g", "b"), result.wb_gains)),
            "decoder": {
                "name": result.decoder_name,
                "version": result.decoder_version,
                "as_shot_wb": list(result.as_shot_wb)
                if result.as_shot_wb is not None else None,
                "active_window_origin": list(result.active_window[0])
                if result.active_window else None,
                "active_window_size": list(result.active_window[1])
                if result.active_window else None,
            },
            "channel_stats": result.channel_stats,
            "stages": [
                ("raw_sensor", "原始传感器采样"),
                ("cropped_raw", "裁切/旋转后传感器"),
                ("mosaic", "黑扣除+白归一 (马赛克)"),
                ("demosaic", "去马赛克 (线性)"),
                ("linear_wb", "白平衡后线性结果"),
                ("srgb", "sRGB 显示预览"),
                ("flags", "过黑/饱和标记预览"),
            ],
        })

    def _handle_image(self, qs):
        result = self._result_from_qs(qs)
        stage = qs.get("stage", ["srgb"])[0]
        self._send_png(_stage_png(result, stage))

    def _handle_pixel(self, qs):
        result = self._result_from_qs(qs)
        try:
            r = int(qs["r"][0]); c = int(qs["c"][0])
        except (KeyError, ValueError) as exc:
            raise RawDevError("pixel query needs integer r and c") from exc
        if not (0 <= r < result.height and 0 <= c < result.width):
            raise RawDevError(
                f"pixel ({r},{c}) outside {result.height}x{result.width}")
        idx = result.index_plane[r][c]
        dr, dg, db = result.demosaiced
        lr, lg, lb = result.linear_wb
        sr, sg, sb = result.display_srgb
        self._send_json({"ok": True, "pixel": {
            "row": r, "col": c,
            "cfa_index": idx,
            "cfa_channel": result.channel_names[idx],
            "raw_uint16": result.oriented_raw[r][c],
            "normalized_mosaic": result.mosaic[r][c],
            "under_black": result.under_mask[r][c],
            "saturated": result.saturated_mask[r][c],
            "linear_demosaic_rgb": [dr[r][c], dg[r][c], db[r][c]],
            "linear_wb_rgb": [lr[r][c], lg[r][c], lb[r][c]],
            "linear16_rgb": [
                round(min(max(lr[r][c], 0.0), 1.0) * 65535),
                round(min(max(lg[r][c], 0.0), 1.0) * 65535),
                round(min(max(lb[r][c], 0.0), 1.0) * 65535),
            ],
            "srgb8_rgb": [
                round(sr[r][c] * 255), round(sg[r][c] * 255),
                round(sb[r][c] * 255),
            ],
        }})

    def _handle_save(self, qs):
        result = self._result_from_qs(qs)
        out_dir = qs.get("outdir", [self.server.output_dir])[0]
        stem = qs.get("stem", ["frame"])[0]
        if not stem.replace("_", "").isalnum():
            raise RawDevError("stem must be alphanumeric/underscore only")
        paths = pipeline.save_outputs(result, out_dir, stem)
        self._send_json({"ok": True, "files": paths,
                         "warnings": result.warnings})


def serve(samples_dir: str, output_dir: str, port: int = 8765,
          host: str = "127.0.0.1") -> None:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.samples_dir = os.path.abspath(samples_dir)
    httpd.output_dir = os.path.abspath(output_dir)
    os.makedirs(httpd.samples_dir, exist_ok=True)
    os.makedirs(httpd.output_dir, exist_ok=True)
    print(f"rawproc GUI on http://{host}:{port}/  (Ctrl+C to stop)")
    print(f"samples: {httpd.samples_dir}")
    print(f"outputs: {httpd.output_dir}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Browser GUI for the rawproc raw development prototype")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--samples", default=os.path.join(root, "samples"))
    ap.add_argument("--outdir", default=os.path.join(root, "output"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    serve(args.samples, args.outdir, args.port, args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
