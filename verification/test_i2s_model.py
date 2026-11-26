#!/usr/bin/env python3
"""Simulator-free self-test of `reference_models/i2s.py` (issue #451).

Hand-built waveforms with the expected result worked out from the I2S bus
specification, not from the model: an ideal Philips transmission decodes to
the frames sent (full-scale extremes included), and each defect the model
claims to catch is caught for its own reason -- the missing one-BCLK delay,
a late WS/SD change (set-up), a lopsided BCLK, a short or long slot, and a
nonzero pad. Run by `npm run lint`. Stdlib only.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.i2s import I2sReceiver, encode_ideal  # noqa: E402
from reference_models.waveform import Signal  # noqa: E402

T = 320.0  # 16 cycles of 20 ns
FRAMES = [(0, 0), (0x7FFF, -32768), (-32768, 0x7FFF), (1, -1), (0x1234, -0x1234), (0x5555, -0x5556)]


def build(frames=FRAMES, **kw):
    bclk, ws, sd = Signal(0, "bclk"), Signal(0, "ws"), Signal(0, "sd")
    end = encode_ideal(bclk, ws, sd, 1000.0, T, frames, **kw)
    return bclk, ws, sd, end


def decode(sig, end, **kw):
    bclk, ws, sd = sig
    return I2sReceiver(**kw).decode(bclk, ws, sd, 0.0, end)


def kinds(r):
    return sorted({v.kind for v in r.violations})


class Nominal(unittest.TestCase):
    def test_ideal_transmission_decodes(self):
        b, w, s, end = build()
        r = decode((b, w, s), end)
        self.assertEqual(r.violations, [])
        self.assertAlmostEqual(r.period_ns, T)
        # the first slot has no WS edge before it and the last none after
        # it: what decodes is the sent run from frame 0's right word on
        self.assertEqual(
            r.samples(),
            [("R", 0), ("L", 32767), ("R", -32768), ("L", -32768), ("R", 32767),
             ("L", 1), ("R", -1), ("L", 4660), ("R", -4660), ("L", 21845)],
        )
        self.assertEqual(r.frames(), [(32767, -32768), (-32768, 32767), (1, -1), (4660, -4660)])

    def test_full_scale_extremes_decode_exactly(self):
        b, w, s, end = build([(0, 0), (0x7FFF, -32768), (-32768, 0x7FFF), (0, 0)])
        got = decode((b, w, s), end).samples()
        self.assertEqual(
            got, [("R", 0), ("L", 32767), ("R", -32768), ("L", -32768), ("R", 32767), ("L", 0)])

    def test_channels_alternate_left_first(self):
        b, w, s, end = build()
        ch = [c for c, _v in decode((b, w, s), end).samples()]
        self.assertTrue(all(a != b2 for a, b2 in zip(ch, ch[1:])))
        self.assertEqual(ch[:2], ["R", "L"])

    def test_msb_follows_the_ws_edge_by_one_bclk(self):
        # a single word 0x8000 then zeros: its MSB is the only 1. Delayed
        # (correct) framing decodes it as 0x8000 = -32768.
        b, w, s, end = build([(0, 0), (-32768, 0), (0, 0), (0, 0)])
        got = [v for _c, v in decode((b, w, s), end).samples()]
        self.assertIn(-32768, got)


class Rejects(unittest.TestCase):
    def test_no_one_bclk_delay_is_caught(self):
        # MSB at the WS edge (left-justified): the receiver reads every word
        # one bit late, so what it decodes is not what was sent
        b, w, s, end = build(ws_delay=False)
        r = decode((b, w, s), end)
        good_b, good_w, good_s, good_end = build()
        good = decode((good_b, good_w, good_s), good_end)
        self.assertNotEqual([v for _c, v in r.samples()], [v for _c, v in good.samples()])

    def test_late_data_change_violates_setup(self):
        b, w, s, end = build(ws_lead_ns=0.4 * T)  # WS moves 0.4 T after the falling edge
        r = decode((b, w, s), end)
        self.assertIn("setup", kinds(r))

    def test_lopsided_bclk_violates_duty(self):
        bclk, ws, sd = Signal(0), Signal(0), Signal(0)
        t = 1000.0
        for _ in range(100):
            bclk.add(t, 0)
            bclk.add(t + 0.8 * T, 1)  # low 0.8 T, high 0.2 T
            t += T
        r = decode((bclk, ws, sd), t)
        self.assertIn("duty", kinds(r))

    def test_wandering_period_is_caught(self):
        bclk, ws, sd = Signal(0), Signal(0), Signal(0)
        t = 1000.0
        for i in range(100):
            p = T * (1.05 if i == 50 else 1.0)
            bclk.add(t, 0)
            bclk.add(t + p / 2, 1)
            t += p
        self.assertIn("period", kinds(decode((bclk, ws, sd), t)))

    def test_short_slot_is_caught(self):
        b, w, s, end = build(slot_bits=31)
        self.assertIn("slot-length", kinds(decode((b, w, s), end)))

    def test_nonzero_pad_is_caught(self):
        b, w, s, end = build([(1, 1)] * 4, data_bits=17)
        self.assertIn("pad", kinds(decode((b, w, s), end)))


if __name__ == "__main__":
    unittest.main()
