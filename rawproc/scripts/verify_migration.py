#!/usr/bin/env python3
"""Verify the rawdecode v2 migration against pre-upgrade v1 golden output.

The golden file ``tests/golden/golden_v1.json`` was produced by the v1
decoder/pipeline (see scripts/regenerate_golden.sh) from the redistributable
tiny samples in ``tests/fixtures/``.  Metadata parsing alone is never treated
as success: every check below compares *processed pixels and flags*.

Checks per sample and per white-balance case (identity, manual gains,
gray-world):

  * active-pixel window (origin + size) and per-channel black levels match;
  * normalized mosaic, demosaiced linear RGB and white-balanced linear RGB
    match the v1 results float-for-float;
  * under-black / saturation masks match cell-for-cell;
  * the result is stamped with rawdecode 2.x and the frame actually went
    through the v2 adapter (not a metadata-only shortcut).

Run::

    python3 -I scripts/verify_migration.py
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rawproc import pipeline, raw_adapter  # noqa: E402
from rawproc.rawdecode import DECODER_VERSION  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")
GOLDEN = os.path.join(ROOT, "tests", "golden", "golden_v1.json")
TOL = 1e-12

CASES = (
    ("identity_gains", dict()),
    ("manual_gains", dict(wb_gains=(1.5, 1.0, 0.8))),
    ("gray_world", dict(auto_white_balance=True)),
)
PLANES = (
    ("mosaic", lambda r: r.mosaic),
    ("demosaic_r", lambda r: r.demosaiced[0]),
    ("demosaic_g", lambda r: r.demosaiced[1]),
    ("demosaic_b", lambda r: r.demosaiced[2]),
    ("linear_wb_r", lambda r: r.linear_wb[0]),
    ("linear_wb_g", lambda r: r.linear_wb[1]),
    ("linear_wb_b", lambda r: r.linear_wb[2]),
)
MASKS = (
    ("under_mask", lambda r: r.under_mask),
    ("saturated_mask", lambda r: r.saturated_mask),
)


def _assert_plane_equal(label, got, expected, failures):
    if len(got) != len(expected) or any(
            len(a) != len(b) for a, b in zip(got, expected)):
        failures.append(f"{label}: shape mismatch")
        return
    for i, (grow, erow) in enumerate(zip(got, expected)):
        for j, (g, e) in enumerate(zip(grow, erow)):
            if abs(g - e) > TOL:
                failures.append(
                    f"{label}: pixel ({i},{j}) v2={g!r} != v1={e!r}")
                return


def _assert_mask_equal(label, got, expected, failures):
    if got != expected:
        diffs = [
            (i, j) for i, (gr, er) in enumerate(zip(got, expected))
            for j, (g, e) in enumerate(zip(gr, er)) if g != e]
        failures.append(f"{label}: mask differs at {diffs[:5]} ...")


def main() -> int:
    golden = json.load(open(GOLDEN, "r", encoding="utf-8"))
    assert golden["api_version"] == "1.0.0", "golden file is not a v1 baseline"
    failures: list[str] = []
    checked = 0

    for name, frame_golden in golden["frames"].items():
        sidecar = os.path.join(FIXTURES, f"{name}.json")
        # Decode through the v2 path first and prove the adapter really ran.
        frame = raw_adapter.decode_frame(sidecar)
        if frame.decoder_version != DECODER_VERSION:
            failures.append(
                f"{name}: frame stamped {frame.decoder_version!r}, "
                f"expected {DECODER_VERSION}")
        for case_name, kwargs in CASES:
            result = pipeline.run_pipeline(sidecar, **kwargs)
            ref = frame_golden[case_name]
            checked += 1

            if result.active_window != tuple(map(tuple, ref["active_window"])):
                failures.append(
                    f"{name}/{case_name}: active window "
                    f"{result.active_window} != v1 {ref['active_window']}")
            if result.meta.black_levels != ref["black_levels"]:
                failures.append(
                    f"{name}/{case_name}: black levels "
                    f"{result.meta.black_levels} != v1 {ref['black_levels']}")
            if (result.height, result.width) != (ref["height"], ref["width"]):
                failures.append(
                    f"{name}/{case_name}: output size changed")

            for plane_name, getter in PLANES:
                _assert_plane_equal(
                    f"{name}/{case_name}/{plane_name}",
                    getter(result), ref[plane_name], failures)
            for mask_name, getter in MASKS:
                _assert_mask_equal(
                    f"{name}/{case_name}/{mask_name}",
                    getter(result), ref[mask_name], failures)

    print(f"golden baseline : {os.path.relpath(GOLDEN, ROOT)} "
          f"({golden['decoder']} {golden['api_version']})")
    print(f"current decoder : rawdecode {DECODER_VERSION} via the adapter")
    print(f"frame/case runs : {checked}")
    if failures:
        print(f"MIGRATION FAIL ({len(failures)} discrepancy(ies)):")
        for f in failures[:20]:
            print("  -", f)
        return 1
    print("MIGRATION OK: v2 linear pixels, masks, window and levels match "
          "the v1 golden reference exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
