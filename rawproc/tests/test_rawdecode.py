"""rawdecode v2 contract tests.

These tests pin the interface changes of the decoder upgrade itself:
black levels, as-shot white-balance coefficients and the active-pixel
window must each be validated explicitly.  A malformed contract raises a
specific error — the decoder never completes missing data with defaults.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rawproc import raw_adapter
from rawproc.errors import RawIOError
from rawproc.rawdecode import (
    DECODER_VERSION,
    LevelError,
    StreamError,
    WhiteBalanceError,
    WindowError,
    decode_sidecar,
)

_VALID = {
    "width": 4, "height": 4, "dtype": "<u2",
    "cfa_origin": [0, 0],
    "black_levels": {"r": 256, "g1": 260, "g2": 256, "b": 264},
    "white_level": 4096,
    "crop_origin": [0, 0], "crop_size": [4, 4],
    "orientation": 1, "raw_file": "x.raw",
}


def _write_case(tmp, payload, raw_samples=16):
    raw = os.path.join(tmp, "x.raw")
    with open(raw, "wb") as fh:
        fh.write(b"\x00\x01" * raw_samples)
    with open(os.path.join(tmp, "x.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return os.path.join(tmp, "x.json")


class DecodeHappyPathTest(unittest.TestCase):
    def test_frame_carries_explicit_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = dict(_VALID)
            payload["as_shot_wb"] = [1.8, 1.0, 1.4]
            sidecar = _write_case(tmp, payload)
            frame = decode_sidecar(sidecar)
        self.assertEqual(frame.decoder_version, DECODER_VERSION)
        self.assertEqual(frame.sensor_height, 4)
        self.assertEqual(frame.levels.black, (256, 260, 256, 264))
        self.assertEqual(frame.levels.white, (4096,) * 4)
        self.assertEqual(frame.window.origin, (0, 0))
        self.assertEqual(frame.window.size, (4, 4))
        self.assertEqual(frame.as_shot_wb.as_tuple(), (1.8, 1.0, 1.4))
        self.assertEqual(len(frame.pixels), 4)
        self.assertEqual(len(frame.pixels[0]), 4)

    def test_active_window_is_sliced_inside_sensor(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = dict(_VALID)
            payload.update(crop_origin=[1, 2], crop_size=[2, 2])
            sidecar = _write_case(tmp, payload)
            frame = decode_sidecar(sidecar)
        active = frame.active_pixels()
        self.assertEqual(len(active), 2)
        self.assertEqual(len(active[0]), 2)
        self.assertEqual(
            raw_adapter.working_window(frame), ((1, 2), (2, 2)))

    def test_per_channel_white_overrides_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = dict(_VALID)
            payload["white_levels"] = {"b": 3000}
            sidecar = _write_case(tmp, payload)
            frame = decode_sidecar(sidecar)
        self.assertEqual(frame.levels.white[3], 3000)
        self.assertEqual(frame.levels.white[0], 4096)


class BlackLevelContractTest(unittest.TestCase):
    def test_missing_black_channel_is_rejected_not_defaulted(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            del payload["black_levels"]["g2"]
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(LevelError) as ctx:
                decode_sidecar(sidecar)
        self.assertIn("g2", str(ctx.exception))
        self.assertIn("default", str(ctx.exception))

    def test_missing_black_levels_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            del payload["black_levels"]
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(LevelError):
                decode_sidecar(sidecar)

    def test_white_not_above_black_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload["white_level"] = 200
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(LevelError):
                decode_sidecar(sidecar)

    def test_missing_white_level_is_rejected_not_defaulted(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            del payload["white_level"]
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(LevelError):
                decode_sidecar(sidecar)


class WhiteBalanceContractTest(unittest.TestCase):
    def test_absent_as_shot_wb_is_none_not_unit_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = decode_sidecar(_write_case(tmp, dict(_VALID)))
        self.assertIsNone(frame.as_shot_wb)
        self.assertIsNone(raw_adapter.as_shot_white_balance(frame))

    def test_partial_wb_triple_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload["as_shot_wb"] = [1.8, 1.0]
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(WhiteBalanceError):
                decode_sidecar(sidecar)

    def test_non_positive_wb_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload["as_shot_wb"] = [1.8, 0.0, 1.4]
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(WhiteBalanceError):
                decode_sidecar(sidecar)

    def test_adapter_passes_valid_wb_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload["as_shot_wb"] = [2.0, 1.0, 1.5]
            frame = decode_sidecar(_write_case(tmp, payload))
        self.assertEqual(raw_adapter.as_shot_white_balance(frame),
                         (2.0, 1.0, 1.5))


class ActiveWindowContractTest(unittest.TestCase):
    def test_window_escaping_sensor_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload.update(crop_origin=[2, 2], crop_size=[4, 4])
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(WindowError):
                decode_sidecar(sidecar)

    def test_missing_window_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            del payload["crop_size"]
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(WindowError):
                decode_sidecar(sidecar)

    def test_negative_origin_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload.update(crop_origin=[-1, 0], crop_size=[2, 2])
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(WindowError):
                decode_sidecar(sidecar)


class StreamContractTest(unittest.TestCase):
    def test_truncated_stream_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sidecar = _write_case(tmp, dict(_VALID), raw_samples=15)
            with self.assertRaises(StreamError) as ctx:
                decode_sidecar(sidecar)
        self.assertIn("bytes", str(ctx.exception))

    def test_unsupported_dtype_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload["dtype"] = "<u4"
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(StreamError):
                decode_sidecar(sidecar)

    def test_missing_raw_file_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload["raw_file"] = "missing.raw"
            with open(os.path.join(tmp, "x.json"), "w") as fh:
                json.dump(payload, fh)
            with self.assertRaises(StreamError):
                decode_sidecar(os.path.join(tmp, "x.json"))


class AdapterBoundaryTest(unittest.TestCase):
    def test_adapter_translates_decoder_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            del payload["black_levels"]["b"]
            sidecar = _write_case(tmp, payload)
            with self.assertRaises(RawIOError) as ctx:
                raw_adapter.decode_frame(sidecar)
        self.assertIn(DECODER_VERSION, str(ctx.exception))

    def test_meta_projection_round_trips_levels_and_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = json.loads(json.dumps(_VALID))
            payload.update(crop_origin=[1, 1], crop_size=[3, 3])
            frame = decode_sidecar(_write_case(tmp, payload))
            meta = raw_adapter.frame_to_meta(frame)
        self.assertEqual(meta.black_levels,
                         {"r": 256, "g1": 260, "g2": 256, "b": 264})
        self.assertEqual(meta.crop_origin, (1, 1))
        self.assertEqual(meta.crop_size, (3, 3))
        self.assertEqual(meta.extra["decoder_version"], DECODER_VERSION)

    def test_levels_for_index_out_of_range_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = decode_sidecar(_write_case(tmp, dict(_VALID)))
        with self.assertRaises(RawIOError):
            raw_adapter.levels_for_index(frame, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
