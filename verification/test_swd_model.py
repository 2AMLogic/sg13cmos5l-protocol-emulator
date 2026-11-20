#!/usr/bin/env python3
"""Simulator-free self-test of `reference_models/swd.py` (issue #452).

Hand-built probe waveforms with expected results worked out from the ADIv5
description the model is written from (and DR 0018's recorded constants), not
from the model: a nominal connection and two read transactions pass with the
ACK, data and parity the target is configured to drive; each connection rule
and each request field is crossed in turn and must be reported for its own
reason; the turnaround rules are exercised both ways (a probe that keeps
SWDIO driven, a probe that re-drives during the clock high); the WAIT and
FAULT ACKs drive their three bits and release; and the trailing idle rule is
graded at finish(). Run by `npm run lint`. Stdlib only.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.swd import (  # noqa: E402
    ACK_FAULT,
    ACK_OK,
    ACK_WAIT,
    RESET_MIN_CYCLES,
    SWITCH_CODE,
    TRAILING_IDLE_MIN,
    SwdTarget,
    read_value_parity,
    request_parity,
)

NS = 20.0  # one core cycle at the 50 MHz target clock, as the bench names it
IDCODE = 0x4BA00477
SECOND = 0x12345678


def bits_of(value, n):
    return [(value >> i) & 1 for i in range(n)]


class Host:
    """A minimal SWD host-side waveform generator and line resolver: drives
    SWCLK and (while `oe`) SWDIO, resolves the line against the target's
    driver and the pull-up, and feeds every settled state to the model. The
    waveforms are built from the protocol (bit periods of two half-cycles),
    never from any firmware."""

    def __init__(self, target: SwdTarget):
        self.t = 0.0
        self.clk = 0
        self.img = 1   # the host's SWDIO output image
        self.oe = True
        self.target = target
        self.driven = []  # the SWDIO bit the target drove at each rising edge
        self._obs_clk = 0
        self._apply()

    def line(self):
        if self.oe:
            return self.img
        if self.target.drive is not None:
            return self.target.drive
        return 1  # the pull-up

    def _apply(self):
        prev_clk = self._obs_clk
        self.target.on_pad(self.t, self.clk, self.line(), self.oe)
        # a drive change lands this instant; settle the resolved line
        # through the model once more so its own view stays coherent
        self.target.on_pad(self.t, self.clk, self.line(), self.oe)
        self._obs_clk = self.clk
        # the bit as launched at this rising edge (repeated bits included)
        if self.clk == 1 and prev_clk == 0 and self.target.drive is not None:
            self.driven.append(self.target.drive)

    def _tick(self, clk):
        self.t += NS
        self.clk = clk
        self._apply()

    def set_dio(self, img=None, oe=None):
        """Change SWDIO while the clock rests low (the host's only legal
        window)."""
        assert self.clk == 0
        if img is not None:
            self.img = img
        if oe is not None:
            self.oe = oe
        self._apply()

    def clock(self, n=1):
        for _ in range(n):
            self._tick(1)
            self._tick(0)

    def force(self, img=None, oe=None):
        """Change SWDIO outside the legal window (while the clock is high)
        -- for the negative cases only."""
        if img is not None:
            self.img = img
        if oe is not None:
            self.oe = oe
        self._apply()

    def bit(self, b):
        """One host-driven SWDIO bit: change it while low, then clock it."""
        self.set_dio(img=b)
        self.clock(1)

    def release_and_clock_turnaround(self):
        """The host end of the turnaround: release while low, clock one
        cycle, leave the clock low for the response."""
        self.set_dio(oe=False)
        self._tick(1)
        self._tick(0)

    def retake(self):
        """The host end of the second turnaround: clock one cycle, then
        re-drive while the clock is low."""
        self._tick(1)
        self._tick(0)
        self.set_dio(oe=True)


def connect(host: Host, reset_len=RESET_MIN_CYCLES):
    """The connection shape pyOCD sends: first line reset, the 0xE79E switch
    (LSB first), a second line reset, idle clocks with SWDIO low."""
    host.set_dio(img=1, oe=True)
    host.clock(reset_len)
    for b in bits_of(SWITCH_CODE, 16):
        host.bit(b)
    host.set_dio(img=1)
    host.clock(reset_len)
    host.set_dio(img=0)
    host.clock(2)


def read_request(host: Host, byte: int):
    for b in bits_of(byte, 8):
        host.bit(b)


def read_transaction(host: Host, byte: int):
    """A whole read transaction from the host side: request, turnaround,
    36 response clocks, turnaround, retake."""
    read_request(host, byte)
    host.release_and_clock_turnaround()
    host.clock(36)
    host.retake()
    return host


class TestParityHelpers(unittest.TestCase):
    def test_request_parity_is_even_over_the_header(self):
        # 0xA5's header (APnDP 0, RnW 1, A 00) holds one 1 -> parity 1
        self.assertEqual(request_parity(0, 1, 0, 0), 1)
        # 0xBD's header (0, 1, 1, 1) holds three 1s -> parity 1
        self.assertEqual(request_parity(0, 1, 1, 1), 1)
        # a header with two 1s needs parity 0
        self.assertEqual(request_parity(0, 1, 0, 1), 0)

    def test_read_value_parity(self):
        self.assertEqual(bin(IDCODE).count("1"), 13)
        self.assertEqual(read_value_parity(IDCODE), 1)
        self.assertEqual(read_value_parity(0), 0)
        self.assertEqual(read_value_parity(0xFFFFFFFF), 0)


class TestGolden(unittest.TestCase):
    def run_golden(self, **kw):
        target = SwdTarget(**kw)
        host = Host(target)
        connect(host)
        return target, host

    def test_connection_and_two_reads(self):
        target, host = self.run_golden()
        # connection is granted with the first request's start bit: the
        # target only counts itself attached once a frame begins
        self.assertFalse(target.connected)
        read_transaction(host, 0xA5)
        self.assertTrue(target.connected)
        self.assertEqual(target.violations, [])
        read_transaction(host, 0xBD)
        host.set_dio(img=0)
        host.clock(TRAILING_IDLE_MIN)
        target.finish(host.t)
        self.assertEqual(target.violations, [])
        self.assertEqual([f.byte for f in target.requests], [0xA5, 0xBD])
        self.assertTrue(all(f.ok for f in target.requests))
        self.assertEqual(target.acks, [ACK_OK, ACK_OK])
        # the model drove: ACK 001, IDCODE LSB first, even parity, twice
        want = [0, 0, 1] + bits_of(IDCODE, 32) + [read_value_parity(IDCODE)]
        want += [0, 0, 1] + bits_of(SECOND, 32) + [read_value_parity(SECOND)]
        self.assertEqual(host.driven, want)
        self.assertEqual(target.report()["trailing_idle_low"], TRAILING_IDLE_MIN)

    def test_wire_and_widths_are_recorded(self):
        target, host = self.run_golden()
        read_transaction(host, 0xA5)
        host.set_dio(img=0)
        host.clock(TRAILING_IDLE_MIN)
        target.finish(host.t)
        self.assertEqual(target.rise_count > RESET_MIN_CYCLES * 2, True)
        phases = [ph for ph, _ in target.wire]
        self.assertEqual(phases.count("switch"), 16)
        self.assertEqual(phases.count("request"), 8)
        # the hand-built clock is one cycle high and one low everywhere
        self.assertEqual(target.report()["swclk_high_cycles"]["switch"], (1.0, 1.0))
        self.assertEqual(target.report()["swclk_low_cycles"]["switch"], (1.0, 1.0))


class TestConnectionRules(unittest.TestCase):
    def check_never_connects(self, target, host, kind):
        self.assertFalse(target.connected)
        kinds = {v.kind for v in target.violations}
        self.assertIn(kind, kinds)
        self.assertEqual(host.driven, [], "a dormant target drives nothing")

    def test_first_line_reset_one_clock_short(self):
        target = SwdTarget()
        host = Host(target)
        connect(host, reset_len=RESET_MIN_CYCLES - 1)
        read_transaction(host, 0xA5)
        target.finish(host.t)
        self.check_never_connects(target, host, "line-reset-short")

    def test_second_line_reset_short(self):
        target = SwdTarget()
        host = Host(target)
        connect(host)
        # rewind: a fresh target that saw a short second reset only
        target2 = SwdTarget()
        host2 = Host(target2)
        host2.set_dio(img=1, oe=True)
        host2.clock(RESET_MIN_CYCLES)
        for b in bits_of(SWITCH_CODE, 16):
            host2.bit(b)
        host2.set_dio(img=1)
        host2.clock(RESET_MIN_CYCLES - 1)
        host2.set_dio(img=0)
        host2.clock(2)
        self.assertFalse(target2.connected)
        kinds = {v.kind for v in target2.violations}
        self.assertIn("line-reset-short", kinds)

    def test_wrong_switch_code(self):
        target = SwdTarget()
        host = Host(target)
        host.set_dio(img=1, oe=True)
        host.clock(RESET_MIN_CYCLES)
        for b in bits_of(SWITCH_CODE ^ 0x0002, 16):  # one bit flipped
            host.bit(b)
        host.set_dio(img=1)
        host.clock(RESET_MIN_CYCLES)
        host.set_dio(img=0)
        host.clock(2)
        read_transaction(host, 0xA5)
        target.finish(host.t)
        self.check_never_connects(target, host, "switch-sequence")

    def test_too_few_idle_clocks(self):
        target = SwdTarget()
        host = Host(target)
        host.set_dio(img=1, oe=True)
        host.clock(RESET_MIN_CYCLES)
        for b in bits_of(SWITCH_CODE, 16):
            host.bit(b)
        host.set_dio(img=1)
        host.clock(RESET_MIN_CYCLES)
        host.set_dio(img=0)
        host.clock(1)  # one idle clock, two required
        read_transaction(host, 0xA5)
        kinds = {v.kind for v in target.violations}
        self.assertIn("idle-after-switch", kinds)


class TestRequestRules(unittest.TestCase):
    def read_with_byte(self, byte):
        target = SwdTarget()
        host = Host(target)
        connect(host)
        read_transaction(host, byte)
        return target, host

    def test_bad_parity_gets_no_response(self):
        # 0xA5 with the parity bit inverted (0x85) fails the parity field
        target, host = self.read_with_byte(0xA5 ^ 0x20)
        self.assertFalse(host.driven, "a rejected request drives no response")
        kinds = {v.kind for v in target.violations}
        self.assertEqual(kinds, {"request-parity"})
        self.assertFalse(target.requests[0].ok)


    # A request with a 0 start bit is not a detectable line-level defect:
    # to a target, SWDIO staying low is indistinguishable from more idle
    # clocks, so the frame boundary is the first driven high bit. The model
    # therefore never reports `request-start` from a waveform, and no
    # start-bit mutant exists in the bench either.

    def test_bad_stop_bit(self):
        target, _ = self.read_with_byte(0xE5)  # stop 1
        self.assertIn("request-stop", {v.kind for v in target.violations})

    def test_bad_park_bit(self):
        target, _ = self.read_with_byte(0xA5 ^ 0x80)  # park 0
        self.assertIn("request-park", {v.kind for v in target.violations})

    def test_write_request_is_refused(self):
        # 0x81: a well-paritied DP write (RnW 0, header all zeros)
        target, host = self.read_with_byte(0x81)
        self.assertFalse(host.driven)
        self.assertIn("write-request", {v.kind for v in target.violations})


class TestTurnaroundRules(unittest.TestCase):
    def test_probe_keeps_swdio_driven(self):
        target = SwdTarget()
        host = Host(target)
        connect(host)
        read_request(host, 0xA5)
        host._tick(0)  # park-bit fall
        host._tick(1)  # the turnaround rise -- still driving SWDIO
        kinds = {v.kind for v in target.violations}
        self.assertIn("no-release", kinds)

    def test_probe_re_drives_during_the_high(self):
        target = SwdTarget()
        host = Host(target)
        connect(host)
        read_request(host, 0xA5)
        host.release_and_clock_turnaround()
        host.clock(36)          # the response; the target releases mid-way
        host._tick(1)           # the second turnaround's clock high, line still released
        host.force(oe=True)     # re-drive during the high
        kinds = {v.kind for v in target.violations}
        self.assertIn("redrive-while-high", kinds)

    def test_swdio_moved_during_the_high(self):
        target = SwdTarget()
        host = Host(target)
        connect(host)
        read_request(host, 0xA5)
        host._tick(1)           # clock high
        host.force(img=0)       # move SWDIO while the clock is high
        kinds = {v.kind for v in target.violations}
        self.assertIn("swdio-change-while-high", kinds)


class TestResponses(unittest.TestCase):
    def read1(self, ack):
        target = SwdTarget(reads=[(ack, 0), (ACK_OK, SECOND)])
        host = Host(target)
        connect(host)
        read_transaction(host, 0xA5)
        read_transaction(host, 0xBD)
        return target, host

    def test_wait_drives_ack_only(self):
        target, host = self.read1(ACK_WAIT)
        self.assertEqual(target.violations, [])
        self.assertEqual(target.acks, [ACK_WAIT, ACK_OK])
        # the first answer drove its three ACK bits and released: nothing
        # more until the second transaction's response
        second = [0, 0, 1] + bits_of(SECOND, 32) + [read_value_parity(SECOND)]
        self.assertEqual(host.driven, [0, 1, 0] + second)

    def test_fault_drives_ack_only(self):
        target, host = self.read1(ACK_FAULT)
        self.assertEqual(target.violations, [])
        self.assertEqual(host.driven[0:3], [1, 0, 0])


class TestTrailingIdle(unittest.TestCase):
    def finish_after(self, lows):
        target = SwdTarget()
        host = Host(target)
        connect(host)
        read_transaction(host, 0xA5)
        read_transaction(host, 0xBD)
        host.set_dio(img=0)
        host.clock(lows)
        target.finish(host.t)
        return target

    def test_eight_idle_clocks_pass(self):
        target = self.finish_after(TRAILING_IDLE_MIN)
        self.assertEqual(target.violations, [])

    def test_seven_idle_clocks_fail(self):
        target = self.finish_after(TRAILING_IDLE_MIN - 1)
        kinds = {v.kind for v in target.violations}
        self.assertEqual(kinds, {"trailing-idle-short"})

    def test_no_trailing_idle_fails(self):
        target = self.finish_after(0)
        kinds = {v.kind for v in target.violations}
        self.assertEqual(kinds, {"trailing-idle-short"})


if __name__ == "__main__":
    unittest.main()
