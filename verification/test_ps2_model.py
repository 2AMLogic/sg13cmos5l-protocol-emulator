#!/usr/bin/env python3
"""Simulator-free self-test of `reference_models/ps2.py` (issue #235).

Hand-built bus logs with expected results worked out from the Chapweske page
the model is written from, not from the model: a nominal device-to-host frame
and a nominal host-to-device frame (request to send, 8+1+1 bits, ACK) pass;
each timing limit is crossed in turn and must be reported for its own
reason; the inhibit rules (abandon the frame, release DATA, wait 50 us,
send the same frame again) are exercised both ways; and a host driver that
breaks the protocol itself is reported as the host's fault, not the
device's. Run by `npm run lint`. Stdlib only.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.ps2 import (  # noqa: E402
    Snap,
    check,
    retransmission_violations,
)

US = 1000.0


class Wave:
    """Four independent pullers (device/host x CLK/DATA); the lines are the
    wired-AND of them, as on the pulled-up open-drain bus."""

    def __init__(self):
        self.ev = []

    def set(self, t, name, val):
        assert name in ("dclk", "ddata", "hclk", "hdata")
        self.ev.append((t, len(self.ev), name, int(val)))

    def snaps(self):
        state = {"dclk": 0, "ddata": 0, "hclk": 0, "hdata": 0}
        out = [Snap(0.0, 1, 1)]
        for t, group in self._groups():
            for _t, _i, name, val in group:
                state[name] = val
            out.append(Snap(t, 0 if (state["dclk"] or state["hclk"]) else 1,
                            0 if (state["ddata"] or state["hdata"]) else 1,
                            bool(state["hclk"]), bool(state["hdata"])))
        return out

    def _groups(self):
        evs = sorted(self.ev)
        i = 0
        while i < len(evs):
            j = i
            while j < len(evs) and evs[j][0] == evs[i][0]:
                j += 1
            yield evs[i][0], evs[i:j]
            i = j


def odd_parity_bit(byte):
    return 1 - (bin(byte).count("1") % 2)


def dev_frame(w, t0, byte, *, low=40 * US, high=40 * US, setup=20 * US, parity=None,
              stop=1, cells=11, lows=None, highs=None, setups=None):
    """A device-to-host frame whose first data change (the start bit) is at
    `t0`. `high` is the time from a CLK rise to the next fall, `setup` the time
    from a data change to the fall that follows it. Returns the time of the
    last rise. Per-cell overrides: lows/highs/setups map cell index to ns."""
    p = odd_parity_bit(byte) if parity is None else parity
    bits = [0] + [(byte >> i) & 1 for i in range(8)] + [p, stop]
    pulling = ddata_state(w)  # 1: the device is pulling DATA low
    rise_prev = None
    last_rise = t0
    for k in range(min(cells, 11)):
        s = (setups or {}).get(k, setup)
        h = (highs or {}).get(k, high)
        lo = (lows or {}).get(k, low)
        if k == 0:
            t_dc, t_fall = t0, t0 + s
        else:
            t_fall = rise_prev + h
            t_dc = t_fall - s
        want = 1 if bits[k] == 0 else 0
        if want != pulling:
            w.set(t_dc, "ddata", want)
            pulling = want
        w.set(t_fall, "dclk", 1)
        t_rise = t_fall + lo
        w.set(t_rise, "dclk", 0)
        rise_prev = t_rise
        last_rise = t_rise
    return last_rise


def ddata_state(w):
    state = 0
    for t, _i, name, val in sorted(w.ev):
        if name == "ddata":
            state = val
    return state


def host_rts(w, t0, byte, *, inhibit=120 * US, response=100 * US, low=40 * US, high=40 * US,
             parity=None, stop=1, ack=True, ack_setup=20 * US, host_change=15 * US,
             release_data=True, abort_after=None, hold_data_after=0.0, early_data=None):
    """Host-to-device: CLK low `inhibit`, DATA low, CLK released; the device
    clocks after `response`. Returns the time of the last device rise."""
    p = odd_parity_bit(byte) if parity is None else parity
    bits = [(byte >> i) & 1 for i in range(8)] + [p, stop]
    w.set(t0, "hclk", 1)
    w.set(t0 + inhibit - 10 * US, "hdata", 1)
    t_rel = t0 + inhibit
    w.set(t_rel, "hclk", 0)
    t_fall = t_rel + response
    for k in range(10):
        w.set(t_fall, "dclk", 1)
        # the host sets this pulse's bit while CLK is low
        t_set = t_fall + host_change
        if early_data is not None and k == early_data:
            t_set = t_fall - 5 * US  # while CLK is high: the host breaks the rule
        w.set(t_set, "hdata", 1 if bits[k] == 0 else 0)
        t_rise = t_fall + low
        w.set(t_rise, "dclk", 0)
        if abort_after is not None and k + 1 == abort_after:
            w.set(t_rise + 5 * US, "hclk", 1)
            w.set(t_rise + 6 * US, "hdata", 0)
            w.set(t_rise + 5 * US + 120 * US, "hclk", 0)
            return t_rise
        t_fall = t_rise + high
    if ack:
        t_ack = t_fall - ack_setup
        w.set(t_ack, "ddata", 1)
    w.set(t_fall, "dclk", 1)
    t_rise = t_fall + low
    w.set(t_rise + hold_data_after, "dclk", 0)
    if hold_data_after:
        w.set(t_rise, "dclk", 0)
    if ack and release_data:
        w.set(t_rise, "ddata", 0)
    elif not ack:
        pass
    return t_rise


def kinds(result):
    return sorted({v.kind for v in result.violations})


def run(w, end=None):
    return check(w.snaps(), end)


class DeviceToHost(unittest.TestCase):
    def test_nominal_frame(self):
        for byte in (0x00, 0xFF, 0xAA, 0x1C, 0x5A, 0x01, 0x80):
            w = Wave()
            dev_frame(w, 60 * US, byte)
            r = run(w)
            self.assertEqual(r.violations, [], f"byte {byte:#04x}")
            self.assertEqual(r.host_violations, [])
            f = r.complete("dev->host")
            self.assertEqual(len(f), 1)
            self.assertEqual(f[0].byte, byte)
            self.assertTrue(f[0].parity_ok and f[0].stop_ok)

    def test_limits_are_inclusive(self):
        for kw in ({"low": 30 * US}, {"low": 50 * US}, {"high": 30 * US}, {"high": 50 * US},
                   {"setup": 5 * US, "high": 40 * US}, {"setup": 25 * US, "high": 40 * US}):
            w = Wave()
            dev_frame(w, 50 * US, 0x5A, **kw)
            self.assertEqual(run(w).violations, [], kw)

    def test_hold_off_exactly_50us_passes_and_less_fails(self):
        w = Wave()
        dev_frame(w, 50 * US, 0x1C)
        self.assertEqual(run(w).violations, [])
        w = Wave()
        dev_frame(w, 49 * US, 0x1C)
        self.assertEqual(kinds(run(w)), ["hold-off"])

    def test_clock_widths(self):
        for kw, want in (({"low": 29 * US}, "clk-low"), ({"low": 51 * US}, "clk-low"),
                         ({"high": 29 * US, "setup": 15 * US}, "clk-high"),
                         ({"high": 51 * US}, "clk-high")):
            w = Wave()
            dev_frame(w, 60 * US, 0x3C, **kw)
            self.assertIn(want, kinds(run(w)), kw)

    def test_data_timing(self):
        w = Wave()
        dev_frame(w, 60 * US, 0x3C, setup=4 * US, high=40 * US)  # change 4 us before the fall
        self.assertIn("data-setup", kinds(run(w)))
        w = Wave()
        dev_frame(w, 60 * US, 0x3C, setup=26 * US, high=40 * US)
        self.assertIn("data-setup", kinds(run(w)))
        # change 3 us after the rise: high 40, setup 37
        w = Wave()
        dev_frame(w, 60 * US, 0x3C, setup=37 * US, high=40 * US)
        self.assertIn("data-after-rise", kinds(run(w)))

    def test_parity_and_stop(self):
        w = Wave()
        dev_frame(w, 60 * US, 0x3C, parity=1 - odd_parity_bit(0x3C))
        self.assertEqual(kinds(run(w)), ["parity"])
        w = Wave()
        dev_frame(w, 60 * US, 0x3C, stop=0)
        self.assertIn("stop-bit", kinds(run(w)))

    def test_measured_ranges_are_reported(self):
        w = Wave()
        dev_frame(w, 60 * US, 0x1C, low=35 * US, high=45 * US)
        r = run(w)
        self.assertEqual(r.violations, [])
        self.assertEqual(r.measured["CLK low"], (35 * US, 35 * US))
        self.assertEqual(r.measured["CLK high"], (45 * US, 45 * US))
        self.assertEqual(r.measured["hold-off"], (60 * US, 60 * US))

    def test_stray_clock(self):
        w = Wave()
        w.set(100 * US, "dclk", 1)
        w.set(140 * US, "dclk", 0)
        self.assertEqual(kinds(run(w)), ["stray-clock"])

    def test_device_drives_data_while_inhibited(self):
        w = Wave()
        w.set(10 * US, "hclk", 1)
        w.set(30 * US, "ddata", 1)
        w.set(130 * US, "hclk", 0)
        self.assertIn("data-while-inhibited", kinds(run(w)))


class Inhibit(unittest.TestCase):
    def abandoned(self, release=True, retransmit=True, continue_clocking=False, wait_after=60 * US):
        w = Wave()
        t_last = dev_frame(w, 60 * US, 0x1C, cells=4)  # four clocks, then the host inhibits
        host_down = t_last + 10 * US
        w.set(host_down, "hclk", 1)
        if release:
            w.set(host_down + 1 * US, "ddata", 0)
        else:
            pass  # the device keeps whatever it was pulling
        host_up = host_down + 130 * US
        w.set(host_up, "hclk", 0)
        if continue_clocking:
            dev_frame(w, host_up + 10 * US, 0x1C, cells=3)
        if retransmit:
            dev_frame(w, host_up + wait_after, 0x1C)
        return w

    def test_abandon_then_resend_passes(self):
        w = self.abandoned()
        r = run(w)
        self.assertEqual(r.violations, [])
        self.assertEqual(retransmission_violations(r), [])
        self.assertEqual([f.aborted for f in r.frames if f.direction == "dev->host"], [True, False])
        self.assertEqual(r.complete("dev->host")[0].byte, 0x1C)

    def test_data_held_after_release_is_caught(self):
        # the last bit sent was a 0 (a pulled DATA); a device that keeps it
        # after the host lets go has not released the line
        w = Wave()
        t_last = dev_frame(w, 60 * US, 0x00, cells=4)
        w.set(t_last + 10 * US, "hclk", 1)
        w.set(t_last + 140 * US, "hclk", 0)
        r = run(w)
        self.assertIn("inhibit-release", kinds(r))

    def test_short_hold_off_after_inhibit(self):
        w = self.abandoned(wait_after=30 * US)
        self.assertIn("hold-off", kinds(run(w)))

    def test_continuing_the_frame_is_caught(self):
        w = self.abandoned(continue_clocking=True, retransmit=False)
        r = run(w)
        self.assertTrue({"hold-off", "stray-clock"} & set(kinds(r)), kinds(r))

    def test_no_retransmit_is_caught(self):
        w = self.abandoned(retransmit=False)
        r = run(w)
        self.assertEqual([v.kind for v in retransmission_violations(r)], ["no-retransmit"])

    def test_wrong_retransmit_is_caught(self):
        w = Wave()
        t_last = dev_frame(w, 60 * US, 0x1C, cells=4)
        w.set(t_last + 10 * US, "hclk", 1)
        w.set(t_last + 11 * US, "ddata", 0)
        up = t_last + 140 * US
        w.set(up, "hclk", 0)
        dev_frame(w, up + 60 * US, 0x1D)
        r = run(w)
        self.assertEqual([v.kind for v in retransmission_violations(r)], ["retransmit-mismatch"])

    def test_inhibit_after_the_last_clock_needs_no_resend(self):
        w = Wave()
        t_last = dev_frame(w, 60 * US, 0x1C)
        w.set(t_last + 5 * US, "hclk", 1)
        w.set(t_last + 130 * US, "hclk", 0)
        r = run(w)
        self.assertEqual(r.violations, [])
        self.assertEqual(retransmission_violations(r), [])

    def test_data_change_under_a_host_held_clock_is_not_the_devices_fault(self):
        # the host inhibits 10 us after a rise; the device cannot know yet and
        # sets its next bit 20 us after the rise. That is a race, not a defect.
        w = Wave()
        t_last = dev_frame(w, 60 * US, 0x1C, cells=2)
        w.set(t_last + 10 * US, "hclk", 1)
        w.set(t_last + 20 * US, "ddata", 1 - ddata_state(w))
        w.set(t_last + 25 * US, "ddata", 0)
        w.set(t_last + 140 * US, "hclk", 0)
        self.assertEqual(run(w).violations, [])
        # but a device that changes DATA while *it* holds CLK low is wrong
        w = Wave()
        dev_frame(w, 60 * US, 0x1C, cells=2)
        w.set(60 * US + 20 * US + 10 * US, "ddata", 1 - ddata_state(w))
        self.assertIn("data-while-clk-low", kinds(run(w)))

    def test_host_inhibit_shorter_than_100us_is_the_hosts_fault(self):
        w = Wave()
        w.set(10 * US, "hclk", 1)
        w.set(60 * US, "hclk", 0)
        r = run(w)
        self.assertEqual([v.kind for v in r.host_violations], ["host-inhibit"])
        self.assertEqual(r.violations, [])


class HostToDevice(unittest.TestCase):
    def test_nominal_request_and_ack(self):
        for byte in (0x00, 0xFF, 0xED, 0x55, 0x80):
            w = Wave()
            host_rts(w, 10 * US, byte)
            r = run(w)
            self.assertEqual(r.violations, [], byte)
            self.assertEqual(r.host_violations, [], byte)
            f = r.complete("host->dev")
            self.assertEqual(len(f), 1)
            self.assertEqual(f[0].byte, byte)
            self.assertTrue(f[0].parity_ok and f[0].stop_ok)
            self.assertEqual(r.rts_response_ns, [100 * US])

    def test_host_parity_error_is_decoded_as_bad(self):
        w = Wave()
        host_rts(w, 10 * US, 0xED, parity=1 - odd_parity_bit(0xED))
        r = run(w)
        self.assertEqual(r.violations, [])
        f = r.complete("host->dev")[0]
        self.assertFalse(f.parity_ok)

    def test_missing_ack(self):
        w = Wave()
        host_rts(w, 10 * US, 0xED, ack=False)
        self.assertIn("no-ack", kinds(run(w)))

    def test_ack_too_early_and_too_late(self):
        for setup in (4 * US, 26 * US):
            w = Wave()
            host_rts(w, 10 * US, 0xED, ack_setup=setup)
            self.assertIn("ack-setup", kinds(run(w)), setup)
        for setup in (5 * US, 25 * US):
            w = Wave()
            host_rts(w, 10 * US, 0xED, ack_setup=setup)
            self.assertEqual(run(w).violations, [], setup)

    def test_data_not_released_after_ack(self):
        w = Wave()
        host_rts(w, 10 * US, 0xED, release_data=False)
        self.assertIn("ack-release", kinds(run(w, end=2000 * US)))

    def _late_release(self, delay_us):
        # DATA held low after the 11th clock, then released with no other
        # bus activity in between
        w = Wave()
        last_rise = host_rts(w, 10 * US, 0xED, release_data=False)
        w.set(last_rise + delay_us * US, "ddata", 0)
        return run(w, end=last_rise + (delay_us + 1) * US)

    def test_release_at_the_limit_is_accepted(self):
        r = self._late_release(50)
        self.assertEqual(r.violations, [])
        self.assertEqual(len(r.complete()), 1)

    def test_overdue_release_edge_is_caught_without_other_snapshots(self):
        for delay in (51, 100, 1000):
            with self.subTest(delay=delay):
                self.assertIn("ack-release", kinds(self._late_release(delay)))

    def test_host_held_data_exempts_a_late_release(self):
        w = Wave()
        last_rise = host_rts(w, 10 * US, 0xED, release_data=False)
        w.set(last_rise + 20 * US, "hdata", 1)
        w.set(last_rise + 200 * US, "ddata", 0)
        w.set(last_rise + 300 * US, "hdata", 0)
        self.assertNotIn("ack-release", kinds(run(w, end=last_rise + 400 * US)))

    def test_slow_response(self):
        w = Wave()
        host_rts(w, 10 * US, 0xED, response=15_001 * US)
        self.assertIn("rts-response", kinds(run(w)))
        w = Wave()
        host_rts(w, 10 * US, 0xED, response=14_000 * US)
        self.assertEqual(run(w).violations, [])

    def test_no_response_at_all(self):
        w = Wave()
        w.set(10 * US, "hclk", 1)
        w.set(120 * US, "hdata", 1)
        w.set(130 * US, "hclk", 0)
        r = run(w, end=20_000 * US)
        self.assertIn("rts-response", kinds(r))

    def test_clock_widths_in_a_received_frame(self):
        w = Wave()
        host_rts(w, 10 * US, 0xED, low=55 * US, host_change=15 * US)
        self.assertIn("clk-low", kinds(run(w)))
        w = Wave()
        host_rts(w, 10 * US, 0xED, high=25 * US)
        self.assertIn("clk-high", kinds(run(w)))

    def test_device_pulling_data_while_receiving(self):
        w = Wave()
        host_rts(w, 10 * US, 0xED)
        # in the first low phase, after the host has set its first bit (a 1: released)
        w.set(10 * US + 120 * US + 100 * US + 20 * US, "ddata", 1)
        w.set(10 * US + 120 * US + 100 * US + 30 * US, "ddata", 0)
        self.assertIn("rx-data-drive", kinds(run(w)))

    def test_host_changing_data_while_clk_high_is_the_hosts_fault(self):
        w = Wave()
        host_rts(w, 10 * US, 0xED, early_data=1)
        r = run(w)
        self.assertIn("host-data-while-clk-high", [v.kind for v in r.host_violations])

    def test_host_abort_before_the_ack(self):
        w = Wave()
        host_rts(w, 10 * US, 0xED, abort_after=4)
        r = run(w)
        self.assertEqual(r.violations, [])
        self.assertEqual([f.aborted for f in r.frames], [True])
        self.assertEqual(r.complete("host->dev"), [])

    def test_response_hold_off_after_a_received_frame(self):
        # echo 60 us after the 11th rise: allowed
        w = Wave()
        t = host_rts(w, 10 * US, 0xED)
        dev_frame(w, t + 60 * US, 0xED)
        r = run(w)
        self.assertEqual(r.violations, [])
        self.assertEqual([f.byte for f in r.complete()], [0xED, 0xED])
        # 30 us after: too soon
        w = Wave()
        t = host_rts(w, 10 * US, 0xED)
        dev_frame(w, t + 30 * US, 0xED)
        self.assertIn("hold-off", kinds(run(w)))


if __name__ == "__main__":
    unittest.main()
