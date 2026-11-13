#!/usr/bin/env bash
# Regenerate tests/golden/golden_v1.json from the PRE-UPGRADE v1 code.
#
# The v1 decoder lived in rawproc/rawio.py + rawproc/metadata.py at the
# commit before the rawdecode v2 upgrade.  This script extracts that package
# into an isolated directory, generates the tiny fixture samples with the v1
# synthesizer and snapshots the v1 pixel results.  It never mixes v1 and v2
# modules on one import path.
#
# Usage (from the project root):
#   bash scripts/regenerate_golden.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V1_REF="${1:-edf9d14}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# The git root may sit above the project root; make the archive path relative
# to the repository rather than assuming they coincide.
GIT_ROOT="$(git -C "$ROOT" rev-parse --show-toplevel)"
PKG_REL="$(realpath --relative-to="$GIT_ROOT" "$ROOT")/rawproc"

echo "v1 source ref: $V1_REF"
# Extract the v1 package contents directly into $WORK/rawproc so that
# `import rawproc` resolves against the isolated checkout with no path mixups.
mkdir -p "$WORK/rawproc"
git -C "$GIT_ROOT" archive "$V1_REF" "$PKG_REL" \
  | tar -x -C "$WORK/rawproc" --strip-components="$(awk -F/ '{print NF}' <<< "$PKG_REL")"
rm -rf "$WORK/rawproc/__pycache__"

cat > "$WORK/make_golden.py" <<'PY'
import json, os, sys
sys.path.insert(0, os.getcwd())
from rawproc import pipeline, synthesize

OUT = sys.argv[1]
SAMPLES = sys.argv[2]
os.makedirs(OUT, exist_ok=True)
os.makedirs(SAMPLES, exist_ok=True)
builders = {
    "handcalc": synthesize.make_handcalc,
    "phase": synthesize.make_phase,
    "chart": synthesize.make_chart,
    "edge45": synthesize.make_edge45,
    "checker": synthesize.make_checker,
}

def snapshot(result, case):
    r, g, b = result.linear_wb
    dr, dg, db = result.demosaiced
    return {
        "wb_case": case,
        "width": result.width, "height": result.height,
        "active_window": [list(result.meta.crop_origin),
                          list(result.meta.crop_size)],
        "black_levels": result.meta.black_levels,
        "mosaic": result.mosaic,
        "under_mask": result.under_mask,
        "saturated_mask": result.saturated_mask,
        "demosaic_r": dr, "demosaic_g": dg, "demosaic_b": db,
        "linear_wb_r": r, "linear_wb_g": g, "linear_wb_b": b,
        "wb_gains": list(result.wb_gains),
    }

golden = {"decoder": "v1-rawio", "api_version": "1.0.0", "frames": {}}
for name, builder in builders.items():
    raw, sidecar = builder(SAMPLES)
    golden["frames"][name] = {
        "raw_bytes": os.path.getsize(raw),
        "identity_gains": snapshot(pipeline.run_pipeline(sidecar), "identity"),
        "manual_gains": snapshot(
            pipeline.run_pipeline(sidecar, wb_gains=(1.5, 1.0, 0.8)),
            "manual_1.5_1.0_0.8"),
        "gray_world": snapshot(
            pipeline.run_pipeline(sidecar, auto_white_balance=True),
            "gray_world"),
    }
with open(os.path.join(OUT, "golden_v1.json"), "w", encoding="utf-8") as fh:
    json.dump(golden, fh)
PY

( cd "$WORK" && python3 -I make_golden.py \
    "$ROOT/tests/golden" "$ROOT/tests/fixtures" )
echo "regenerated $ROOT/tests/golden/golden_v1.json"
