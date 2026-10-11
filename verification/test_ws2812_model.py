#!/usr/bin/env python3
"""Simulator-free self-test of `reference_models/ws2812.py` (issue #141).

Hand-built waveforms with expected results worked out from the WS2812B
datasheet table, not from the model: nominal frames decode, pulses on each
window edge pass, pulses just outside each window fail for the right reason,
a dropped bit and a short reset are caught, and an unlatched frame is not
counted. Run by `npm run lint`. Stdlib only.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.waveform import Signal  # noqa: E402
from reference_models.ws2812 import (  # noqa: E402
    RES_MIN_NS,
    Ws2812Decoder,
    encode_frame,
)

LEAD = 60_000.0  # a leading reset, above RES
PIXELS = [(0x00, 0xFF, 0xA5), (0x12, 0x34, 0x56)]


def frame_signal(pixels=PIXELS, **kw):
    sig = Signal(0, name="din")
    end = encode_frame(sig, pixels, LEAD, **kw)
    return sig, end


def decode(sig, end, **kw):
    return Ws2812Decoder(**kw).decode(sig, 0.0, end)


def kinds(result):
    return sorted({v.kind for v in result.violations})


class Nominal(unittest.TestCase):
    def test_nominal_frame_decodes(self):
        sig, end = frame_signal()
        r = decode(sig, end)
        self.assertEqual(r.violations, [])
        self.assertEqual(len(r.latched_frames), 1)
        self.assertEqual(r.latched_frames[0].pixels(), PIXELS)

    def test_two_frames(self):
        sig = Signal(0)
        t = encode_frame(sig, PIXELS, LEAD)
        end = encode_frame(sig, [(1, 2, 3)], t)
        r = decode(sig, end)
        self.assertEqual(r.violations, [])
        self.assertEqual([f.pixels() for f in r.latched_frames], [PIXELS, [(1, 2, 3)]])

    def test_bit_order_is_grb_msb_first(self):
        # one pixel G=0x80, R=0, B=0x01: the first bit and the last bit are 1
        sig, end = frame_signal([(0x80, 0x00, 0x01)])
        bits = [b.value for b in decode(sig, end).frames[0].bits]
        self.assertEqual(bits, [1] + [0] * 22 + [1])

    def test_window_edges_pass(self):
        # T0H 250 / T0L 1000 (period 1250), T1H 950 / T1L 300 (period 1250)
        sig, end = frame_signal(t0h=250.0, t0l=1000.0, t1h=950.0, t1l=300.0)
        self.assertEqual(decode(sig, end).violations, [])
        sig, end = frame_signal(t0h=550.0, t0l=700.0, t1h=650.0, t1l=600.0)
        self.assertEqual(decode(sig, end).violations, [])


class Rejects(unittest.TestCase):
    def test_short_t1h_is_unreadable(self):
        sig, end = frame_signal(t1h=640.0)
        r = decode(sig, end)
        self.assertEqual(kinds(r), ["high"])

    def test_long_t0h_is_unreadable(self):
        sig, end = frame_signal(t0h=560.0, t0l=690.0)
        self.assertIn("high", kinds(decode(sig, end)))

    def test_t0l_out_of_window(self):
        sig, end = frame_signal(t0l=690.0)
        self.assertEqual(kinds(decode(sig, end)), ["low"])

    def test_t1l_out_of_window(self):
        sig, end = frame_signal(t1l=610.0)
        self.assertEqual(kinds(decode(sig, end)), ["low"])

    def test_dropped_bit(self):
        sig, end = frame_signal(drop_bit_at=5)
        r = decode(sig, end)
        self.assertIn("partial-pixel", kinds(r))

    def test_short_reset_between_frames(self):
        # 20 us between frames: longer than any TL, shorter than RES
        sig = Signal(0)
        t = encode_frame(sig, PIXELS, LEAD, reset_ns=20_000.0)
        end = encode_frame(sig, PIXELS, t)
        r = decode(sig, end)
        self.assertIn("low", kinds(r))
        self.assertEqual(len(r.latched_frames), 1)  # both frames run together
        self.assertEqual(len(r.latched_frames[0].bits), 2 * 48)

    def test_short_leading_reset(self):
        sig = Signal(0)
        end = encode_frame(sig, PIXELS, 10_000.0)
        self.assertIn("leading-reset", kinds(decode(sig, end)))
        self.assertNotIn("leading-reset", kinds(decode(sig, end, require_leading_reset=False)))

    def test_unlatched_frame_not_counted(self):
        sig, end = frame_signal()
        r = decode(sig, end - RES_MIN_NS)  # cut the capture inside the reset
        self.assertEqual(r.latched_frames, [])
        self.assertEqual(len(r.frames), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
