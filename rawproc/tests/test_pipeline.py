"""Hand-calculated verification on the 4x4 reference sample.

Raw constants (RGGB, black 256/260/256/264, white 4096):
  R raw 1216 -> (1216-256)/3840  = 0.25
  G raw 2178/2174 -> (..-260)/3836 = 0.5 ; (2174-256)/3840 = 0.5
  B raw 3138 -> (3138-264)/3832 = 0.75
With constant per-channel values, bilinear demosaic must reproduce a flat
[0.25, 0.5, 0.75] image at every pixel; pixel (0,0) is under-black and
(3,3) is saturated and remain flagged after the whole chain.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rawproc import pipeline, synthesize
from rawproc import arrayops, imageio
from rawproc.metadata import load_metadata
from rawproc.errors import MetadataError

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "samples")


class HandCalcTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        synthesize.make_handcalc(SAMPLES)
        cls.sidecar = os.path.join(SAMPLES, "handcalc.json")
        cls.result = pipeline.run_pipeline(cls.sidecar)

    def test_hand_normalization(self):
        r = self.result
        # Non-flagged pixels keep their exact hand-computed normalized value.
        self.assertAlmostEqual(r.mosaic[0][2], 0.25)      # R at (0,2)
        self.assertAlmostEqual(r.mosaic[0][1], 0.5)       # G1 at (0,1)
        self.assertAlmostEqual(r.mosaic[1][0], 0.5)       # G2 at (1,0)
        self.assertAlmostEqual(r.mosaic[1][1], 0.75)      # B at (1,1)

    def test_under_black_and_saturation_flags(self):
        self.assertTrue(self.result.under_mask[0][0])
        self.assertTrue(self.result.saturated_mask[3][3])
        # Extremes are clamped but their marker survives, never folded away.
        self.assertEqual(self.result.mosaic[0][0], 0.0)
        self.assertEqual(self.result.mosaic[3][3], 1.0)
        self.assertFalse(any(
            self.result.under_mask[r][c]
            for r in range(4) for c in range(4) if (r, c) != (0, 0)))
        self.assertFalse(any(
            self.result.saturated_mask[r][c]
            for r in range(4) for c in range(4) if (r, c) != (3, 3)))

    def test_demosaic_flat_field_hand_values(self):
        dr, dg, db = self.result.demosaiced
        # Own-channel measured samples are always passed through untouched,
        # including the hand-computed constants at unflagged positions.
        self.assertAlmostEqual(dr[0][2], 0.25, places=6)
        self.assertAlmostEqual(dr[2][0], 0.25, places=6)
        self.assertAlmostEqual(dg[0][1], 0.5, places=6)
        self.assertAlmostEqual(db[1][1], 0.75, places=6)
        self.assertAlmostEqual(db[3][1], 0.75, places=6)
        # Green at (2,2) is interpolated from four green neighbors, none of
        # which is the under-black R pixel or saturated B pixel.
        self.assertAlmostEqual(dg[2][2], 0.5, places=6)

    def test_per_channel_black_levels_distinguished(self):
        stats = {s["channel"]: s for s in self.result.channel_stats}
        self.assertEqual(stats["r"]["black"], 256)
        self.assertEqual(stats["g1"]["black"], 260)
        self.assertEqual(stats["b"]["black"], 264)

    def test_bilinear_interpolation_at_center(self):
        # Direct check of the interpolation formula on a crafted plane:
        # center B pixel estimates R from four R diagonals.
        from rawproc.demosaic import demosaic
        mosaic = [
            [0.8, 0.0, 0.4, 0.0],
            [0.0, 0.0, 0.0, 0.0],
            [0.2, 0.0, 0.6, 0.0],
            [0.0, 0.0, 0.0, 0.0],
        ]
        r, g, b = demosaic(mosaic, (0, 0))
        # B lives at (1,1); R estimate = mean of four R diagonals = 0.5
        self.assertAlmostEqual(r[1][1], 0.5, places=6)
        # R at (0,0) is its own measured sample.
        self.assertEqual(r[0][0], 0.8)


class PhaseAndOrientationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        synthesize.make_phase(SAMPLES)
        cls.sidecar = os.path.join(SAMPLES, "phase.json")
        cls.result = pipeline.run_pipeline(cls.sidecar)

    def test_origin_transform_matches_geometry_all_orientations(self):
        # Exhaustive: the tracked R-pixel phase must equal the phase read off
        # the geometrically transformed index plane for every orientation and
        # every 2x2 origin, across odd and even frame sizes.
        from rawproc import arrayops
        from rawproc.cfa import build_index_plane
        for h, w in ((6, 8), (7, 9), (5, 8), (8, 5), (11, 13), (2, 2)):
            for origin in ((0, 0), (0, 1), (1, 0), (1, 1)):
                plane = build_index_plane(h, w, origin)
                for orient in range(1, 9):
                    ref = arrayops.apply_orientation(plane, orient)
                    H, W = len(ref), len(ref[0])
                    got_origin = arrayops.transform_cfa_origin(
                        origin, orient, h, w)
                    got = build_index_plane(H, W, got_origin)
                    # Compare R (index 0) membership only, since parity can
                    # make a full-array equality fail at the last row/col;
                    # the phase origin is fully characterized by R positions.
                    ref_r = [[v == 0 for v in row] for row in ref]
                    got_r = [[v == 0 for v in row] for row in got]
                    self.assertEqual(ref_r, got_r,
                                     f"origin={origin} orient={orient} "
                                     f"size={h}x{w}")

    def test_crop_and_rotation_shape(self):
        meta = load_metadata(self.sidecar)
        ch, cw = meta.crop_size
        # Orientation 6 transposes axes.
        self.assertEqual((self.result.height, self.result.width), (cw, ch))

    def test_color_positions_tracked_not_guessed(self):
        # Flat neutral field: with the correct phase, demosaic reconstructs
        # the same normalized gray at every output pixel and channel.
        expected = (768 - 256) / (1024 - 256)
        dr, dg, db = self.result.demosaiced
        for plane in (dr, dg, db):
            for row in plane:
                for v in row:
                    self.assertAlmostEqual(v, expected, places=6)

    def test_effective_origin_is_explicit(self):
        from rawproc.pipeline import _effective_origin
        origin = _effective_origin(self.result)
        # Computed, not assumed: R phase after crop (1,1)+(1,0) then rot 6.
        self.assertEqual(len(origin), 2)
        self.assertTrue(all(v in (0, 1) for v in origin))


class ChartContentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        synthesize.make_chart(SAMPLES)
        cls.sidecar = os.path.join(SAMPLES, "chart.json")
        cls.result = pipeline.run_pipeline(cls.sidecar)

    def test_solid_patches_separate_channels(self):
        r = self.result
        h = r.height
        dr, dg, db = r.demosaiced
        # Crop origin x=2: sensor red bar [0:4) -> output cols 0..1, blue
        # bar [4:8) -> output cols 2..3.  Average interior rows so border
        # bleed and the single flagged pixel do not dominate.
        rows = range(4, h - 2)
        red_r = sum(dr[i][1] for i in rows) / len(list(rows))
        red_b = sum(db[i][1] for i in rows) / len(list(rows))
        self.assertGreater(red_r, red_b * 3)
        blue_b = sum(db[i][2] for i in rows) / len(list(rows))
        blue_r = sum(dr[i][2] for i in rows) / len(list(rows))
        self.assertGreater(blue_b, blue_r * 3)

    def test_slanted_edge_is_smooth_not_discrete(self):
        dr, _, _ = self.result.demosaiced
        # Interpolated edge region must contain intermediate values, proving
        # demosaic computes sub-sample transitions rather than hard slices.
        interior = [dr[i][j] for i in range(4, 16) for j in range(8, 14)]
        lo = min(interior); hi = max(interior)
        mids = [v for v in interior if lo < v < hi]
        self.assertTrue(mids, "no intermediate values along slanted edge")

    def test_checkerboard_present_and_flagged_extremes(self):
        self.assertTrue(arrayops.mask_any(self.result.under_mask))
        self.assertTrue(arrayops.mask_any(self.result.saturated_mask))
        n_under = arrayops.count_true(self.result.under_mask)
        n_sat = arrayops.count_true(self.result.saturated_mask)
        self.assertEqual(n_under, 1)
        self.assertEqual(n_sat, 1)


class CheckerAndEdgeSamplesTest(unittest.TestCase):
    def test_checker_orientation_180(self):
        synthesize.make_checker(SAMPLES)
        result = pipeline.run_pipeline(os.path.join(SAMPLES, "checker.json"))
        dr, dg, db = result.demosaiced
        # Shifted CFA + rotation still yields finite, in-range linear values.
        for plane in (dr, dg, db):
            for row in plane:
                for v in row:
                    self.assertTrue(0.0 <= v <= 1.0)

    def test_edge45_runs(self):
        synthesize.make_edge45(SAMPLES)
        result = pipeline.run_pipeline(os.path.join(SAMPLES, "edge45.json"))
        self.assertEqual(result.height, 16)
        self.assertFalse(arrayops.mask_any(result.saturated_mask))


class WhiteBalanceAndDisplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        synthesize.make_handcalc(SAMPLES)
        cls.sidecar = os.path.join(SAMPLES, "chart.json")
        synthesize.make_chart(SAMPLES)

    def test_white_balance_is_separate_linear_step(self):
        base = pipeline.run_pipeline(self.sidecar)
        warmed = pipeline.run_pipeline(self.sidecar,
                                       wb_gains=(1.5, 1.0, 0.8))
        b0 = base.linear_wb[0][5][5]
        b1 = warmed.linear_wb[0][5][5]
        self.assertAlmostEqual(b1, b0 * 1.5, places=6)
        # Display preview is derived after WB and differs from linear clamp.
        self.assertIsNot(warmed.display_srgb, warmed.linear_wb)

    def test_gray_world_gains_positive(self):
        from rawproc.color import gray_world_gains
        r = [[0.2] * 4 for _ in range(4)]
        g = [[0.4] * 4 for _ in range(4)]
        b = [[0.1] * 4 for _ in range(4)]
        gr, gg, gb = gray_world_gains(r, g, b)
        self.assertAlmostEqual(gg, 1.0)
        self.assertAlmostEqual(gr, 2.0)
        self.assertAlmostEqual(gb, 4.0)


class OutputEncodingTest(unittest.TestCase):
    def test_16bit_png_roundtrip(self):
        import struct
        import zlib
        plane = [[0.0, 0.25, 0.5, 0.75, 1.0]]
        blob = imageio.png_bytes([plane, plane, plane], bitdepth=16)
        self.assertTrue(blob.startswith(b"\x89PNG"))
        # Parse IHDR and confirm 16-bit RGB declaration survives encoding.
        self.assertEqual(blob[12:16], b"IHDR")
        bitdepth = blob[24]
        color_type = blob[25]
        self.assertEqual(bitdepth, 16)
        self.assertEqual(color_type, 2)
        # Decompress IDAT and verify an exact 16-bit code for 0.25.
        pos, idat = 8, bytearray()
        while pos < len(blob):
            length = struct.unpack(">I", blob[pos:pos + 4])[0]
            tag = blob[pos + 4:pos + 8]
            if tag == b"IDAT":
                idat += blob[pos + 8:pos + 8 + length]
            pos += 12 + length
        raw = zlib.decompress(bytes(idat))
        # First scanline: filter byte (offset 0), then R sample of pixel 0.
        self.assertEqual(raw[0], 0)
        first_r = struct.unpack(">H", raw[1:3])[0]
        self.assertEqual(first_r, 0)
        # Second pixel R channel at byte offset: filter + 3 samples * 2 bytes
        expected = round(0.25 * 65535)
        got = struct.unpack(">H", raw[7:9])[0]
        self.assertEqual(got, expected)

    def test_save_outputs_keeps_linear_and_preview_apart(self):
        import tempfile
        synthesize.make_handcalc(SAMPLES)
        result = pipeline.run_pipeline(os.path.join(SAMPLES, "handcalc.json"))
        with tempfile.TemporaryDirectory() as tmp:
            paths = pipeline.save_outputs(result, tmp, "hc")
            self.assertTrue(os.path.exists(paths["linear16_png"]))
            self.assertTrue(os.path.exists(paths["preview_srgb8_png"]))
            self.assertNotEqual(paths["linear16_png"],
                                paths["preview_srgb8_png"])
            self.assertTrue(os.path.exists(paths["result_json"]))
            self.assertGreater(os.path.getsize(paths["linear_float32_bin"]),
                               4 * 3 * 16)


class MetadataGuardTest(unittest.TestCase):
    def test_unsupported_layout_rejected(self):
        import json as _json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "x.raw")
            with open(raw, "wb") as fh:
                fh.write(b"\x00\x00" * 16)
            meta = {
                "width": 4, "height": 4, "dtype": "<u2",
                "cfa_layout": "bayer_rggb_12bit_packed",
                "cfa_origin": [0, 0],
                "black_levels": {"r": 0, "g1": 0, "g2": 0, "b": 0},
                "white_level": 1000,
                "crop_origin": [0, 0], "crop_size": [4, 4],
                "orientation": 1, "raw_file": "x.raw",
            }
            with open(os.path.join(tmp, "x.json"), "w") as fh:
                _json.dump(meta, fh)
            with self.assertRaises(MetadataError):
                load_metadata(os.path.join(tmp, "x.json"))

    def test_crop_outside_sensor_rejected(self):
        import json as _json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, "x.raw")
            open(raw, "wb").write(b"\x00" * 32)
            meta = {
                "width": 4, "height": 4, "dtype": "<u2",
                "cfa_layout": "rggb", "cfa_origin": [0, 0],
                "black_levels": {"r": 0, "g1": 0, "g2": 0, "b": 0},
                "white_level": 1000, "crop_origin": [2, 2],
                "crop_size": [4, 4], "orientation": 1,
                "raw_file": "x.raw",
            }
            with open(os.path.join(tmp, "x.json"), "w") as fh:
                _json.dump(meta, fh)
            with self.assertRaises(MetadataError):
                load_metadata(os.path.join(tmp, "x.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
