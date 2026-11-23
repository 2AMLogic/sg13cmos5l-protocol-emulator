#!/usr/bin/env python3
"""Simulator-free self-test of `reference_models/dmx512.py` (issue #445).

Hand-built waveforms with expected results worked out from the DMX512
protocol conventions, not from the model: a nominal packet (BREAK, mark,
start code, channel slots) decodes byte for byte with both stop bits high
and zero drift; a short BREAK and a short mark are caught; a slot whose
edges drift past the per-slot bound fails `check_slot` while still
decoding; and the malformed boundary of the test plan -- a next slot
started one bit early, leaving only one stop bit -- is rejected even
though the preceding byte decoded correctly. Run by `npm run lint`.
Stdlib only.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.waveform import Signal  # noqa: E402
from reference_models.dmx512 import (  # noqa: E402
    BIT_PERIOD_NS,
    BREAK_MIN_NS,
    MAB_MIN_NS,
    Dmx512Receiver,
    encode_one_stop_slot,
    encode_packet,
)

P = BIT_PERIOD_NS
LEVELS = [0x00, 0x5A, 0xFF, 0x01, 0x80, 0xA5]
START = 0x00


def packet_signal(levels=LEVELS, break_ns=92_000.0, mab_ns=12_000.0):
    sig = Signal(1, name="dmx")
    encode_packet(START, levels, break_ns=break_ns, mab_ns=mab_ns, line=sig,
                  t0=100_000.0)
    return sig


class Nominal(unittest.TestCase):
    def test_nominal_packet_decodes(self):
        r = Dmx512Receiver().decode(packet_signal())
        self.assertEqual(r.violations, [], r.violations)
        self.assertEqual(len(r.packets), 1)
        pkt = r.packets[0]
        self.assertGreaterEqual(pkt.break_ns, BREAK_MIN_NS)
        self.assertGreaterEqual(pkt.mab_ns, MAB_MIN_NS)
        self.assertEqual(len(pkt.slots), 1 + len(LEVELS))
        self.assertEqual(pkt.slots[0].data, START)
        for slot, want in zip(pkt.slots[1:], LEVELS):
            self.assertEqual(slot.data, want)
            self.assertEqual(slot.stop_samples, (1, 1))
            self.assertTrue(Dmx512Receiver.check_slot(slot))
        self.assertTrue(r.ends_clean)

    def test_every_slot_boundary_on_the_nominal_grid(self):
        r = Dmx512Receiver().decode(packet_signal())
        slots = r.packets[0].slots
        for a, b in zip(slots, slots[1:]):
            self.assertAlmostEqual((b.t_start - a.t_start) / P, 11.0, places=9)
            self.assertIsNotNone(a.pitch_periods)
            self.assertAlmostEqual(a.pitch_periods, 11.0, places=9)
        self.assertIsNone(slots[-1].pitch_periods,
                          "no following slot exists past the capture end")

    def test_zero_level_slot_keeps_two_stop_bits(self):
        # a 0x00 byte is nine consecutive low periods; the stops must
        # still sample high and the pitch stay on the grid
        r = Dmx512Receiver().decode(packet_signal([0x00, 0x00]))
        self.assertEqual(r.violations, [], r.violations)
        pkt = r.packets[0]
        self.assertEqual([s.data for s in pkt.slots], [0x00, 0x00, 0x00])
        for s in pkt.slots:
            self.assertEqual(s.stop_samples, (1, 1))

    def test_two_packets(self):
        sig = Signal(1)
        t = encode_packet(START, [0x11, 0x22], line=sig, t0=50_000.0,
                          break_ns=92_000.0, mab_ns=12_000.0)
        encode_packet(START, [0x33], line=sig, t0=t + 5_000.0,
                      break_ns=92_000.0, mab_ns=12_000.0)
        r = Dmx512Receiver().decode(sig)
        self.assertEqual(r.violations, [], r.violations)
        self.assertEqual(len(r.packets), 2)
        self.assertEqual(r.packets[1].slots[-1].data, 0x33)


class Framing(unittest.TestCase):
    def test_short_break_between_packets_flags_garbage_slots(self):
        # a low longer than a start bit but below the BREAK limit is
        # indistinguishable from a slot start at the waveform (a 0x00
        # slot's start-plus-data low runs nine periods), so the receiver
        # decodes it as a slot and the stop-bit sampling flags it; the
        # next real BREAK still opens the next packet
        sig = Signal(1)
        t = encode_packet(START, [0x5A], line=sig, t0=100_000.0,
                          break_ns=92_000.0, mab_ns=12_000.0)
        sig.add(t, 0)                       # a 60 us low: a break attempt
        sig.add(t + 60_000.0, 1)
        encode_packet(START, [0x3C], line=sig, t0=t + 65_000.0,
                      break_ns=92_000.0, mab_ns=12_000.0)
        r = Dmx512Receiver().decode(sig)
        self.assertEqual(len(r.packets), 2, r.violations)
        self.assertTrue(any(v.kind == "stop" for v in r.violations),
                        "the garbage slot must be flagged by the stop "
                        f"sampling: {r.violations}")
        self.assertEqual([s.data for s in r.packets[1].slots], [START, 0x3C])

    def test_short_mark_is_caught(self):
        r = Dmx512Receiver().decode(packet_signal(mab_ns=3_000.0))
        self.assertTrue(any(v.kind == "mab" for v in r.violations))

    def test_trailing_break_is_reported_not_graded(self):
        # a capture that ends inside a low is flagged as trailing and
        # ends_clean goes False; no packet is fabricated for it
        sig = Signal(1)
        t = encode_packet(START, [0x12], line=sig, t0=100_000.0,
                          break_ns=92_000.0, mab_ns=12_000.0)
        sig.add(t + 1.0, 0)                        # re-enter a BREAK low
        r = Dmx512Receiver().decode(sig)
        self.assertFalse(r.ends_clean)
        self.assertTrue(any(v.kind == "trailing" for v in r.violations))


class Drift(unittest.TestCase):
    def test_drifting_slot_fails_check_but_still_decodes(self):
        # one packet whose every edge is stretched 1.06x: 6% drift, above
        # the 5% bound, while every byte still samples correctly
        levels = [0x0F, 0x33]
        # stretch the packet by rebuilding on the same grid times 1.06
        stretched = Signal(1, name="stretched")
        encode_packet(START, levels, period_ns=P * 1.06, line=stretched,
                      t0=100_000.0, break_ns=92_000.0 * 1.06,
                      mab_ns=12_000.0 * 1.06)
        r = Dmx512Receiver().decode(stretched)
        pkt = r.packets[0]
        self.assertEqual([s.data for s in pkt.slots], [START] + levels)
        graded = [Dmx512Receiver.check_slot(s) for s in pkt.slots]
        self.assertFalse(all(graded),
                         f"6% drift passed check_slot: {pkt.slots}")
        # the drift bound is check_slot's to enforce; the violations list
        # carries the framing consequences only

    def test_nominal_drift_is_zero(self):
        r = Dmx512Receiver().decode(packet_signal())
        for s in r.packets[0].slots:
            self.assertIsNotNone(s.drift_pct)
            self.assertAlmostEqual(s.drift_pct, 0.0, places=6)


class MalformedBoundary(unittest.TestCase):
    def test_one_stop_bit_boundary_rejected_while_byte_decodes(self):
        # the issue's negative control: a next slot started one bit early
        # leaves the previous slot with one stop bit; the previous byte
        # must still decode and the boundary must be rejected
        sig = Signal(1)
        t = encode_packet(START, [0x5A], line=sig, t0=100_000.0,
                          break_ns=92_000.0, mab_ns=12_000.0)
        # 0x5A's packet is one slot; append 0x3C and 0x96 with the early
        # boundary: each loses its second stop bit to the next start
        encode_one_stop_slot([0x3C, 0x96], line=sig, t0=t)
        r = Dmx512Receiver().decode(sig)
        pkt = r.packets[0]
        datas = [s.data for s in pkt.slots]
        self.assertEqual(datas[0], START)
        self.assertEqual(datas[1], 0x5A)
        self.assertEqual(datas[2], 0x3C, "the byte before the boundary "
                         "must still decode correctly")
        self.assertEqual(datas[3], 0x96)
        kinds = {v.kind for v in r.violations}
        self.assertIn("stop", kinds, f"no stop-bit violation: {r.violations}")
        self.assertIn("short-pitch", kinds)
        # the slots that lost their stop bit must fail check_slot
        self.assertFalse(Dmx512Receiver.check_slot(pkt.slots[1]))
        self.assertFalse(Dmx512Receiver.check_slot(pkt.slots[2]))
        self.assertTrue(Dmx512Receiver.check_slot(pkt.slots[3]),
                        "the final slot keeps both stop bits")


if __name__ == "__main__":
    unittest.main(verbosity=2)
