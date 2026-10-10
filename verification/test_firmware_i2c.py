"""DUT-facing I2C firmware bench (issue #73, part of #23; target-spec
rows 1 and 12).

The claim this bench substantiates is the one `CLAUDE.md` demands for a
protocol ("firmware is evidence"): **committed** programs
(`firmware/asm/i2c_fast.asm`, `firmware/asm/i2c_std.asm`, images under
`firmware/build/`) loaded over the real serial load-phase pins onto the
real top (`tt_um_2amlogic_protocol_emulator`), executed by the ISA core,
with the SCL/SDA waveforms they drive captured off the simulation and
juded by the **independent** I2C reference model
(`verification/reference_models/i2c.py`) -- `check_transfer` finding the
START, sampling each of the 9 clocks per byte on the SCL rising edges,
re-deriving address/data/ACKs, and *measuring* t_LOW / t_HIGH / t_HD;STA
/ t_SU;STO against NXP UM10204 Table 10's own minimums, for both
Standard-mode (100 kHz class) and Fast-mode (400 kHz class) budgets.
Nothing here asserts the waveform against the bench's own idea of what
the program meant to send: the expected address and payload byte are the
only bench-side inputs, and the framing, sampling and timing verdicts all
come from the model.

What is measured, and in what units
-----------------------------------
**Cycles.** The phase budgets these programs implement are exactly
**65/60 core cycles** (Fast) and **235/200 core cycles** (Standard) per
SCL clock, which is what the model's ns measurements map onto at the
nominal 20 ns simulation clock: 1300/1200 ns and 4700/4000 ns -- the
Table 10 minimums, to the cycle. The cycle counts are the claim; any
kHz figure is arithmetic at target-spec row 4's **unconfirmed** clock
(same stance as `test_firmware_uart.py`; see
`verification/records/sta-corner-sweep/` for why row 4 is unconfirmed).

The bus the model grades is the pad-resolved line (issue #136)
-------------------------------------------------------------
Every run goes through the silicon-true pad model
(`verification/uio_pads.py`, DR 0012 section "Consequences"): per `uio`
pin the design's `uio_oe` / `uio_out`, a pull-up on SCL (`uio[2]`) and
on SDA (`uio[3]`), and the peripheral as an external open-drain driver
are resolved into one line, and that line is what `uio_in` reads. The
reactive peripheral watches the *line's* SCL (never the controller's
intent on `uio_out`) and pulls SDA low for the ACK slots it chooses to
acknowledge -- how a real I2C peripheral behaves. The two waveforms the
reference model grades are the SCL and SDA **lines** as sampled on
`uio_in`, so the ACK handshake still flows through the core's real `IN`
path, and now so does every level the controller itself puts on the bus.

Until issue #136 this bench composed the bus itself: `line = uio_out
AND uio_in`, with `uio_oe` never read. That is what an open-drain bus
does *if* the pads implement open-drain, so it could not tell a chip
that drives the line from one that cannot; before DR 0012 the top had
`uio_oe = 8'h00` and could not (DR 0008 section "Context"). The records
minted from that composition are superseded for that reason. Here a
line goes low only because the design enabled its pad and drove 0, or
the peripheral did. After each run the bench also checks what the pads
were seen doing: the design drove exactly SCL and SDA, only ever low,
with no contention.

The pad model is zero-delay and purely logical: it says nothing about
pull-up rise time, pad delay or drive strength (`uio_pads.py`, "Timing").

The ACK branch is exercised in both directions (two runs, one program)
---------------------------------------------------------------------
The committed program branches on the sampled address ACK (`IN` + `AND`
+ `BNZ` -- DR 0001's one sanctioned data-dependent branch). Run A has
the peripheral ACK the address and NACK the data byte: the branch falls
through, the data byte is transmitted, decoded by the model as
address 0x50 write + data 0x5A with acks [True, False]. Run B has the
peripheral NACK the address: the branch is taken, the transfer decodes
as address-only with acks [False] -- a different, shorter waveform from
the same committed program, which is what makes the branch load-bearing
rather than decorative.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
1. `stimulus.i2c_negative_short_stop_case` -- the reference model's own
   deterministic negative control (a Standard-mode transfer whose STOP
   setup is half the Table 10 t_SU;STO minimum) -- must FAIL
   `check_transfer` while still decoding, with the t_SU;STO violation
   the only one flagged.
2. The **DUT's own captured waveforms**, time-compressed by 0.9, must
   also FAIL `check_transfer` in both modes: both programs pace t_LOW
   exactly at the Table 10 floor (1300 ns Fast / 4700 ns Standard), so
   a uniform 0.9x compression drives t_LOW under the floor (and t_HIGH
   with it, in Standard mode) while leaving the transfer's structure --
   and therefore the model's decode -- intact. This is the stronger
   control: it proves this bench's capture-and-grade path can fail, not
   merely that a synthetic waveform can.
3. **`UIO_OD` left at reset** (issue #136): each committed image with
   its one `WCTL UIO_OD` word replaced by a reserved 1-cycle no-op, so
   the cycle timing is unchanged and every `OUT` still happens, but the
   pads stay inputs (DR 0012's reset state). The lines must never leave
   the pulled-up level, the peripheral must see no clock, and the model
   must find no transfer. The same run's `uio_out` *intent*, composed
   the old way, still decodes as a well-timed transfer -- which is
   exactly why the old composition was not evidence about the pins.

Driven by `klt functional-verification` (see
`verification/request-firmware-i2c.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the two `rtl/` modules it
instantiates and the vendored PDK macro model (`rtl/vendor/`). Like its
siblings, this file is *input* to `klt functional-verification`, not a
pytest module.

Everything is deterministic: two committed programs, fixed peripheral
ACK scripts, no randomization anywhere, so every run is
byte-reproducible.
"""

import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer

from reference_models import stimulus
from reference_models.i2c import (
    check_transfer,
    encode_transfer,
    minimum_ns,
)
from reference_models.waveform import Signal

# --- the unconfirmed-clock mapping, stated once -------------------------
#: Simulation clock period. 20 ns names target-spec row 4's **target**
#: 50 MHz; row 4 is unconfirmed (see the module docstring), so this value
#: is a nominal for the ns<->cycle mapping, never a measurement. The
#: reference model's minimums are ns; the programs' budgets are cycles;
#: 20 ns is the exchange rate this bench names, nothing more.
CLK_PERIOD_NS = 20


class _Mode:
    """One speed grade's cycle budgets and committed program names."""

    def __init__(self, name, fast_mode, t_low, t_high, t_hd_sta, t_su_sto):
        self.name = name
        self.fast_mode = fast_mode
        self.t_low = t_low
        self.t_high = t_high
        self.t_hd_sta = t_hd_sta
        self.t_su_sto = t_su_sto
        self.src = Path("firmware") / "asm" / f"{name}.asm"
        self.hex = Path("firmware") / "build" / f"{name}.hex"
        self.cycles = Path("firmware") / "build" / f"{name}.cycles.txt"

    @property
    def low_ns(self):
        return self.t_low * CLK_PERIOD_NS

    @property
    def high_ns(self):
        return self.t_high * CLK_PERIOD_NS


#: Fast-mode (400 kHz class): DR 0001's 65/60 allocation. Both floors of
#: UM10204 Table 10's Fast column are met (t_LOW exactly, t_HIGH 2x).
FAST = _Mode("i2c_fast", True, t_low=65, t_high=60, t_hd_sta=65, t_su_sto=60)

#: Standard-mode (100 kHz class): the sketch's floor-paced 235/200.
#: Both floors of Table 10's Standard column are met exactly.
STD = _Mode("i2c_std", False, t_low=235, t_high=200, t_hd_sta=205, t_su_sto=205)

MODES = (FAST, STD)

#: What the committed programs transmit (the only bench-side inputs the
#: comparison consumes): a write transfer to static address 0x50 of one
#: data byte 0x5A.
ADDRESS = 0x50
READ_BIT = False
DATA_BYTE = 0x5A

#: Pin plan of both programs: SCL on uio bit 2, SDA on uio bit 3 -- DR
#: 0010's target plan, the standard Tiny Tapeout I2C Pmod (issue #155).
#: `SCL_PIN` / `SDA_PIN` name the controller's *intent* (`uio_out`); the
#: line the model grades is read on `uio_in` (`LINE_PIN`).
SCL_PIN, SCL_BIT = "uio_out", 2
SDA_PIN, SDA_BIT = "uio_out", 3
LINE_PIN = "uio_in"

#: What every I2C run captures, per clock edge: the two bus lines as the
#: pads resolve them (graded), and the controller's intent (kept for the
#: UIO_OD negative control, never graded as the bus).
CAPTURE_SPECS = {
    "scl": (LINE_PIN, SCL_BIT),
    "sda": (LINE_PIN, SDA_BIT),
    "ctl_scl": (SCL_PIN, SCL_BIT),
    "ctl_sda": (SDA_PIN, SDA_BIT),
}


def i2c_pads(dut):
    """The pad model wired as this pin plan's I2C board: pull-ups on SCL
    and SDA, every other `uio` line tied low. The one place the I2C
    benches tell the pad model which pins the bus is on."""
    return i2c_board(dut, scl=SCL_BIT, sda=SDA_BIT)

#: Trailing capture margin past the program's static end, in cycles.
CAPTURE_MARGIN_CYCLES = 300

#: The DUT-waveform negative control's compression factor. Both programs
#: pace t_LOW exactly at the Table 10 floor, so any uniform compression
#: violates it; 0.9 also drives Standard t_HIGH under its floor.
NEGATIVE_CONTROL_SCALE = 0.9


try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

try:
    from firmware_artifacts import parse_cycle_sections as _parse_sections, parse_hex_image, total_cycles
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from firmware_artifacts import parse_cycle_sections as _parse_sections, parse_hex_image, total_cycles
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

# The load-phase driver and the capture scaffolding are NOT re-derived
# here: they are the ones already proven by
# `verification/records/program-load-phase/` (load_program) and landed by
# the UART sub-issue (#71, `verification/records/firmware-uart/` --
# CapturedPin / capture_pin_bits). Importing the functions (not the
# modules' tests) is deliberate -- cocotb discovers tests by scanning
# the *named* module's own namespace, so no sibling test is registered
# by these imports and `test_firmware_uart.py` /
# `test_protocol_emulator.py` stay byte-unchanged (live evidence records
# hash them).
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart import (  # noqa: E402
    CapturedPin,
    capture_pin_bits,
)
from uio_pads import (  # noqa: E402  (the pad model; no test objects)
    assert_i2c_open_drain,
    i2c_board,
)


# =======================================================================
# Committed-artifact readers
# =======================================================================


def load_committed_image(mode: _Mode) -> list:
    """Parse the committed hex image (one 4-hex-digit word per line)."""
    return parse_hex_image(REPO_ROOT / mode.hex)


def committed_report(mode: _Mode) -> str:
    return (REPO_ROOT / mode.cycles).read_text(encoding="utf-8")


def parse_cycle_sections(mode: _Mode) -> dict:
    """`CYCLES name=... start=... end=... cycles=...` report lines."""
    return _parse_sections(committed_report(mode))


def committed_total_cycles(mode: _Mode) -> int:
    return total_cycles(committed_report(mode))


def expected_section_cycles(mode: _Mode) -> dict:
    """Every `.cyclesec` of both programs mapped to its expected budget.

    The convention (documented in the `.asm` headers): a phase's section
    opens at the OUT that starts the phase and closes before the OUT that
    ends it, so the section's count IS the phase's measured length. The
    two `*_stop_*_low` sections open at the STOP path's SCL-fall OUT and
    include the SDA-low OUT inside, so they too equal the full pre-STOP
    low period.
    """
    expected = {
        "i2c_start": mode.t_hd_sta,
        "i2c_ack1_low": mode.t_low,
        "i2c_ack2_low": mode.t_low,
        "i2c_ack1_high": mode.t_high,
        "i2c_ack2_high": mode.t_high,
        "i2c_stop_data_low": mode.t_low,
        "i2c_stop_addr_low": mode.t_low,
        "i2c_stop_data": mode.t_su_sto,
        "i2c_stop_addr": mode.t_su_sto,
    }
    for byte in ("abit", "dbit"):
        for bit in range(1, 9):
            expected[f"i2c_{byte}{bit}_low"] = mode.t_low
            expected[f"i2c_{byte}{bit}_high"] = mode.t_high
    return expected


# =======================================================================
# The pad-resolved bus and the reactive peripheral
# =======================================================================


def wired_and(a: CapturedPin, b: CapturedPin) -> Signal:
    """Compose `a AND b` from two captures -- the bus this bench graded
    before issue #136, when it assumed open-drain pads instead of
    modelling them. **No pass in this file is graded on it any more.** It
    is kept for one purpose: the `UIO_OD` negative control composes the
    controller's `uio_out` intent this way to show that the old
    composition still reports a clean transfer on a chip whose pads never
    drive.

    Both captures were sampled on the same clock edges, so their
    transition lists share a time basis exactly; the line's transitions
    are the union of both sides' times at which the AND actually changes.
    """
    line = Signal(a.signal.initial & b.signal.initial,
                  name=f"({a.signal.name}&{b.signal.name})")
    events = sorted(
        [(t, v, "a") for (t, v) in a.signal.transitions]
        + [(t, v, "b") for (t, v) in b.signal.transitions]
    )
    va, vb = a.signal.initial, b.signal.initial
    for t, v, side in events:
        if side == "a":
            va = v
        else:
            vb = v
        line.add(t, va & vb)
    return line


def scale_signal(signal: Signal, factor: float) -> Signal:
    """A copy of the waveform with every transition time scaled by
    `factor` -- the negative control that re-grades this bench's OWN
    captured waveform as a too-fast transmitter."""
    clone = Signal(signal.initial, name=f"{signal.name}*{factor}")
    clone.transitions = [(t * factor, v) for (t, v) in signal.transitions]
    return clone


async def drive_peripheral(dut, pads, ack_falls: set) -> None:
    """Reactive I2C peripheral on the pad model's external side: watch
    the SCL **line**, count its falling edges, and pull the SDA line low
    for the ACK slots named in `ack_falls`.

    A real peripheral answers SCL, not a script -- but the *decision* of
    which bytes to acknowledge is the peripheral's own, and that is what
    `ack_falls` encodes (fall 9 = the address byte's ACK clock, fall 18 =
    the data byte's). The pull lands two cycles after the SCL fall it
    answers, well inside the 65/235-cycle low phase and long before both
    the controller's `IN` sample and the SCL rise the model samples on;
    the release lands on the next fall, i.e. inside the following low
    phase, which is the only place I2C lets SDA change.

    The peripheral is open-drain like every I2C device: it pulls SDA low
    or lets go, and never touches SCL in this bench (no stretching). It
    changes its drive 1 ns after the read-only sample of each edge, so it
    never races this bench's own captures and the line is stable at the
    next rising edge the core samples on.

    The SCL line idles high from reset (pull-up, every pad an input), so
    the first fall counted is the controller's first real one: a chip
    that never drives SCL low gives this peripheral nothing to answer.
    """
    previous = pads.level(SCL_BIT)
    falls = 0
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        scl = pads.level(SCL_BIT)
        await Timer(1, unit="ns")
        if previous == 1 and scl == 0:
            falls += 1
            if falls in ack_falls:
                pads.pull_low(SDA_BIT)
            else:
                pads.release(SDA_BIT)
        previous = scl


async def run_words(dut, tag: str, words: list, run_cycles: int,
                    ack_falls: set, expect_open_drain: bool = True):
    """Load `words` and run them on the I2C board (`i2c_pads`:
    pull-ups on SCL/SDA, the reactive peripheral above on the external
    side), capturing the two lines and the controller's intent on every
    clock edge. Returns `(captures, pads)`.

    The pad model runs from before reset: no `uio` pad may be enabled
    from reset release to the end of the load phase (DR 0012: every pin
    an input until a program configures it). With `expect_open_drain` (every run except
    the UIO_OD negative control) the run must end having driven exactly
    SCL and SDA, only ever low, without contention."""
    assert len(words) <= 256, "program exceeds DR 0001's 256-word memory"
    pads = i2c_pads(dut).start()
    await load_program(dut, words)
    assert pads.resets == 1 and pads.oe_seen == 0, (
        f"{tag}: uio pads 0x{pads.oe_seen:02x} were enabled between "
        "reset release and the end of the load phase (DR 0012: every uio "
        "pin is an input at reset)"
    )
    driver = cocotb.start_soon(drive_peripheral(dut, pads, ack_falls))
    caps = await capture_pin_bits(dut, CAPTURE_SPECS, run_cycles)
    driver.kill()
    pads.stop()
    if expect_open_drain:
        assert_i2c_open_drain(pads, tag)
    return caps, pads


async def run_program(dut, mode: _Mode, ack_falls: set) -> dict:
    """Load `mode`'s committed image, run it on the pads with the
    reactive peripheral acknowledging exactly the slots in `ack_falls`,
    and return the captures (the SCL/SDA lines the caller grades, plus
    the controller's intent)."""
    words = load_committed_image(mode)
    run_cycles = committed_total_cycles(mode) + CAPTURE_MARGIN_CYCLES
    dut._log.info(
        f"{mode.name}: capturing {run_cycles} cycles, peripheral ACKs "
        f"SCL falls {sorted(ack_falls)}"
    )
    caps, _pads = await run_words(dut, mode.name, words, run_cycles, ack_falls)
    return caps


def grade_transfer(caps: dict, mode: _Mode):
    """Hand the two pad-resolved lines to the independent model -- the
    decode and every timing verdict are the model's."""
    scl = caps["scl"].signal
    sda = caps["sda"].signal
    return scl, sda, check_transfer(scl, sda, fast_mode=mode.fast_mode)


def assert_measured_budgets(dut, mode: _Mode, report, scl: Signal) -> None:
    """The model's ns measurements, mapped back to the cycle domain and
    checked against the programs' committed budgets. Relative
    measurements between same-edge samples carry no clock-rate
    assumption; /20 ns is the named nominal of the module docstring."""
    m = report.measurements
    assert m["t_LOW(min)"] == mode.low_ns, (
        f"{mode.name}: model measured t_LOW(min) {m['t_LOW(min)']} ns, the "
        f"committed budget is {mode.t_low} cycles = {mode.low_ns} ns"
    )
    assert m["t_HIGH(min)"] == mode.high_ns, (
        f"{mode.name}: model measured t_HIGH(min) {m['t_HIGH(min)']} ns, the "
        f"committed budget is {mode.t_high} cycles = {mode.high_ns} ns"
    )
    hd_key = next(k for k in m if k.startswith("t_HD;STA@"))
    assert m[hd_key] == mode.t_hd_sta * CLK_PERIOD_NS, (
        f"{mode.name}: t_HD;STA {m[hd_key]} ns != {mode.t_hd_sta} cycles"
    )
    assert m["t_SU;STO"] == mode.t_su_sto * CLK_PERIOD_NS, (
        f"{mode.name}: t_SU;STO {m['t_SU;STO']} ns != "
        f"{mode.t_su_sto} cycles"
    )
    assert minimum_ns("t_LOW", mode.fast_mode) == mode.low_ns, (
        f"{mode.name}: t_LOW budget is not the Table 10 floor -- the "
        "negative control below depends on that equality"
    )
    dut._log.info(
        f"{mode.name}: measured t_LOW(min) {m['t_LOW(min)']} ns "
        f"({mode.t_low} cy), t_HIGH(min) {m['t_HIGH(min)']} ns "
        f"({mode.t_high} cy), t_HD;STA {m[hd_key]} ns, "
        f"t_SU;STO {m['t_SU;STO']} ns -- all at the committed budgets"
    )


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_images_are_fresh(dut):
    """Both committed build artifacts match their committed `.asm`
    sources, each program carries EXACTLY the one sanctioned
    data-dependent-latency warning (the address-ACK `BNZ`), and every
    `.cyclesec` states the budget this bench grades against (DR 0003:
    committed artifacts are the evidence, not regenerated ad hoc)."""
    for mode in MODES:
        program = asm.assemble_file(REPO_ROOT / mode.src)
        drift = asm.check_against(program, REPO_ROOT / mode.hex.parent)
        assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
        assert len(program.warnings) == 1, (
            f"{mode.name}: expected exactly the one sanctioned ACK-branch "
            f"warning, got {program.warnings}"
        )
        assert "BNZ" in program.warnings[0], (
            f"{mode.name}: the warning must be the ACK BNZ, got "
            f"{program.warnings[0]!r}"
        )
        sections = parse_cycle_sections(mode)
        expected = expected_section_cycles(mode)
        assert set(sections) == set(expected), (
            f"{mode.name}: section names diverge: "
            f"{set(sections) ^ set(expected)}"
        )
        for name, want in expected.items():
            _start, _end, got, _branches = sections[name]
            assert got == want, (
                f"{mode.name}: section {name} claims {got} cycles, this "
                f"bench grades {want}"
            )
        assert len(program.instructions) <= 256
        dut._log.info(
            f"{mode.name}: {len(program.instructions)} words, "
            f"{committed_total_cycles(mode)} fall-through cycles, "
            f"{len(sections)} cycle sections at budget, 1 sanctioned warning"
        )


@cocotb.test()
async def test_i2c_both_grades_pass_independent_reference_model(dut):
    """The claim: each committed program, loaded over the real
    load-phase pins and executed by the core, drives a write transfer to
    0x50 that the independent `check_transfer` decodes byte-exactly and
    grades inside every UM10204 Table 10 minimum for its speed grade,
    with the phase budgets measuring exactly 65/60 (Fast) and 235/200
    (Standard) core cycles. The address-ACK branch is exercised in both
    directions: run A (ACK -> data byte transmitted) and run B (NACK ->
    address-only transfer), same committed program.

    Every run is on the pad model: the lines graded are what `uio_in`
    reads, and each run ends with the check that the design drove exactly
    SCL and SDA, only ever low, without contention.

    The negative controls run on these same captured waveforms at the
    end, so a capture-and-grade path that could only ever pass fails
    here.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    for mode in MODES:
        # ---- run A: peripheral ACKs the address, NACKs the data byte.
        # SCL fall 9 = the address ACK clock, fall 18 = the data ACK.
        caps = await run_program(dut, mode, ack_falls={9})
        scl, sda, report = grade_transfer(caps, mode)
        dut._log.info(f"{mode.name} run A: {report}")
        assert report.ok, (
            f"{mode.name} run A failed the independent model: {report}"
        )
        assert report.address == ADDRESS and report.read_bit == READ_BIT
        assert report.data_bytes == [DATA_BYTE]
        assert report.acks == [True, False], (
            f"{mode.name} run A: expected ACK on the address byte and NACK "
            f"on the data byte, decoded {report.acks}"
        )
        assert report.stretched_clocks == 0, "no clock stretching was driven"
        assert_measured_budgets(dut, mode, report, scl)
        # nobody but the controller moves SCL in these runs (the
        # peripheral never stretches), so the SCL line must be the
        # controller's intent exactly -- which it only can be if the pad
        # pulls low on a 0 and the pull-up restores the line on a 1.
        # (`uio_out` resets to 0 while the pad is still an input, so the
        # intent starts with one rise the line never sees: the program's
        # `OUT 0x0C` that precedes `WCTL UIO_OD`.)
        intent = caps["ctl_scl"].signal
        assert intent.initial == 0 and intent.transitions[0][1] == 1
        assert (
            caps["scl"].signal.initial == 1
            and caps["scl"].signal.transitions == intent.transitions[1:]
        ), f"{mode.name} run A: the SCL line is not the controller's SCL"

        # ---- run B: peripheral NACKs the address -> the branch is taken,
        # the data byte is never transmitted, the transfer is shorter.
        caps_b = await run_program(dut, mode, ack_falls=set())
        scl_b, sda_b, report_b = grade_transfer(caps_b, mode)
        dut._log.info(f"{mode.name} run B: {report_b}")
        assert report_b.ok, (
            f"{mode.name} run B failed the independent model: {report_b}"
        )
        assert report_b.address == ADDRESS and report_b.read_bit == READ_BIT
        assert report_b.data_bytes == [], (
            f"{mode.name} run B: the address NACK must skip the data byte, "
            f"decoded {report_b.data_bytes}"
        )
        assert report_b.acks == [False]
        assert_measured_budgets(dut, mode, report_b, scl_b)

        # ---- negative control on the DUT's OWN captured waveform: a
        # uniform 0.9x time compression keeps the transfer's structure
        # (the model still decodes it) but must break the timing floor
        # the program paces exactly at -- t_LOW in both grades, t_HIGH
        # too in Standard. A capture path that could only ever pass
        # fails here.
        for run, run_scl, run_sda, run_report in (
            ("A", scl, sda, report),
            ("B", scl_b, sda_b, report_b),
        ):
            squeezed = check_transfer(
                scale_signal(run_scl, NEGATIVE_CONTROL_SCALE),
                scale_signal(run_sda, NEGATIVE_CONTROL_SCALE),
                fast_mode=mode.fast_mode,
            )
            assert not squeezed.ok, (
                f"NEGATIVE CONTROL FAILED TO FAIL ({mode.name} run {run}): "
                f"a {NEGATIVE_CONTROL_SCALE}x-compressed copy of the DUT's "
                f"own waveform still passed check_transfer with violations "
                f"{squeezed.violations!r}"
            )
            low_violations = [
                v for v in squeezed.violations if v.startswith("t_LOW")
            ]
            assert low_violations, (
                f"{mode.name} run {run}: the compressed waveform must "
                f"violate the exactly-floored t_LOW, got "
                f"{squeezed.violations!r}"
            )
            assert squeezed.data_bytes == run_report.data_bytes, (
                f"{mode.name} run {run}: the negative control must only "
                "mistime the transfer, not change what it decodes"
            )
            dut._log.info(
                f"negative control ({mode.name} run {run} x"
                f"{NEGATIVE_CONTROL_SCALE}): {len(squeezed.violations)} "
                f"violation(s), first {squeezed.violations[0]!r}"
            )


#: `WCTL k, Rs` is `OUT` to port 00 with imm8 = k (DR 0012 section 1);
#: UIO_OD is k = 0x01. The mask ignores the source-register field.
_WCTL_UIO_OD_MASK, _WCTL_UIO_OD = 0xF3FF, 0xA001
#: `OUT` to port 01 is DR 0012's reserved encoding: a 1-cycle no-op.
_RESERVED_NOP_PORT = 0x0100


def without_uio_od(words: list) -> list:
    """The image with its `WCTL UIO_OD` turned into DR 0012's reserved
    1-cycle no-op (`OUT` to port 01, same source register): the program
    runs cycle for cycle as before and performs every `OUT`, but `UIO_OD`
    keeps its reset value of 0, so every pad stays an input."""
    hits = [i for i, w in enumerate(words)
            if w & _WCTL_UIO_OD_MASK == _WCTL_UIO_OD]
    assert len(hits) == 1, (
        f"expected exactly one WCTL UIO_OD in the image, found {len(hits)}"
    )
    mutant = list(words)
    mutant[hits[0]] |= _RESERVED_NOP_PORT
    return mutant


@cocotb.test()
async def test_uio_od_left_at_reset_cannot_drive_the_bus(dut):
    """Negative control for the pad path (issue #136): the committed
    programs with `UIO_OD` left at its reset value must NOT produce an
    I2C transfer on the lines.

    Each image runs with its one `WCTL UIO_OD` replaced by a reserved
    no-op of the same length. Required, per grade: no pad is ever
    enabled; SCL and SDA never leave the pulled-up level; the peripheral,
    which answers the SCL line, is never clocked and never pulls SDA; and
    the independent model finds no transfer on the lines.

    The same run then shows what this bench used to grade. The
    controller's intent on `uio_out` is unchanged by the mutation, and
    composed the pre-#136 way (`uio_out AND` a released peripheral) the
    model decodes it as a well-timed transfer to 0x50. So the old
    composition passes on a design that cannot pull a line low -- the
    reason its records are superseded.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    for mode in MODES:
        words = without_uio_od(load_committed_image(mode))
        run_cycles = committed_total_cycles(mode) + CAPTURE_MARGIN_CYCLES
        # the peripheral would ACK both bytes if it ever saw the clocks
        caps, pads = await run_words(
            dut, f"{mode.name} without UIO_OD", words, run_cycles,
            ack_falls={9, 18}, expect_open_drain=False,
        )
        tag = f"{mode.name} with UIO_OD at reset"
        pads.assert_no_contention()
        assert pads.oe_unknown == 0
        assert pads.oe_seen == 0, (
            f"NEGATIVE CONTROL FAILED TO FAIL ({tag}): pads "
            f"0x{pads.oe_seen:02x} were enabled without a UIO_OD write"
        )
        for line in ("scl", "sda"):
            sig = caps[line].signal
            assert sig.initial == 1 and not sig.transitions, (
                f"NEGATIVE CONTROL FAILED TO FAIL ({tag}): the {line} line "
                f"moved ({sig.transitions[:4]}...) though no pad was enabled"
            )
        assert pads.ext[SDA_BIT] is None, (
            f"{tag}: the peripheral pulled SDA though SCL never fell"
        )
        try:
            _scl, _sda, report = grade_transfer(caps, mode)
            found = report.ok or report.address is not None
            detail = repr(report)
        except ValueError as exc:
            found, detail = False, f"model rejected the lines: {exc}"
        assert not found, (
            f"NEGATIVE CONTROL FAILED TO FAIL ({tag}): the model found a "
            f"transfer on lines that never moved: {detail}"
        )
        dut._log.info(f"negative control ({tag}), lines: {detail}")

        # What the pre-#136 composition concludes from this same run.
        released = CapturedPin("released-peripheral", 1)
        old_scl = wired_and(caps["ctl_scl"], released)
        old_sda = wired_and(caps["ctl_sda"], released)
        assert caps["ctl_scl"].signal.transitions, (
            f"{tag}: the program stopped issuing OUTs -- the mutation must "
            "leave the controller's intent intact"
        )
        composed = check_transfer(old_scl, old_sda, fast_mode=mode.fast_mode)
        assert composed.ok and composed.address == ADDRESS, (
            f"{tag}: expected the bench-composed bus (uio_out intent, pads "
            f"ignored) to still decode a clean transfer, got {composed}"
        )
        assert composed.acks == [False] and composed.data_bytes == [], (
            f"{tag}: composed intent decoded {composed}"
        )
        dut._log.info(
            f"negative control ({tag}), bench-composed from uio_out intent "
            f"(pads ignored, NOT evidence): {composed}"
        )


@cocotb.test()
async def test_reference_model_negative_control_still_fails(dut):
    """The reference model's own deterministic negative control, re-run
    here so this bench's pass is citable: a nominal `encode_transfer`
    passes `check_transfer` in both grades, and
    `stimulus.i2c_negative_short_stop_case` -- a Standard-mode transfer
    whose STOP setup runs at half the Table 10 t_SU;STO minimum, every
    other parameter legal -- FAILS it with the t_SU;STO violation the
    only one flagged, while still decoding.

    No DUT run: this grades the model, which is what makes it a control
    on the grader rather than on the design.
    """
    # nominal model waveforms pass in both grades (bounds calibrated)
    for mode in MODES:
        scl = Signal(1, name=f"model-nominal-{mode.name}")
        sda = Signal(1, name=f"model-nominal-{mode.name}")
        encode_transfer(
            ADDRESS, READ_BIT, [DATA_BYTE], [False], mode.fast_mode, scl, sda
        )
        report = check_transfer(scl, sda, fast_mode=mode.fast_mode)
        assert report.ok, (
            f"a nominal reference-model transfer must pass check_transfer "
            f"({mode.name}); if it does not, the minimums are misread: "
            f"{report}"
        )
        dut._log.info(f"model nominal ({mode.name}): {report}")

    # the model's own short-stop-setup control fails, t_SU;STO only
    scl, sda = stimulus.i2c_negative_short_stop_case()
    report = check_transfer(scl, sda, fast_mode=False)
    dut._log.info(f"negative control (short stop setup): {report}")
    assert not report.ok, (
        "NEGATIVE CONTROL FAILED TO FAIL: "
        "i2c_negative_short_stop_case passed check_transfer"
    )
    assert report.data_bytes == [0x00] and report.acks == [True, True], (
        "the negative control must still decode -- its whole point is a "
        "failure only the timing measurement catches"
    )
    assert len(report.violations) == 1 and report.violations[0].startswith(
        "t_SU;STO"
    ), (
        f"the control must flag exactly the t_SU;STO violation, got "
        f"{report.violations!r}"
    )
