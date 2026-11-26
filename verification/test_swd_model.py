#!/usr/bin/env python3
"""Simulator-free self-test of `reference_models/swd.py` (issues #452, #500).

Hand-built probe waveforms with expected results worked out from the ADIv5
description the model is written from (and DR 0018's recorded constants), not
from the model: a nominal connection and two read transactions pass with the
ACK, data and parity the target is configured to drive; each connection rule
and each request field is crossed in turn and must be reported for its own
reason; the turnaround rules are exercised both ways (a probe that keeps
SWDIO driven, a probe that re-drives during the clock high); the WAIT and
FAULT ACKs drive their three bits and release; and the trailing idle rule is
graded at finish(). The memory-access-port mode (issue #500) is exercised
the same way: write transactions with their 33-bit data phase, a posted DRW
read against RDBUFF, SELECT / TAR with no reset value, a write whose parity
is wrong or whose ACK is a WAIT or FAULT, and a probe that does not drive the
write data. Run by `npm run lint`. Stdlib only.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.swd import (  # noqa: E402
    ACK_BAD,
    ACK_FAULT,
    ACK_NONE,
    ACK_OK,
    ACK_WAIT,
    CSW_START,
    RESET_MIN_CYCLES,
    SWITCH_CODE,
    TRAILING_IDLE_MIN,
    MemAp,
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


def read_transaction(host: Host, byte: int, slots=36):
    """A whole read transaction from the host side: request, turnaround,
    `slots` response clocks (36 for OK: ACK 3 + data 32 + parity 1; 3 for a
    WAIT or FAULT, which ends after the ACK), turnaround, retake."""
    read_request(host, byte)
    host.release_and_clock_turnaround()
    host.clock(slots)
    host.retake()
    return host


def write_transaction(host: Host, byte: int, value: int, parity=None,
                      drive_data=True, ack_only=False):
    """A whole write transaction from the host side: request, turnaround, the
    3-bit ACK, the return turnaround and retake, then (unless `ack_only`) the
    33 write bits the host drives: 32 data bits LSB first and even parity
    (`parity` overrides it). `drive_data=False` leaves SWDIO released."""
    read_request(host, byte)
    host.release_and_clock_turnaround()
    host.clock(3)
    host.retake()
    if ack_only:
        return host
    if not drive_data:
        host.set_dio(oe=False)
    p = read_value_parity(value) if parity is None else parity
    for b in bits_of(value, 32) + [p]:
        host.bit(b)
    if not drive_data:
        host.set_dio(oe=True)
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
        # the model drove: ACK OK (wire order 1,0,0 -- numeric code 0b001
        # sent LSB first), IDCODE LSB first, even parity, twice
        want = [1, 0, 0] + bits_of(IDCODE, 32) + [read_value_parity(IDCODE)]
        want += [1, 0, 0] + bits_of(SECOND, 32) + [read_value_parity(SECOND)]
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
    def read2(self, ack):
        """The first read is OK; the second (a request that can legally
        fail) answers `ack`. A WAIT or FAULT ends after its three ACK bits
        (CTRL/STAT.ORUNDETECT = 0)."""
        target = SwdTarget(reads=[(ACK_OK, IDCODE), (ack, 0)])
        host = Host(target)
        connect(host)
        read_transaction(host, 0xA5)
        read_transaction(host, 0xBD, slots=3)
        host.set_dio(img=0)
        host.clock(TRAILING_IDLE_MIN)
        target.finish(host.t)
        return target, host

    def test_ack_wire_order(self):
        # ADIv5 numeric OK=1, WAIT=2, FAULT=4, sent LSB first (IHI 0031 B4.1.5)
        from reference_models.swd import ACK_WIRE
        for name, code in ((ACK_OK, 1), (ACK_WAIT, 2), (ACK_FAULT, 4)):
            self.assertEqual(sum(b << i for i, b in enumerate(ACK_WIRE[name])), code)
        self.assertEqual(ACK_WIRE[ACK_OK], (1, 0, 0))
        self.assertEqual(ACK_WIRE[ACK_FAULT], (0, 0, 1))

    def test_wait_drives_ack_only(self):
        target, host = self.read2(ACK_WAIT)
        self.assertEqual(target.violations, [])
        self.assertEqual(target.acks, [ACK_OK, ACK_WAIT])
        first = [1, 0, 0] + bits_of(IDCODE, 32) + [read_value_parity(IDCODE)]
        self.assertEqual(host.driven, first + [0, 1, 0])

    def test_fault_drives_ack_only(self):
        target, host = self.read2(ACK_FAULT)
        self.assertEqual(target.violations, [])
        self.assertEqual(host.driven[-3:], [0, 0, 1])
        self.assertEqual(len(host.driven), 36 + 3)

    def test_clocking_the_data_phase_after_an_error_is_flagged(self):
        """A host that clocks 36 response slots after a WAIT keeps clocking
        a released, pulled-up line: not a legal end of the transfer."""
        target = SwdTarget(reads=[(ACK_OK, IDCODE), (ACK_WAIT, 0)])
        host = Host(target)
        connect(host)
        read_transaction(host, 0xA5)
        read_transaction(host, 0xBD, slots=36)
        kinds = {v.kind for v in target.violations}
        self.assertIn("line-released-after-transfer", kinds)


class TestReturnTurnaround(unittest.TestCase):
    def test_driving_the_return_turnaround_cycle_is_flagged(self):
        """The Judge's negative control: the first retake() replaced by
        set_dio(img=0, oe=True) then clock(1) -- the probe drives the cycle
        after the read parity. Everything else is the golden shape."""
        target = SwdTarget()
        host = Host(target)
        connect(host)
        read_request(host, 0xA5)
        host.release_and_clock_turnaround()
        host.clock(36)
        host.set_dio(img=0, oe=True)
        host.clock(1)
        read_transaction(host, 0xBD)
        host.set_dio(img=0)
        host.clock(TRAILING_IDLE_MIN)
        target.finish(host.t)
        self.assertEqual({v.kind for v in target.violations},
                         {"return-turnaround-driven"})

    def test_released_return_turnaround_passes(self):
        target = SwdTarget()
        host = Host(target)
        connect(host)
        read_transaction(host, 0xA5)
        read_transaction(host, 0xBD)
        host.set_dio(img=0)
        host.clock(TRAILING_IDLE_MIN)
        target.finish(host.t)
        self.assertEqual(target.violations, [])


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


#: ADIv5 request bytes (even request parity), worked out by hand from the
#: frame: start, APnDP, RnW, A2, A3, parity, stop, park -- LSB first.
REQ_DPIDR = 0xA5      # DP read A=0x0
REQ_SELECT = 0xB1     # DP write A=0x8 (A3=1)
REQ_TAR = 0x8B        # AP write A=0x4 (A2=1)
REQ_DRW = 0x9F        # AP read A=0xC
REQ_RDBUFF = 0xBD     # DP read A=0xC
REQ_CSW = 0x87        # AP read A=0x0 (CSW)
REQ_CTRLSTAT = 0x8D   # DP read A=0x4: not modeled
MEM = {0x20000000: 0x11111111, 0x20000004: 0xCAFEF00D}
POSTED = 0xA5A5C3C3
TAR = 0x20000004


def ap_target(**kw):
    return SwdTarget(ap=MemAp(idcode=IDCODE, mem=MEM, posted_initial=POSTED), **kw)


def kinds_of(target):
    return sorted({v.kind for v in target.violations})


class TestMemAp(unittest.TestCase):
    def connected(self, **kw):
        target = ap_target(**kw)
        host = Host(target)
        connect(host)
        return target, host

    def finish(self, target, host):
        host.set_dio(img=0)
        host.clock(TRAILING_IDLE_MIN)
        target.finish(host.t)

    def test_request_bytes_match_the_frame_layout(self):
        # start 1, APnDP, RnW, A2, A3, parity, stop 0, park 1, LSB first
        def byte(apn, rnw, a2, a3):
            par = request_parity(apn, rnw, a2, a3)
            return sum(b << i for i, b in enumerate([1, apn, rnw, a2, a3, par, 0, 1]))
        self.assertEqual(byte(0, 1, 0, 0), REQ_DPIDR)
        self.assertEqual(byte(0, 0, 0, 1), REQ_SELECT)
        self.assertEqual(byte(1, 0, 1, 0), REQ_TAR)
        self.assertEqual(byte(1, 1, 1, 1), REQ_DRW)
        self.assertEqual(byte(0, 1, 1, 1), REQ_RDBUFF)

    def test_posted_read_then_rdbuff_returns_the_addressed_word(self):
        target, host = self.connected()
        read_transaction(host, REQ_DPIDR)
        write_transaction(host, REQ_SELECT, 0)
        write_transaction(host, REQ_TAR, TAR)
        read_transaction(host, REQ_DRW)
        read_transaction(host, REQ_RDBUFF)
        self.finish(target, host)
        self.assertEqual(target.violations, [])
        self.assertEqual(target.acks, [ACK_OK] * 5)
        self.assertEqual(target.ap.log, [
            ("read", "DPIDR", IDCODE),
            ("write", "SELECT", 0),
            ("write", "TAR", TAR),
            ("read", "DRW", POSTED),          # the stale buffer, NOT the word
            ("read", "RDBUFF", MEM[TAR]),     # the addressed word
        ])
        self.assertNotEqual(POSTED, MEM[TAR])
        # what the model drove: the writes answer ACK only, the reads add data
        want = [1, 0, 0] + bits_of(IDCODE, 32) + [read_value_parity(IDCODE)]
        want += [1, 0, 0] + [1, 0, 0]
        want += [1, 0, 0] + bits_of(POSTED, 32) + [read_value_parity(POSTED)]
        want += [1, 0, 0] + bits_of(MEM[TAR], 32) + [read_value_parity(MEM[TAR])]
        self.assertEqual(host.driven, want)
        phases = [ph for ph, _ in target.wire]
        self.assertEqual(phases.count("write-data"), 66)
        self.assertEqual(target.report()["trailing_idle_low"], TRAILING_IDLE_MIN)

    def test_csw_read_is_posted_like_drw(self):
        # AP reads are posted: DRW -> CSW -> RDBUFF returns the buffer one
        # read late each time (Arm's DAP handling of consecutive AP reads).
        self.assertEqual(request_parity(1, 1, 0, 0), 0)
        byte = sum(b << i for i, b in enumerate([1, 1, 1, 0, 0, 0, 0, 1]))
        self.assertEqual(byte, REQ_CSW)
        target, host = self.connected()
        write_transaction(host, REQ_SELECT, 0)
        write_transaction(host, REQ_TAR, TAR)
        read_transaction(host, REQ_DRW)
        read_transaction(host, REQ_CSW)
        read_transaction(host, REQ_RDBUFF)
        self.finish(target, host)
        self.assertEqual(target.violations, [])
        self.assertEqual(target.ap.log[2:], [
            ("read", "DRW", POSTED),
            ("read", "CSW", MEM[TAR]),        # DRW's queued word, not CSW
            ("read", "RDBUFF", CSW_START),    # CSW's value, one read late
        ])
        want = [1, 0, 0] * 2 + [1, 0, 0] + bits_of(POSTED, 32) + [read_value_parity(POSTED)]
        want += [1, 0, 0] + bits_of(MEM[TAR], 32) + [read_value_parity(MEM[TAR])]
        want += [1, 0, 0] + bits_of(CSW_START, 32) + [read_value_parity(CSW_START)]
        self.assertEqual(host.driven, want)

    def test_csw_starts_in_word_access_state(self):
        # the documented starting state: Size = word (0b010), AddrInc = off
        self.assertEqual(CSW_START & 0x7, 0b010)
        self.assertEqual((CSW_START >> 4) & 0x3, 0b00)
        self.assertEqual(MemAp().csw, CSW_START)

    def test_wrong_write_parity_discards_the_write(self):
        target, host = self.connected()
        read_transaction(host, REQ_DPIDR)
        write_transaction(host, REQ_SELECT, 0, parity=1)   # right parity is 0
        self.finish(target, host)
        self.assertEqual(kinds_of(target), ["write-parity"])
        self.assertIsNone(target.ap.select)
        self.assertNotIn(("write", "SELECT", 0), target.ap.log)

    def test_tar_write_before_select_is_refused(self):
        target, host = self.connected()
        write_transaction(host, REQ_TAR, TAR)
        self.finish(target, host)
        self.assertEqual(kinds_of(target), ["ap-not-selected"])
        self.assertIsNone(target.ap.tar)

    def test_drw_before_tar_is_refused(self):
        target, host = self.connected()
        write_transaction(host, REQ_SELECT, 0)
        read_transaction(host, REQ_DRW)
        self.finish(target, host)
        self.assertEqual(kinds_of(target), ["tar-unset"])

    def test_unaligned_tar_is_refused(self):
        target, host = self.connected()
        write_transaction(host, REQ_SELECT, 0)
        write_transaction(host, REQ_TAR, TAR + 2)
        read_transaction(host, REQ_DRW)
        read_transaction(host, REQ_RDBUFF)
        self.finish(target, host)
        self.assertIn("tar-unaligned", kinds_of(target))

    def test_other_ap_in_select_is_not_this_ap(self):
        target, host = self.connected()
        write_transaction(host, REQ_SELECT, 0x01000000)    # APSEL 1
        write_transaction(host, REQ_TAR, TAR)
        self.finish(target, host)
        self.assertEqual(kinds_of(target), ["ap-not-selected"])

    def test_rejected_write_changes_nothing_and_has_no_data_phase(self):
        for ack in (ACK_WAIT, ACK_FAULT):
            target, host = self.connected(acks={2: ack})
            read_transaction(host, REQ_DPIDR)
            write_transaction(host, REQ_SELECT, 0, ack_only=True)
            self.finish(target, host)
            self.assertEqual(target.violations, [], ack)
            self.assertEqual(target.acks, [ACK_OK, ack])
            self.assertIsNone(target.ap.select)
            self.assertEqual([e[1] for e in target.ap.log], ["DPIDR"])
            self.assertEqual([ph for ph, _ in target.wire].count("write-data"), 0)

    def test_bad_ack_needs_the_probe_to_stay_released(self):
        # No answer (1,1,1) or 1,0,1: not an OK. The probe that drives write
        # data anyway is reported; one that stays released through the
        # possible 33-bit data phase, then idles low, is clean.
        for ack in (ACK_NONE, ACK_BAD):
            target, host = self.connected(acks={2: ack})
            read_transaction(host, REQ_DPIDR)
            write_transaction(host, REQ_SELECT, 0)
            self.finish(target, host)
            self.assertIn("driven-after-bad-ack", kinds_of(target), ack)
            self.assertIsNone(target.ap.select)

            target, host = self.connected(acks={2: ack})
            read_transaction(host, REQ_DPIDR)
            read_request(host, REQ_SELECT)
            host.release_and_clock_turnaround()
            host.clock(3 + 1 + 33 + 2)      # ACK, turnaround, data slots, spare
            host.set_dio(img=0, oe=True)
            host.clock(TRAILING_IDLE_MIN)
            target.finish(host.t)
            self.assertEqual(target.violations, [], ack)
            self.assertEqual(target.acks, [ACK_OK, ack])
            self.assertEqual(len(target.requests), 2, "no request after the bad ACK")
            self.assertIsNone(target.ap.select)
            self.assertEqual(target.report()["trailing_idle_low"], TRAILING_IDLE_MIN)

    def test_write_data_must_be_driven(self):
        target, host = self.connected()
        read_transaction(host, REQ_DPIDR)
        write_transaction(host, REQ_SELECT, 0, drive_data=False)
        self.finish(target, host)
        self.assertIn("write-data-not-driven", kinds_of(target))

    def test_unmodeled_register_is_flagged(self):
        target, host = self.connected()
        read_transaction(host, REQ_CTRLSTAT)
        self.finish(target, host)
        self.assertEqual(kinds_of(target), ["unmodeled-register"])


if __name__ == "__main__":
    unittest.main()
