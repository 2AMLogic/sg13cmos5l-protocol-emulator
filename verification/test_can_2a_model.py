#!/usr/bin/env python3
"""Simulator-free self-test of `reference_models/can_2a.py` (issue #450).

Expected results worked out from the CAN 2.0A framing description, not
from the model: the two CRC-15 implementations agree on random messages
and the message-plus-CRC zero property holds; a nominal frame encodes and
decodes back to the same fields; a frame with long bit runs carries stuff
bits; a flipped data bit is a CRC violation; a flipped stuff bit is a
stuff violation; a dominant CRC delimiter is a form violation; and a
1.2x-stretched copy of a good waveform is flagged by the bit-timing bound.
Run by `npm run lint`. Stdlib only.
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.waveform import Signal  # noqa: E402
from reference_models.can_2a import (  # noqa: E402
    CanReceiver,
    crc15_shift,
    crc15_divide,
    destuff_bits,
    encode_frame,
    frame_bits,
    stuff_bits,
)

PER_NS = 8000.0  # a nominal bit period for the waveform-level tests


def waveform(bits, period=PER_NS, idle_bits=4, stretch=1.0):
    sig = Signal(1, name="can")
    t = 0.0
    for b in bits:
        sig.add(t, b)
        t += period * stretch
    sig.add(t + idle_bits * period, 1)
    return sig, t + (idle_bits + 2) * period


def decode(bits, **kw):
    sig, end = waveform(bits, **kw)
    return CanReceiver(PER_NS).decode(sig, 0.0, end)


class TestCrc(unittest.TestCase):
    def test_implementations_agree(self):
        rnd = random.Random(450)
        for _ in range(80):
            n = rnd.randrange(1, 130)
            bits = [rnd.randrange(2) for _ in range(n)]
            self.assertEqual(crc15_shift(bits), crc15_divide(bits), bits)

    def test_zero_property(self):
        for can_id, data in ((0x5A5, bytes([0x11, 0x1F, 0x22])),
                             (0x123, bytes([0xAB, 0xCD, 0x5A])),
                             (0x000, bytes()),
                             (0x7FF, bytes(range(8)))):
            bits = frame_bits(can_id, data)
            from reference_models.can_2a import crc_sequence
            self.assertEqual(crc15_shift(bits + crc_sequence(bits)), 0)


class TestStuffing(unittest.TestCase):
    def test_stuffing_breaks_long_runs(self):
        bits = [0] * 20
        stuffed = stuff_bits(bits)
        # no run longer than 6 anywhere (5 data + 1 stuff)
        run, best = 1, 1
        for a, b in zip(stuffed, stuffed[1:]):
            run = run + 1 if a == b else 1
            best = max(best, run)
        self.assertLessEqual(best, 6)

    def test_destuff_roundtrip(self):
        bits = [0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 1]
        out, err = destuff_bits(stuff_bits(bits))
        self.assertIsNone(err)
        self.assertEqual(out, bits)


class TestDecode(unittest.TestCase):
    def test_nominal_frame_decodes(self):
        for can_id, data in ((0x5A5, bytes([0x11, 0x1F, 0x22])),
                             (0x123, bytes([0xAB, 0xCD, 0x5A]))):
            wire, tail = encode_frame(can_id, data)
            res = decode(wire + tail)
            self.assertEqual(res.violations, [], [res.violations, can_id])
            self.assertEqual(len(res.frames), 1)
            f = res.frames[0]
            self.assertEqual(f.can_id, can_id)
            self.assertEqual(f.rtr, 0)
            self.assertEqual(f.dlc, len(data))
            self.assertEqual(f.data, list(data))
            self.assertTrue(f.crc_ok)
            self.assertEqual(f.ack_slot_level, 1)

    def test_frame_with_stuff_bits_decodes(self):
        # long runs force stuff bits onto the wire
        data = bytes([0x00, 0xFF, 0x00])
        wire, tail = encode_frame(0x300, data)
        self.assertGreater(len(wire), 19 + 24 + 15, "expected stuff bits")
        res = decode(wire + tail)
        self.assertEqual(res.violations, [])
        f = res.frames[0]
        self.assertEqual((f.can_id, f.data), (0x300, [0, 0xFF, 0]))

    def test_flipped_data_bit_is_a_crc_violation(self):
        wire, tail = encode_frame(0x5A5, bytes([0x11, 0x1F, 0x22]))
        bits = list(wire + tail)
        bits[25] ^= 1
        res = decode(bits)
        self.assertIn("crc", {v.kind for v in res.violations})
        self.assertFalse(res.frames[0].crc_ok)

    def test_flipped_stuff_bit_is_a_stuff_violation(self):
        wire, tail = encode_frame(0x5A5, bytes([0x11, 0x1F, 0x22]))
        w = list(wire)
        run, last = 0, None
        for i, b in enumerate(w):
            if run == 5:
                w[i] = last  # the stuff bit extends the run: six equal
                break
            run = run + 1 if b == last else 1
            last = b
        else:
            self.fail("the demo frame has no stuff bit to corrupt")
        res = decode(w + tail)
        self.assertIn("stuff", {v.kind for v in res.violations})

    def test_dominant_delimiter_is_a_form_violation(self):
        wire, tail = encode_frame(0x5A5, bytes([0x11, 0x1F, 0x22]))
        bits = list(wire + tail)
        bits[len(wire)] = 0  # the CRC delimiter
        res = decode(bits)
        self.assertIn("form", {v.kind for v in res.violations})

    def test_stretched_waveform_fails_the_bit_timing_bound(self):
        wire, tail = encode_frame(0x5A5, bytes([0x11, 0x1F, 0x22]))
        res = decode(wire + tail, stretch=1.2)
        self.assertIn("bit-timing", {v.kind for v in res.violations})


if __name__ == "__main__":
    unittest.main(verbosity=2)
