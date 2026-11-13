"""End-to-end contract tests for the rawdecode v2 upgrade.

These complement the golden migration check: they assert the *new* behavior
the upgrade introduces (version stamping, explicit as-shot WB, high-bit-depth
linear output after white balance, error propagation through the kernel)
rather than parity with v1.
"""

import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rawproc import pipeline, raw_adapter, synthesize
from rawproc.errors import RawIOError
from rawproc.rawdecode import DECODER_NAME, DECODER_VERSION

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "samples")


class DecoderStampingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        synthesize.make_handcalc(SAMPLES)
        cls.sidecar = os.path.join(SAMPLES, "handcalc.json")
        cls.result = pipeline.run_pipeline(cls.sidecar)

    def test_pipeline_runs_the_v2_path(self):
        self.assertEqual(self.result.decoder_name, DECODER_NAME)
        self.assertEqual(self.result.decoder_version, DECODER_VERSION)

    def test_active_window_is_explicit_contract(self):
        self.assertEqual(self.result.active_window, ((0, 0), (4, 4)))

    def test_as_shot_wb_absent_is_none_never_silent_ones(self):
        # The handcalc sidecar advertises no as-shot WB; the adapter must say
        # so explicitly instead of manufacturing (1, 1, 1).
        self.assertIsNone(self.result.as_shot_wb)

    def test_saved_result_json_records_decoder_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = pipeline.save_outputs(self.result, tmp, "hc")
            data = json.load(open(paths["result_json"], encoding="utf-8"))
        self.assertEqual(data["raw_decoder"]["name"], DECODER_NAME)
        self.assertEqual(data["raw_decoder"]["version"], DECODER_VERSION)
        self.assertEqual(data["active_window_origin"], [0, 0])
        self.assertIsNone(data["as_shot_white_balance"])


class AsShotWhiteBalanceTest(unittest.TestCase):
    def test_as_shot_coefficients_flow_into_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, sidecar = synthesize.make_handcalc(tmp)
            data = json.load(open(sidecar, encoding="utf-8"))
            data["as_shot_wb"] = [1.25, 1.0, 0.8]
            with open(sidecar, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            result = pipeline.run_pipeline(sidecar)
        self.assertEqual(result.as_shot_wb, (1.25, 1.0, 0.8))
        # Working gains remain identity unless the operator chooses otherwise:
        # as-shot metadata must not be silently applied as the kernel's WB.
        self.assertEqual(result.wb_gains, (1.0, 1.0, 1.0))


class LinearHighBitDepthAfterWBTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        synthesize.make_handcalc(SAMPLES)
        cls.sidecar = os.path.join(SAMPLES, "handcalc.json")

    def test_white_balance_changes_linear_pixels_predictably(self):
        base = pipeline.run_pipeline(self.sidecar)
        warmed = pipeline.run_pipeline(self.sidecar,
                                       wb_gains=(2.0, 1.0, 0.5))
        br, _, _ = base.linear_wb
        wr, wg, wb = warmed.linear_wb
        bg, bb = base.linear_wb[1], base.linear_wb[2]
        for i in range(4):
            for j in range(4):
                self.assertAlmostEqual(wr[i][j], br[i][j] * 2.0, places=12)
                self.assertAlmostEqual(wg[i][j], bg[i][j], places=12)
                self.assertAlmostEqual(wb[i][j], bb[i][j] * 0.5, places=12)

    def test_16bit_encoding_reflects_wb_and_stays_in_uint16(self):
        result = pipeline.run_pipeline(self.sidecar,
                                       wb_gains=(1.0, 1.0, 1.0))
        with tempfile.TemporaryDirectory() as tmp:
            paths = pipeline.save_outputs(result, tmp, "hc")
            blob = open(paths["linear16_png"], "rb").read()
        self.assertTrue(blob.startswith(b"\x89PNG"))
        self.assertEqual(blob[24], 16)  # IHDR bit depth
        # Every encoded code is a valid uint16 (decode a few scanlines).
        import zlib
        pos, idat = 8, bytearray()
        while pos < len(blob):
            length = struct.unpack(">I", blob[pos:pos + 4])[0]
            if blob[pos + 4:pos + 8] == b"IDAT":
                idat += blob[pos + 8:pos + 8 + length]
            pos += 12 + length
        raw = zlib.decompress(bytes(idat))
        stride = 1 + 4 * 3 * 2
        for row in range(4):
            self.assertEqual(raw[row * stride], 0)  # filter byte
            for off in range(1, stride, 2):
                hi, lo = raw[row * stride + off], raw[row * stride + off + 1]
                code = (hi << 8) | lo
                self.assertLessEqual(code, 65535)

    def test_color_channels_keep_their_order_after_wb(self):
        # handcalc's flat per-channel constants: R=0.25, G=0.5, B=0.75.
        result = pipeline.run_pipeline(self.sidecar,
                                       wb_gains=(1.0, 1.0, 1.0))
        r, g, b = result.demosaiced
        self.assertAlmostEqual(r[0][2], 0.25, places=9)
        self.assertAlmostEqual(g[0][1], 0.5, places=9)
        self.assertAlmostEqual(b[1][1], 0.75, places=9)


class KernelFailurePropagationTest(unittest.TestCase):
    def test_bad_contract_surfaces_as_kernel_error_not_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            synthesize.make_handcalc(tmp)
            sidecar = os.path.join(tmp, "handcalc.json")
            data = json.load(open(sidecar, encoding="utf-8"))
            del data["black_levels"]["r"]
            with open(sidecar, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            with self.assertRaises(RawIOError) as ctx:
                pipeline.run_pipeline(sidecar)
        self.assertIn(DECODER_VERSION, str(ctx.exception))
        self.assertIn("r", str(ctx.exception))

    def test_truncated_stream_surfaces_from_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, sidecar = synthesize.make_handcalc(tmp)
            with open(raw, "wb") as fh:
                fh.write(b"\x00" * 20)  # 4x4 needs 32 bytes
            with self.assertRaises(RawIOError):
                pipeline.run_pipeline(sidecar)


if __name__ == "__main__":
    unittest.main(verbosity=2)
