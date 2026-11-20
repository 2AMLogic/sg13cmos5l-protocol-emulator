#!/usr/bin/env python3
"""Simulator-free self-test of `reference_models/nec_ir.py` (issue #448).

Hand-built waveforms with expected results worked out from the NEC
protocol description, not from the model: a nominal frame decodes, a frame
plus a repeat code decodes, window-edge widths pass, just-outside widths
fail for the right reason, a bad inverted byte and a truncated frame are
caught, an off-frequency carrier is flagged, and a frame whose trailing
silence the capture cuts short is not counted as latched. Run by
`npm run lint`. Stdlib only.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.waveform import Signal  # noqa: E402
from reference_models.nec_ir import (  # noqa: E402
    FRAME_SILENCE_MIN_NS,
    SPACE0_NS,
    SPACE1_NS,
    NecIrDecoder,
    encode_frame,
    encode_repeat,
)

ADDR, CMD = 0xA5, 0x3C
TRAILER = 5_000_000.0  # silence appended past the frame, so it latches


def decoded(**kw):
    sig = Signal(0, name="ir")
    end = encode_frame(sig, ADDR, CMD, **kw)
    return NecIrDecoder().decode(sig, 0.0, end + TRAILER)


def kinds(result):
    return sorted({v.kind for v in result.violations})


class Nominal(unittest.TestCase):
    def test_nominal_frame_decodes(self):
        r = decoded()
        self.assertEqual(r.violations, [])
        self.assertEqual(len(r.latched_frames), 1)
        f = r.latched_frames[0]
        self.assertEqual((f.addr, f.cmd), (ADDR, CMD))
        self.assertEqual(f.inv_addr, 0xFF - ADDR)
        self.assertEqual(f.inv_cmd, 0xFF - CMD)

    def test_two_frames(self):
        sig = Signal(0)
        t = encode_frame(sig, ADDR, CMD)
        end = encode_frame(sig, 0x00, 0xFF, t0=t + 30_000_000.0)
        r = NecIrDecoder().decode(sig, 0.0, end + TRAILER)
        self.assertEqual(r.violations, [])
        self.assertEqual([(f.addr, f.cmd) for f in r.latched_frames],
                         [(ADDR, CMD), (0x00, 0xFF)])

    def test_bit_order_is_lsb_first(self):
        sig = Signal(0)
        end = encode_frame(sig, 0x87, 0x65)
        r = NecIrDecoder().decode(sig, 0.0, end + TRAILER)
        self.assertEqual(r.violations, [])
        frame, = r.latched_frames
        # Literal transmission order for 0x87, 0x78, 0x65, 0x9A.
        self.assertEqual("".join(map(str, frame.bits)),
                         "11100001" "00011110" "10100110" "01011001")
        self.assertEqual((frame.addr, frame.inv_addr, frame.cmd, frame.inv_cmd),
                         (0x87, 0x78, 0x65, 0x9A))

    def test_frame_then_repeat_code(self):
        sig = Signal(0)
        t = encode_frame(sig, ADDR, CMD)
        end = encode_repeat(sig, t + 40_000_000.0)
        r = NecIrDecoder().decode(sig, 0.0, end + TRAILER)
        self.assertEqual(r.violations, [])
        self.assertEqual(len(r.latched_frames), 1)
        self.assertEqual(len(r.repeats), 1)

    def test_unlatched_frame_not_counted(self):
        sig = Signal(0)
        end = encode_frame(sig, ADDR, CMD)
        r = NecIrDecoder().decode(sig, 0.0, end + FRAME_SILENCE_MIN_NS / 2)
        self.assertEqual(r.latched_frames, [])
        self.assertEqual(len(r.frames), 1)
        self.assertEqual(r.violations, [])


class Windows(unittest.TestCase):
    def test_space_window_edges_pass(self):
        # spaces are exact (not quantized to carrier periods), so the
        # closed-window edges can be placed exactly
        r = decoded(space0_ns=SPACE0_NS * 0.9, space1_ns=SPACE1_NS * 1.1)
        self.assertEqual(r.violations, [])
        r = decoded(space0_ns=SPACE0_NS * 1.1, space1_ns=SPACE1_NS * 0.9)
        self.assertEqual(r.violations, [])

    def test_just_outside_space_fails(self):
        # the misclassified space also leaves the frame incomplete
        r = decoded(space0_ns=SPACE0_NS * 0.9 - 1_000.0)
        self.assertIn("space", kinds(r))
        self.assertFalse(r.frames[0].complete)
        r = decoded(space1_ns=SPACE1_NS * 1.1 + 1_000.0)
        self.assertIn("space", kinds(r))

    def test_just_outside_leader_space_fails(self):
        r = decoded(leader_space_ns=4_500_000.0 * 1.1 + 1_000.0)
        self.assertIn("leader-space", kinds(r))

    def test_just_outside_leader_mark_fails(self):
        r = decoded(leader_mark_ns=9_000_000.0 * 1.1 + 2_000.0)
        self.assertIn("mark", kinds(r))


class Rejects(unittest.TestCase):
    def test_bad_inverted_command(self):
        r = decoded(inv_cmd=(0xFF - CMD) ^ 0x01)
        self.assertEqual(kinds(r), ["complement"])

    def test_bad_inverted_address(self):
        r = decoded(inv_addr=(0xFF - ADDR) ^ 0x20)
        self.assertEqual(kinds(r), ["complement"])

    def test_truncated_frame(self):
        r = decoded(stop_after_bits=17)
        self.assertIn("bit-count", kinds(r))
        self.assertEqual(len(r.frames[0].bits), 16)
        self.assertFalse(r.frames[0].complete)

    def test_off_frequency_carrier(self):
        r = decoded(carrier_period_ns=24_000.0)  # ~41.7 kHz
        self.assertIn("carrier", kinds(r))
        r = decoded(carrier_period_ns=29_000.0)  # ~34.5 kHz
        self.assertIn("carrier", kinds(r))

    def test_200_khz_carrier_is_rejected(self):
        r = decoded(carrier_period_ns=5_000.0)
        self.assertTrue(r.carrier_periods)
        for period in r.carrier_periods:
            self.assertAlmostEqual(period, 5_000.0)
        self.assertEqual(sum(v.kind == "carrier" for v in r.violations),
                         len(r.carrier_periods))
        self.assertEqual(r.latched_frames, [])

    def test_mistimed_everything_fails_on_marks(self):
        # every mark and space +15%: the mark windows fail first (marks are
        # quantized to whole carrier periods, so they cannot sit on edges)
        r = decoded(bit_mark_ns=562_500.0 * 1.15, leader_mark_ns=9_000_000.0 * 1.15,
                    space0_ns=562_500.0 * 1.15, space1_ns=1_687_500.0 * 1.15,
                    leader_space_ns=4_500_000.0 * 1.15)
        self.assertIn("mark", kinds(r))

    def test_in_window_carrier_jitter(self):
        sig = Signal(0, name="ir")
        end = encode_frame(sig, ADDR, CMD)
        # Lengthen a single leader low by 100 ns, inside the period window.
        tr = sig.transitions
        first_fall = next(i for i, (t, v) in enumerate(tr) if v == 0)
        tr[first_fall + 1:] = [(t + 100.0, v) for (t, v) in tr[first_fall + 1:]]
        r = NecIrDecoder().decode(sig, 0.0, end + 100.0 + TRAILER)
        self.assertEqual(r.violations, [])
        self.assertEqual(len(r.latched_frames), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
