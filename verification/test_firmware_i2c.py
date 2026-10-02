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

The bus the model grades is a wired-AND the bench composes
----------------------------------------------------------
The core drives its open-drain *intent* on `uio_out` (SCL = bit 0,
SDA = bit 7; writing 1 releases the line, 0 asserts it low), and the
peripheral's intent is driven onto `uio_in` by this bench's reactive
driver (a coroutine that watches the controller's SCL and pulls SDA low
for the ACK slots it chooses to acknowledge -- exactly how a real I2C
peripheral behaves). The line the reference model grades is
``controller_output AND peripheral_output`` per bit, composed from the
per-cycle captures -- the wired-AND an open-drain bus physically is.
This composition is deliberate and is the honest reading of this RTL:
`uio_oe` is fixed to 0 at the top level (`src/tt_um_2amlogic_
emulator.v`), so on silicon no firmware drive would reach a physical
pin at all -- DR 0001's own flagged open question (its "Consequences"
section names I2C's SDA direction change explicitly). That gap is
raised as its own issue rather than worked around here; what this bench
proves on this RTL is that the firmware's cycle timing and protocol
behavior are correct at the point the core drives and samples, with the
ACK handshake flowing through the core's real `IN` path.

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
   control: it proves this bench's compose-and-grade path can fail, not
   merely that a synthetic waveform can.

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

#: Pin plan of both programs: SCL on uio bit 0, SDA on uio bit 7.
SCL_PIN, SCL_BIT = "uio_out", 0
SDA_PIN, SDA_BIT = "uio_out", 7

#: Trailing capture margin past the program's static end, in cycles.
CAPTURE_MARGIN_CYCLES = 300

#: The DUT-waveform negative control's compression factor. Both programs
#: pace t_LOW exactly at the Table 10 floor, so any uniform compression
#: violates it; 0.9 also drives Standard t_HIGH under its floor.
NEGATIVE_CONTROL_SCALE = 0.9


def _find_repo_root() -> Path:
    """Locate the repo root from this bench's file location or the cwd
    (same anchors as `test_firmware_uart.py`: `klt
    functional-verification` may run the module from a scratch dir)."""
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parent)
    except NameError:  # pragma: no cover - defensive
        pass
    candidates.append(Path.cwd())
    for start in candidates:
        for probe in [start, *start.parents]:
            if (probe / "firmware" / "tools" / "asm.py").exists() and (
                probe / "spec" / "target-spec.md"
            ).exists():
                return probe
    raise RuntimeError(
        "cannot locate the repo root (needed for firmware/ and the "
        "committed build artifacts); run via klt functional-verification "
        "from the repository, or from any directory inside it"
    )


REPO_ROOT = _find_repo_root()
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

# The load-phase driver, the capture scaffolding and the cycle-domain
# helpers are NOT re-derived here: they are the ones already proven by
# `verification/records/program-load-phase/` (load_program) and landed by
# the UART sub-issue (#71, `verification/records/firmware-uart/` --
# CapturedPin / capture_pin_bits / cycle_at_time). Importing the
# functions (not the modules' tests) is deliberate -- cocotb discovers
# tests by scanning the *named* module's own namespace, so no sibling
# test is registered by these imports and `test_firmware_uart.py` /
# `test_protocol_emulator.py` stay byte-unchanged (live evidence records
# hash them).
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart import (  # noqa: E402
    CapturedPin,
    capture_pin_bits,
    cycle_at_time,
)


# =======================================================================
# Committed-artifact readers
# =======================================================================


def load_committed_image(mode: _Mode) -> list:
    """Parse the committed hex image (one 4-hex-digit word per line)."""
    words = []
    for line in (REPO_ROOT / mode.hex).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            words.append(int(line, 16))
    assert words, f"committed image {mode.hex} is empty"
    return words


def committed_report(mode: _Mode) -> str:
    return (REPO_ROOT / mode.cycles).read_text(encoding="utf-8")


def parse_cycle_sections(mode: _Mode) -> dict:
    """`CYCLES name=... start=... end=... cycles=...` report lines."""
    pattern = re.compile(
        r"^CYCLES name=(\S+) start=(\d+) end=(\d+) cycles=(\d+) branches=(\S+)$"
    )
    sections = {}
    for line in committed_report(mode).splitlines():
        match = pattern.match(line)
        if match:
            name, start, end, cycles, branches = match.groups()
            sections[name] = (int(start), int(end), int(cycles), branches)
    return sections


def committed_total_cycles(mode: _Mode) -> int:
    match = re.search(r"^TOTAL-CYCLES (\d+)$", committed_report(mode), re.M)
    assert match, f"committed report for {mode.name} lacks a TOTAL-CYCLES line"
    return int(match.group(1))


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
# The wired-AND bus composition and the reactive peripheral
# =======================================================================


def wired_and(a: CapturedPin, b: CapturedPin) -> Signal:
    """Compose the open-drain bus line `a AND b`.

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


#: Released-bus pin value the peripheral drives on `uio_in` (SCL bit 0
#: and SDA bit 7 both released = 0x81); the ACK pull clears SDA's bit.
_RELEASED = 0x81
_ACK_PULL = 0x01


async def drive_peripheral(dut, ack_falls: set) -> None:
    """Reactive I2C peripheral: watch the controller's SCL intent
    (`uio_out` bit 0), count falling edges, and pull SDA low on the
    `uio_in` bit-7 side for the ACK slots named in `ack_falls`.

    A real peripheral answers SCL, not a script -- but the *decision* of
    which bytes to acknowledge is the peripheral's own, and that is what
    `ack_falls` encodes (fall 9 = the address byte's ACK clock, fall 18 =
    the data byte's). The pull lands two cycles after the SCL fall it
    answers, well inside the 65/235-cycle low phase and long before both
    the controller's `IN` sample and the SCL rise the model samples on;
    the release lands on the next fall, i.e. inside the following low
    phase, which is the only place I2C lets SDA change.

    Writes happen 1 ns after the read-only sample of each edge, so they
    never race this bench's own captures and are stable at the next
    rising edge the core samples on.
    """
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    dut.uio_in.value = _RELEASED  # release the bus before the core's
    # first OUT (load_program leaves uio_in at 0; the idle bus must read
    # released so the wired-AND line follows the controller alone)
    previous = 0  # uio_out resets to 0: no phantom fall before the
    # controller's first release OUT (counting that reset state as a fall
    # would shift every ACK slot by one)
    falls = 0
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        scl = (int(dut.uio_out.value) >> SCL_BIT) & 1
        await Timer(1, unit="ns")
        if previous == 1 and scl == 0:
            falls += 1
            dut.uio_in.value = _ACK_PULL if falls in ack_falls else _RELEASED
        previous = scl


async def run_program(dut, mode: _Mode, ack_falls: set) -> dict:
    """Load `mode`'s committed image, run it with the reactive peripheral
    acknowledging exactly the slots in `ack_falls`, capture all four pin
    bits, and return the captured pins (controller SCL/SDA + peripheral
    SCL/SDA). The caller composes and grades the wired-AND lines."""
    words = load_committed_image(mode)
    assert len(words) <= 256, "program exceeds DR 0001's 256-word memory"
    await load_program(dut, words)
    run_cycles = committed_total_cycles(mode) + CAPTURE_MARGIN_CYCLES
    dut._log.info(
        f"{mode.name}: capturing {run_cycles} cycles, peripheral ACKs "
        f"SCL falls {sorted(ack_falls)}"
    )
    driver = cocotb.start_soon(drive_peripheral(dut, ack_falls))
    caps = await capture_pin_bits(
        dut,
        {
            "ctl_scl": (SCL_PIN, SCL_BIT),
            "ctl_sda": (SDA_PIN, SDA_BIT),
            "per_scl": ("uio_in", SCL_BIT),
            "per_sda": ("uio_in", SDA_BIT),
        },
        run_cycles,
    )
    driver.kill()
    return caps


def grade_transfer(caps: dict, mode: _Mode):
    """Compose the wired-AND bus and hand BOTH lines to the independent
    model -- the decode and every timing verdict are the model's."""
    scl = wired_and(caps["ctl_scl"], caps["per_scl"])
    sda = wired_and(caps["ctl_sda"], caps["per_sda"])
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

    The negative controls run on these same captured waveforms at the
    end, so a compose-and-grade path that could only ever pass fails
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
        # the peripheral never pulled SCL (its side only ever rose to the
        # released level at run start -- no stretching, no clock pulls)
        assert all(
            v == 1 for (_t, v) in caps["per_scl"].signal.transitions
        ), "the peripheral must not pull SCL in these runs (no stretching)"

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
