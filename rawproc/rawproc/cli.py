"""Auxiliary command line for the raw development prototype.

The graphical interface (``python -m rawproc.gui``) is the primary entry
point; this CLI only mirrors the basic development flow for scripting and
checking.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import pipeline, raw_adapter, synthesize
from .errors import RawDevError


def _gains(text: str):
    if text is None:
        return None
    parts = text.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "gains must be three comma-separated numbers, e.g. 1.2,1,0.9")
    try:
        gains = tuple(float(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if any(g <= 0 for g in gains):
        raise argparse.ArgumentTypeError("gains must be positive")
    return gains


def cmd_synthesize(args) -> int:
    made = synthesize.make_all(args.samples)
    for name, (raw, sidecar) in made.items():
        print(f"[{name}] {raw} + {sidecar}")
    return 0


def cmd_info(args) -> int:
    frame = raw_adapter.decode_frame(args.sidecar)
    print(json.dumps({
        "raw_decoder": {"name": frame.decoder,
                        "version": frame.decoder_version},
        "raw_file": frame.source_path,
        "sensor": [frame.sensor_width, frame.sensor_height],
        "dtype": "<u2",
        "cfa_origin": list(frame.cfa_origin),
        "black_levels": frame.levels.as_black_dict(),
        "white_levels": frame.levels.as_white_dict(),
        "active_window": {"origin": list(frame.window.origin),
                          "size": list(frame.window.size)},
        "as_shot_white_balance": (list(frame.as_shot_wb.as_tuple())
                                  if frame.as_shot_wb else None),
        "orientation": frame.orientation,
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_develop(args) -> int:
    result = pipeline.run_pipeline(
        args.sidecar,
        wb_gains=None if args.auto_wb else _gains(args.gains),
        auto_white_balance=args.auto_wb,
    )
    stem = args.stem or os.path.splitext(
        os.path.basename(args.sidecar))[0]
    paths = pipeline.save_outputs(result, args.outdir, stem)
    print(f"developed {result.width}x{result.height} "
          f"WB={result.wb_gains}")
    for w in result.warnings:
        print(f"WARNING: {w}")
    for kind, path in paths.items():
        print(f"{kind:22s} {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(
        prog="rawproc",
        description="Auxiliary CLI; the GUI (python -m rawproc.gui) "
                    "is the primary entry point.")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("synthesize", help="create synthetic sensor samples")
    p.add_argument("--samples", default=os.path.join(root, "samples"))
    p.set_defaults(func=cmd_synthesize)

    p = sub.add_parser("info", help="print validated sample metadata")
    p.add_argument("sidecar")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("develop", help="run the basic development chain")
    p.add_argument("sidecar")
    p.add_argument("--outdir", default=os.path.join(root, "output"))
    p.add_argument("--stem", default=None)
    p.add_argument("--gains", default=None,
                   help="R,G,B linear white-balance gains, e.g. 1.2,1,0.9")
    p.add_argument("--auto-wb", action="store_true",
                   help="use gray-world gains")
    p.set_defaults(func=cmd_develop)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except RawDevError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
