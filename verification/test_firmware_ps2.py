"""DUT-facing PS/2 device firmware bench (target-spec row 13, stretch column,
issue #235; the protocol choice is the dated note of 2026-10-11 in DR 0018,
made after DR 0017's ISA freeze).

The claim: the committed program `firmware/asm/ps2_device.asm` (image
`firmware/build/ps2_device.hex`), loaded over the real serial load-phase pins
onto the real top and run by the ISA core, behaves as a PS/2 keyboard/mouse
device on an open-drain, pulled-up two-wire bus that a **host** also drives.
The host here is the independent model side
(`verification/reference_models/ps2.py`, written from Chapweske's published
description alone). It holds CLK low to inhibit, requests to send, sends
bytes, and watches every edge the device makes. The bench never tells the
model what the waveform should look like.

What is on the bus. The pad model (`verification/uio_pads.py`, DR 0012,
verification-plan section 7) resolves `uio[2]` (CLK) and `uio[3]` (DATA) from
the design's own `uio_oe` / `uio_out` and the host's driver, with a pull-up
on each line. The other six `uio` lines are tied low by the board, so a
program that drove one of them high would be reported as contention. A line
goes low here only because the device's pad is enabled and driving 0, or
because the host pulls it.

What is graded, and by whom
---------------------------
1. **The bus.** The bench logs the resolved CLK and DATA levels at every
   change, together with what the host is pulling, and gives the log to
   `reference_models.ps2.check`. Every device-side limit (clock widths, data
   setup and hold against the clock, the 50 us hold-off, the inhibit and
   abandon rule, request-to-send response, the ACK and the release after it)
   is the model's. It also grades the **host driver** against the protocol,
   so the device is never graded against an illegal host.
2. **The bytes.** Frames the model decodes are compared with what the bench
   sent: each command byte must come back as an echo after the ACK, and a
   frame with bad parity must come back as 0xFE.
3. **The pads.** After each run the pad model must show no contention, no
   unknown `uio_oe`, exactly CLK and DATA enabled, both only ever driven
   low (open-drain), and no other pin driven.

Time base. The simulation clock is 20 ns, target-spec row 4's **target**
50 MHz, which is not confirmed. Every microsecond figure is core cycles x
20 ns; no pad delay or pull-up rise time is modelled (the pad model has zero
delay by design).

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Seven mutant programs, each assembled in memory from the committed source
with one defect, run on the same DUT and bus and must be rejected for the
defect's own reason: no inhibit check (the device keeps clocking while the
host holds CLK low), a hold-off of 8 us instead of 50 us, no ACK (misses the
turnaround), the data change 37 us before the falling edge (too late), the
data change 2 us after a rising edge (too early), even parity, and an
open-drain setup replaced by push-pull (drives a line it should release, so
the pad model reports contention). An eighth skips the host's parity check,
which only the byte comparison (not the bus model) can catch. A ninth control
re-grades the golden run's own log with the DATA edges moved, to show the
log-and-grade path can fail.

Driven by `klt functional-verification` (`verification/request-firmware-
ps2.json`) at RTL, and by `flow/run-ps2-gate-level.sh` on the LibreLane
netlist (zero-delay). All of it is pin-observable, so the same file runs
unchanged on gates.
"""

import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Event, First, ReadOnly, Timer, ValueChange
from cocotb.utils import get_sim_time

from reference_models.ps2 import (
    Snap,
    check,
    retransmission_violations,
)
from uio_pads import UioPads

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)
from firmware_artifacts import parse_hex_image  # noqa: E402

# The load-phase driver is the one every other bench uses.
from test_protocol_emulator import load_program  # noqa: E402

SRC = REPO_ROOT / "firmware" / "asm" / "ps2_device.asm"
HEX = REPO_ROOT / "firmware" / "build" / "ps2_device.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "ps2_device.cycles.txt"

#: Simulation clock: names row 4's target 50 MHz; not a measurement.
CLK_PERIOD_NS = 20
#: The bus: CLK and DATA on the standard I2C Pmod's pull-up'd row.
CLK_BIT, DATA_BIT = 2, 3
#: `UIO_OD` value the program must write: CLK | DATA.
OD_MASK = (1 << CLK_BIT) | (1 << DATA_BIT)
US = 1000

#: The bytes the host sends in the echo test, with the reason for each.
ECHO_BYTES = (0xED, 0x00, 0xFF, 0x55, 0xAA, 0x01, 0x80, 0xF4)
#: The assembler's data-dependent-latency warnings, as (mnemonic, branch
#: target). Each is a protocol handshake (wait for the bus, the host's
#: request, an inhibit check, the host's parity and stop bits) or the test of
#: the direction flag in bit 6 of R1, which the lint calls pin-derived because
#: the receive path ORs the host's parity bit into R1. No wait loop is among
#: them: those run on constants.
EXPECTED_WARNINGS = (
    ("BZ", "tx_wait"),
    ("BZ", "rx_start"),
    ("BZ", "tx_wait"),
    ("BZ", "abort"),
    ("BZ", "tx_action"),
    ("BZ", "idle_wait"),
    ("BZ", "tx_wait"),
    ("BNZ", "idle_wait"),
    ("BZ", "rx_bad"),
    ("BZ", "rx_bad"),
)


# =======================================================================
# The board and the host
# =======================================================================


def ps2_board(dut):
    """Pads as a PS/2 board: a pull-up on CLK and on DATA, the six other
    `uio` lines tied low (a strong driver, so a program that drove one of
    them high would be reported as contention). Not started."""
    return UioPads(
        dut,
        pulls={CLK_BIT: "up", DATA_BIT: "up"},
        tie={p: 0 for p in range(8) if p not in (CLK_BIT, DATA_BIT)},
        name="ps2-board",
    )


def assert_ps2_open_drain(pads, tag):
    """After a PS/2 run: the design drove exactly CLK and DATA, only ever
    low, with no unknown `uio_oe` and no contention."""
    pads.assert_no_contention()
    assert pads.oe_unknown == 0, f"{tag}: uio_oe unknown on pins 0x{pads.oe_unknown:02x}"
    assert pads.oe_seen == OD_MASK, (
        f"{tag}: the design drove uio pins 0x{pads.oe_seen:02x}; a PS/2 device "
        f"must drive exactly CLK|DATA = 0x{OD_MASK:02x}"
    )
    assert pads.drove_high == 0, (
        f"{tag}: the design drove uio pins 0x{pads.drove_high:02x} HIGH; an open-drain pad only pulls low"
    )
    assert pads.drove_low == OD_MASK, (
        f"{tag}: the design pulled pins 0x{pads.drove_low:02x} low, expected both lines 0x{OD_MASK:02x}"
    )


class Host:
    """The PS/2 host: pulls the lines through the pad model, logs the bus.

    Every method that waits is a coroutine on simulation time. The log is a
    list of `ps2.Snap` taken at the end of every time step in which a line
    or a host puller changed."""

    def __init__(self, dut, pads):
        self.dut = dut
        self.pads = pads
        self.hclk = False
        self.hdata = False
        self.snaps = []
        self.bad_level = []
        self._ev = Event()
        self._task = None

    # ---- logging ---------------------------------------------------------
    def start(self):
        self._task = cocotb.start_soon(self._log())
        self._ev.set()  # take the first snapshot
        return self

    def stop(self):
        if self._task is not None:
            self._task.kill()
            self._task = None

    async def _log(self):
        while True:
            await First(ValueChange(self.dut.uio_in), self._ev.wait())
            self._ev.clear()
            await ReadOnly()
            lv = self.pads.levels
            clk, data = lv[CLK_BIT], lv[DATA_BIT]
            t = float(get_sim_time("ns"))
            if clk not in ("0", "1") or data not in ("0", "1"):
                self.bad_level.append((t, clk, data))
                continue
            snap = Snap(t, int(clk), int(data), self.hclk, self.hdata)
            if self.snaps and self.snaps[-1].t == t:
                self.snaps[-1] = snap
            else:
                self.snaps.append(snap)

    def now(self):
        return float(get_sim_time("ns"))

    # ---- pulling ---------------------------------------------------------
    def pull_clk(self, low):
        self.hclk = bool(low)
        if low:
            self.pads.pull_low(CLK_BIT)
        else:
            self.pads.release(CLK_BIT)
        self._ev.set()

    def pull_data(self, low):
        self.hdata = bool(low)
        if low:
            self.pads.pull_low(DATA_BIT)
        else:
            self.pads.release(DATA_BIT)
        self._ev.set()

    # ---- watching ----------------------------------------------------------
    def line(self, bit):
        return self.pads.level(bit)

    async def wait_line(self, bit, level, timeout_ns):
        """Wait until the line is `level`; False if `timeout_ns` passes first."""
        deadline = self.now() + timeout_ns
        while self.line(bit) != level:
            remaining = deadline - self.now()
            if remaining <= 0:
                return False
            await First(ValueChange(self.dut.uio_in), Timer(int(remaining), "ns"))
        return True

    async def wait_device_frame(self, first_timeout_ns=3_000 * US):
        """Wait for one whole device-to-host frame: 11 falling edges of CLK,
        then the 11th rising edge. Returns False if the device went quiet."""
        timeout = first_timeout_ns
        for _ in range(11):
            if not await self.wait_line(CLK_BIT, 0, timeout):
                return False
            timeout = 200 * US
            if not await self.wait_line(CLK_BIT, 1, 200 * US):
                return False
        await Timer(2 * US, "ns")  # let the logger take the last snapshot
        return True

    # ---- host procedures (the numbered steps are Chapweske's) ---------------
    async def inhibit(self, ns):
        """Hold CLK low for `ns` and let go."""
        self.pull_clk(True)
        await Timer(ns, "ns")
        self.pull_clk(False)

    async def request_to_send(self, inhibit_ns=120 * US):
        """Steps 1-3: CLK low for at least 100 us, DATA low, release CLK."""
        self.pull_clk(True)
        await Timer(inhibit_ns - 10 * US, "ns")
        self.pull_data(True)
        await Timer(10 * US, "ns")
        self.pull_clk(False)

    async def send(self, byte, *, parity=None, stop=1, abort_after=None, inhibit_ns=120 * US,
                   response_timeout_ns=15_000 * US):
        """A whole host-to-device transfer (steps 1-12). Returns True if the
        device answered every clock; with `abort_after=n` the host inhibits
        after the n-th pulse instead of finishing."""
        p = (1 - bin(byte).count("1") % 2) if parity is None else parity
        bits = [(byte >> i) & 1 for i in range(8)] + [p, stop]
        await self.request_to_send(inhibit_ns)
        for k, bit in enumerate(bits):
            # step 4 / 7: wait for the device to bring CLK low; step 5: set DATA
            if not await self.wait_line(CLK_BIT, 0, response_timeout_ns if k == 0 else 200 * US):
                self.pull_data(False)
                return False
            await Timer(15 * US, "ns")
            self.pull_data(bit == 0)
            # step 6: wait for the device to bring CLK high (it reads DATA there)
            if not await self.wait_line(CLK_BIT, 1, 200 * US):
                self.pull_data(False)
                return False
            if abort_after is not None and k + 1 == abort_after:
                await Timer(5 * US, "ns")
                self.pull_clk(True)
                self.pull_data(False)
                await Timer(inhibit_ns, "ns")
                self.pull_clk(False)
                return True
        # step 9: release DATA. A stop bit of 1 is already released. A 0 is kept
        # until the 11th pulse has begun: the host changes DATA only while CLK
        # is low, so it lets go in that pulse's low phase (the ACK is then
        # hidden behind the host's own low, which the model knows).
        if stop == 0:
            if not await self.wait_line(CLK_BIT, 0, 200 * US):
                return False
            self.pull_data(False)
        # steps 10-12: ACK, one more clock pulse, then the device lets go
        if stop == 1 and not await self.wait_line(DATA_BIT, 0, 200 * US):
            return False
        if stop == 1 and not await self.wait_line(CLK_BIT, 0, 200 * US):
            return False
        if not await self.wait_line(CLK_BIT, 1, 200 * US):
            return False
        ok = await self.wait_line(DATA_BIT, 1, 200 * US)
        await Timer(2 * US, "ns")  # let the logger take the last snapshot
        return ok


# =======================================================================
# Running a program and grading it
# =======================================================================


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


def committed_words():
    return parse_hex_image(HEX)


async def boot(dut, words):
    """Load `words` onto the PS/2 board and return `(host, pads)`, the
    logger running. No pad may be enabled from reset release to the end of
    the load."""
    assert len(words) <= 256
    pads = ps2_board(dut).start()
    await load_program(dut, words)
    assert pads.resets == 1 and pads.oe_seen == 0, (
        f"uio pads 0x{pads.oe_seen:02x} enabled between reset release and the end of the load"
    )
    host = Host(dut, pads).start()
    return host, pads


def finish(host, pads, tag, *, open_drain=True):
    """Stop the logger and the pads; return the model's grade of the log."""
    t_end = host.now()
    host.stop()
    pads.stop()
    if open_drain:
        assert_ps2_open_drain(pads, tag)
    if open_drain:
        assert not host.bad_level, f"{tag}: a bus line was unknown or floating: {host.bad_level[:3]}"
    return check(host.snaps, t_end)


def report(dut, tag, result):
    for v in result.violations[:10]:
        dut._log.error(f"[{tag}] {v}")
    for v in result.host_violations[:10]:
        dut._log.error(f"[{tag}] HOST {v}")
    frames = [(f.direction, f.byte, f.complete, f.aborted) for f in result.frames]
    dut._log.info(f"[{tag}] frames {frames}; margins (ns) {margins_text(result)}; "
                  f"measured (min, max ns) {measured_text(result)}")


def assert_clean(dut, tag, result):
    report(dut, tag, result)
    assert result.host_violations == [], f"[{tag}] the bench host broke the protocol: {result.host_violations[:3]}"
    assert result.violations == [], f"[{tag}] {len(result.violations)} violation(s): {[str(v) for v in result.violations[:5]]}"
    again = retransmission_violations(result)
    assert again == [], f"[{tag}] {[str(v) for v in again]}"


def mutate(text, old, new):
    assert text.count(old) == 1, f"mutation site {old!r} found {text.count(old)} times"
    return text.replace(old, new)


def kinds(result):
    return sorted({v.kind for v in result.violations})


def margins_text(result):
    return {k: round(v) for k, v in sorted(result.margins.items())}


def measured_text(result):
    """Smallest and largest measured value (ns) of each graded quantity."""
    return {k: (round(lo), round(hi)) for k, (lo, hi) in sorted(result.measured.items())}


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed image and report match the source; the program fits;
    every assembler lint warning is one of the documented handshakes."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    lines = SRC.read_text(encoding="utf-8").splitlines()
    got = []
    for w in program.warnings:
        m = re.match(r"line (\d+): (BNZ|BZ) ", w)
        assert m, w
        text = lines[int(m.group(1)) - 1]
        got.append((m.group(2), text.split(";")[0].split()[1]))
    assert tuple(got) == EXPECTED_WARNINGS, got
    words = committed_words()
    assert len(words) <= 256
    # the open-drain setup is the very first thing the program does to the pads
    text = SRC.read_text(encoding="utf-8")
    assert text.count("WCTL  UIO_OD, R3") == 1 and "UIO_DIR" not in re.sub(r";.*", "", text)
    dut._log.info(f"{len(words)} words, {len(program.warnings)} documented lint warnings")


@cocotb.test()
async def test_power_up_frame(dut):
    """From reset the device sends the BAT code 0xAA once, no sooner than
    50 us after the bus was idle, and then stays quiet."""
    start_clock(dut)
    host, pads = await boot(dut, committed_words())
    assert await host.wait_device_frame(), "no device frame after power-up"
    await Timer(3_000 * US, "ns")  # nothing more may happen
    result = finish(host, pads, "power-up")
    assert_clean(dut, "power-up", result)
    assert [(f.direction, f.byte) for f in result.complete()] == [("dev->host", 0xAA)]
    assert len(result.frames) == 1
    dut._log.info(f"power-up: hold-off {[round(x) for x in result.hold_off_ns]} ns, margins {margins_text(result)}")


@cocotb.test()
async def test_host_commands_are_acked_and_echoed(dut):
    """Request to send: the device clocks the byte in, pulls ACK, and then
    answers with the same byte as a device-to-host frame."""
    start_clock(dut)
    host, pads = await boot(dut, committed_words())
    assert await host.wait_device_frame(), "no power-up frame"
    want = [("dev->host", 0xAA)]
    for byte in ECHO_BYTES:
        assert await host.send(byte), f"host send {byte:#04x} failed"
        assert await host.wait_device_frame(100 * US * 100), f"no echo of {byte:#04x}"
        want += [("host->dev", byte), ("dev->host", byte)]
    result = finish(host, pads, "echo")
    assert_clean(dut, "echo", result)
    assert [(f.direction, f.byte) for f in result.complete()] == want
    assert all(f.parity_ok and f.stop_ok for f in result.complete())
    dut._log.info(f"echo: {len(ECHO_BYTES)} commands, response {[round(x) for x in result.rts_response_ns]} ns, "
                  f"margins {margins_text(result)}")


@cocotb.test()
async def test_bad_frames_get_resend(dut):
    """A host byte with wrong parity, and one with a 0 stop bit, are ACKed
    and answered with 0xFE; a good byte afterwards is echoed again."""
    start_clock(dut)
    host, pads = await boot(dut, committed_words())
    assert await host.wait_device_frame()
    want = [("dev->host", 0xAA)]
    cases = ((0xED, {"parity": 1 - (1 - bin(0xED).count("1") % 2)}, 0xFE),  # wrong parity
             (0x3C, {"stop": 0}, 0xFE),                                     # stop bit 0
             (0x3C, {}, 0x3C))                                              # recovery
    for byte, kw, answer in cases:
        assert await host.send(byte, **kw), f"host send {byte:#04x} {kw} failed"
        assert await host.wait_device_frame(), f"no answer to {byte:#04x} {kw}"
        want += [("host->dev", byte), ("dev->host", answer)]
    result = finish(host, pads, "resend")
    assert_clean(dut, "resend", result)
    assert [(f.direction, f.byte) for f in result.complete()] == want
    host_frames = [f for f in result.complete("host->dev")]
    assert [f.parity_ok for f in host_frames] == [False, True, True]
    assert [f.stop_ok for f in host_frames] == [True, False, True]


@cocotb.test()
async def test_inhibit_mid_frame_abandons_and_resends(dut):
    """The host holds CLK low after the 1st, 4th, 10th and 11th clock. Before
    the 11th the device must let go of DATA, stay quiet for the hold-off and
    then send the same frame again; after the 11th nothing is repeated."""
    start_clock(dut)
    for after, resent in ((1, True), (4, True), (10, True), (11, False)):
        host, pads = await boot(dut, committed_words())
        for k in range(after):
            assert await host.wait_line(CLK_BIT, 0, 3_000 * US), f"no clock {k + 1}"
            if k + 1 < after or after < 11:
                assert await host.wait_line(CLK_BIT, 1, 200 * US), f"no rise of clock {k + 1}"
        # 10 us after the rising edge of clock `after`; for the 11th, 5 us into its low phase
        await Timer(5 * US if after == 11 else 10 * US, "ns")
        await host.inhibit(130 * US)
        if resent:
            assert await host.wait_device_frame(), f"no resend after an inhibit at clock {after}"
        await Timer(1_500 * US, "ns")
        result = finish(host, pads, f"inhibit-{after}")
        assert_clean(dut, f"inhibit-{after}", result)
        tx = [f for f in result.frames if f.direction == "dev->host"]
        if resent:
            assert [(f.aborted, f.complete) for f in tx] == [(True, False), (False, True)], tx
            assert tx[1].byte == 0xAA
        else:
            assert [(f.aborted, f.complete) for f in tx] == [(False, True)], tx
        dut._log.info(f"inhibit after clock {after}: margins {margins_text(result)}")


@cocotb.test()
async def test_inhibited_bus_is_not_used(dut):
    """The host holds CLK low from reset for 400 us. The device sends
    nothing until CLK has been high for 50 us."""
    start_clock(dut)
    host, pads = await boot(dut, committed_words())
    host.pull_clk(True)
    await Timer(400 * US, "ns")
    host.pull_clk(False)
    assert await host.wait_device_frame(), "no frame after the inhibit"
    await Timer(1_000 * US, "ns")
    result = finish(host, pads, "inhibited-start")
    assert_clean(dut, "inhibited-start", result)
    assert [(f.direction, f.byte) for f in result.complete()] == [("dev->host", 0xAA)]
    assert min(result.hold_off_ns) >= 50 * US


@cocotb.test()
async def test_request_to_send_while_a_byte_is_pending(dut):
    """The host asks to send before the device has sent its BAT code. The
    device receives first; its single pending byte is replaced by the echo."""
    start_clock(dut)
    host, pads = await boot(dut, committed_words())
    await Timer(5 * US, "ns")
    assert await host.send(0xF2, inhibit_ns=120 * US)
    assert await host.wait_device_frame()
    await Timer(2_000 * US, "ns")
    result = finish(host, pads, "rts-early")
    assert_clean(dut, "rts-early", result)
    assert [(f.direction, f.byte) for f in result.complete()] == [("host->dev", 0xF2), ("dev->host", 0xF2)]


@cocotb.test()
async def test_host_abort_then_recovery(dut):
    """The host abandons its own transfer after 5 clocks (CLK held low). The
    device lets go of the bus, sends nothing, and a full transfer afterwards
    still works."""
    start_clock(dut)
    host, pads = await boot(dut, committed_words())
    assert await host.wait_device_frame()
    assert await host.send(0xED, abort_after=5)
    await Timer(3_000 * US, "ns")  # nothing may come back
    assert await host.send(0xF4)
    assert await host.wait_device_frame()
    result = finish(host, pads, "host-abort")
    assert_clean(dut, "host-abort", result)
    seq = [(f.direction, f.byte, f.complete) for f in result.frames]
    assert seq[0] == ("dev->host", 0xAA, True)
    assert seq[1][0] == "host->dev" and seq[1][2] is False, seq
    assert seq[2:] == [("host->dev", 0xF4, True), ("dev->host", 0xF4, True)], seq


@cocotb.test()
async def test_unused_pins_are_never_driven(dut):
    """Across a run with commands and an inhibit, `uio_oe` stays 0 on every
    pin but CLK and DATA, and reset leaves the pads released (checked by
    `assert_ps2_open_drain` in every test; this one also checks the idle
    state after the run)."""
    start_clock(dut)
    host, pads = await boot(dut, committed_words())
    assert await host.wait_device_frame()
    assert await host.send(0x5A)
    assert await host.wait_device_frame()
    await Timer(500 * US, "ns")
    oe = int(dut.uio_oe.value)
    out = int(dut.uio_out.value)
    assert oe & ~OD_MASK == 0, f"uio_oe = {oe:#04x}: a pin outside CLK|DATA is enabled"
    assert (out & OD_MASK) == OD_MASK and (oe & OD_MASK) == 0, (
        f"idle bus: uio_out {out:#04x} uio_oe {oe:#04x}; both lines should be released"
    )
    finish(host, pads, "pins")


def mutant_program(name, text):
    return asm.assemble_text(text, source_name=f"<mutant {name}>").words


async def run_mutant(dut, name, text, scenario, **kw):
    start_clock(dut)
    host, pads = await boot(dut, mutant_program(name, text))
    await scenario(host)
    result = finish(host, pads, f"mutant {name}", open_drain=False)
    dut._log.info(f"mutant {name}: {len(result.violations)} violation(s), kinds {kinds(result)}; "
                  f"{len(pads.contention)} contention episode(s); first: "
                  f"{result.violations[0] if result.violations else None}")
    return host, pads, result


async def scenario_power_up(host):
    await host.wait_device_frame()
    await Timer(500 * US, "ns")


async def scenario_inhibit_at_4(host):
    for _ in range(4):
        await host.wait_line(CLK_BIT, 0, 3_000 * US)
        await host.wait_line(CLK_BIT, 1, 200 * US)
    await Timer(10 * US, "ns")
    await host.inhibit(130 * US)
    await Timer(1_500 * US, "ns")


async def scenario_released_after_inhibit(host):
    host.pull_clk(True)
    await Timer(300 * US, "ns")
    host.pull_clk(False)
    await Timer(1_200 * US, "ns")


async def scenario_one_command(host):
    await host.wait_device_frame()
    await host.send(0xED)
    await host.wait_device_frame()
    await Timer(200 * US, "ns")


@cocotb.test()
async def test_negative_no_inhibit_check(dut):
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "BZ    abort            ; CLK low although released: the host inhibits",
                  "NOP                    ; (mutant) no inhibit check")
    _h, _p, result = await run_mutant(dut, "no-inhibit-check", text, scenario_inhibit_at_4)
    got = set(kinds(result)) | {v.kind for v in retransmission_violations(result)}
    assert got & {"hold-off", "stray-clock", "inhibit-release", "no-retransmit", "retransmit-mismatch"}, got
    assert result.violations or retransmission_violations(result)


@cocotb.test()
async def test_negative_short_hold_off(dut):
    text = mutate(SRC.read_text(encoding="utf-8"), "LDI   R2, 200 ", "LDI   R2, 18  ")
    _h, _p, result = await run_mutant(dut, "short-hold-off", text, scenario_released_after_inhibit)
    assert kinds(result) == ["hold-off"], kinds(result)


@cocotb.test()
async def test_negative_no_ack(dut):
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "LDI   R1, 0x40         ; DATA low: the ACK",
                  "LDI   R1, 0x48         ; (mutant) DATA stays released: no ACK")
    _h, _p, result = await run_mutant(dut, "no-ack", text, scenario_one_command)
    assert kinds(result) == ["no-ack"], kinds(result)


@cocotb.test()
async def test_negative_data_too_late(dut):
    src = SRC.read_text(encoding="utf-8")
    text = mutate(src, "LDI   R3, 0x10         ; 4 x 250 cycles\nw_mid:", "LDI   R3, 0x01         ; (mutant) 8 x 250 cycles\nw_mid:")
    _h, _p, result = await run_mutant(dut, "data-too-late", text, scenario_power_up)
    assert "data-setup" in kinds(result), kinds(result)
    assert set(kinds(result)) <= {"data-setup", "clk-high"}, kinds(result)


@cocotb.test()
async def test_negative_data_too_soon_after_rise(dut):
    src = SRC.read_text(encoding="utf-8")
    text = mutate(src, "LDI   R3, 0x10         ; 4 x 250 cycles\nw_high: WAIT  246",
                  "LDI   R3, 0x80         ; (mutant) 1 x 104 cycles\nw_high: WAIT  100")
    _h, _p, result = await run_mutant(dut, "data-too-soon", text, scenario_power_up)
    assert "data-after-rise" in kinds(result), kinds(result)
    assert set(kinds(result)) <= {"data-after-rise", "clk-high"}, kinds(result)


@cocotb.test()
async def test_negative_even_parity(dut):
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "        XOR   R1, R3           ; the odd-parity bit\n",
                  "")
    _h, _p, result = await run_mutant(dut, "even-parity", text, scenario_power_up)
    assert kinds(result) == ["parity"], kinds(result)


@cocotb.test()
async def test_negative_push_pull_instead_of_open_drain(dut):
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "WCTL  UIO_OD, R3       ; ... then open-drain on CLK and DATA",
                  "WCTL  UIO_DIR, R3      ; (mutant) push-pull on CLK and DATA")
    _h, pads, result = await run_mutant(dut, "push-pull", text, scenario_inhibit_at_4)
    assert pads.contention, "NEGATIVE CONTROL FAILED TO FAIL: the pad model saw no contention"
    assert pads.drove_high & OD_MASK, "the mutant should have driven a line high"
    try:
        assert_ps2_open_drain(pads, "push-pull mutant")
    except AssertionError:
        pass
    else:
        raise AssertionError("NEGATIVE CONTROL FAILED TO FAIL: the open-drain assertion passed")


@cocotb.test()
async def test_negative_parity_not_checked(dut):
    """Skipping the host-parity check is invisible to the bus model (the bus
    is legal). The byte comparison catches it: a bad-parity byte is echoed
    instead of answered with 0xFE."""
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "BZ    rx_bad           ; even number of ones: parity error",
                  "NOP                    ; (mutant) parity not checked")
    start_clock(dut)
    host, pads = await boot(dut, mutant_program("parity-not-checked", text))
    await host.wait_device_frame()
    bad_parity = 1 - (1 - bin(0xED).count("1") % 2)
    await host.send(0xED, parity=bad_parity)
    await host.wait_device_frame()
    result = finish(host, pads, "mutant parity-not-checked")
    answers = [f.byte for f in result.complete("dev->host")]
    assert answers[-1] == 0xED and answers[-1] != 0xFE, answers
    dut._log.info(f"mutant parity-not-checked: bus violations {kinds(result)}; answer {answers[-1]:#04x} (the golden answer is 0xFE)")


@cocotb.test()
async def test_negative_log_path_can_fail(dut):
    """Re-grade the golden power-up log with its DATA edges moved 30 us
    earlier: a 0 bit now changes 50 us before the falling edge, which the
    model must reject. That shows the log-and-grade path can fail."""
    start_clock(dut)
    host, pads = await boot(dut, committed_words())
    assert await host.wait_device_frame()
    await Timer(200 * US, "ns")
    t_end = host.now()
    result = finish(host, pads, "log-control")
    assert_clean(dut, "log-control", result)
    moved = [Snap(s.t - (30 * US if (i and s.data != host.snaps[i - 1].data and s.clk == 1) else 0), s.clk, s.data, s.hclk, s.hdata)
             for i, s in enumerate(host.snaps)]
    moved.sort(key=lambda s: s.t)
    bad = check(moved, t_end)
    assert bad.violations, "NEGATIVE CONTROL FAILED TO FAIL: the moved log still passed the model"
    dut._log.info(f"log control: {len(bad.violations)} violation(s), kinds {kinds(bad)}")
