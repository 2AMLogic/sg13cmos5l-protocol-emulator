"""DUT-facing SPI firmware bench (issue #72, part of #23; target-spec
rows 1 and 11).

The claim this bench substantiates is the one `CLAUDE.md` demands for a
protocol ("firmware is evidence"): **committed** programs
(`firmware/asm/spi_mode{0..3}.asm`, images `firmware/build/spi_mode*.hex`)
loaded over the real serial load-phase pins onto the real top
(`tt_um_2amlogic_protocol_emulator`), executed by the ISA core, with the
SCLK/MOSI/CS pins they drive -- and the MISO pin an independent
peripheral-emulator coroutine drives back -- captured off the simulation
and judged by the **independent** SPI reference model
(`verification/reference_models/spi.py`): `check_burst` re-derives both
data streams by sampling on the mode-correct edges, checks each mode's
idle levels and chip-select envelope, and enforces row 11's
SCLK <= f_clk/4 ceiling at the named core clock. Nothing here asserts the
waveform against the bench's own idea of what the program meant to send:
the expected payload bytes are the only bench-side inputs, and the
framing, sampling and timing verdicts all come from the model.

One program per mode (all four Motorola combinations), each with two
full-duplex bursts (an `IN` samples MISO every bit in both):

1. a **ceiling burst** at exactly 4 core cycles per SCLK period
   (SCLK = f_clk/4, DR 0001's ceiling), MOSI byte `0xA5`;
2. a **functional burst** at 8 cycles/bit (under the ceiling), MOSI byte
   `0x3C`, whose loop also extracts and assembles the received MISO bits
   and echoes the assembled byte on `uo_out[7:0]` after CS releases --
   DUT-side receive evidence the bench checks against the byte its
   peripheral coroutine drove (`0x5A`).

What is measured, and in what units
-----------------------------------
**Cycles.** The SCLK period is measured at the pin as the spacing between
captured SCLK transitions, in rising edges of the core clock. The ceiling
burst measures exactly **4 cycles** (2-cycle half-periods); the
functional burst exactly 8. Those numbers are independent of any clock
frequency.

**Any MHz figure is arithmetic at an unconfirmed clock.** The bench runs
its simulation clock at `CLK_PERIOD_NS = 20` purely to *name* target-spec
row 4's nominal 50 MHz, and passes that same nominal to `check_burst` as
`f_clk_hz` so the model's f_clk/4 ceiling is the 80 ns that 4 cycles x
20 ns works out to. Row 4 is *unconfirmed* on this program's own klt flow
(STA against this core is blocked -- `verification/records/
sta-corner-sweep/`), exactly as the sibling UART record already states. A
different clock rate would change the Hz number and change nothing this
bench measures: the measured ceiling is the 4-cycle period itself.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Three, all graded by the model's own `check_burst`:

1. `stimulus.spi_negative_ceiling_case` (the reference model's own
   deterministic over-ceiling control, f_clk/3) must FAIL with the
   ceiling named in the violation.
2. `stimulus.spi_negative_wrong_mode_case` (mode-0 traffic judged as
   mode 1) must NOT round-trip -- the checker is mode-sensitive.
3. The **DUT's own captured ceiling burst**, re-graded under each of the
   three wrong modes, must fail (violation or wrong bytes). This is the
   strongest of the three: it proves this bench's capture-and-check path
   can fail, not merely that a synthetic waveform can.

Driven by `klt functional-verification` (see
`verification/request-firmware-spi.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the two `rtl/` modules it
instantiates and the vendored PDK macro model (`rtl/vendor/`). Like its
siblings, this file is *input* to `klt functional-verification`, not a
pytest module.

Everything is deterministic: four committed programs, fixed payload
bytes, a cycle-counted reactive peripheral, no randomization anywhere, so
every run is byte-reproducible.
"""

import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer

from reference_models.spi import MODES, check_burst
from reference_models.stimulus import (
    spi_negative_ceiling_case,
    spi_negative_wrong_mode_case,
)

# --- the unconfirmed-clock mapping, stated once -------------------------
#: Simulation clock period. 20 ns names target-spec row 4's **target**
#: 50 MHz; row 4 is unconfirmed (see the module docstring), so this value
#: is a nominal for the ns<->cycle mapping, never a measurement.
CLK_PERIOD_NS = 20

#: The nominal core clock handed to `check_burst` so row 11's
#: SCLK <= f_clk/4 ceiling is graded in ns (f_clk/4 = 80 ns = 4 cycles at
#: the nominal). Arithmetic at the unconfirmed clock above, not a
#: measurement.
F_CLK_HZ = 1e9 / CLK_PERIOD_NS

# --- the pin map (fixed pin-port table; see each program's header) ------
CS_BIT, SCLK_BIT, MOSI_BIT = 0, 1, 2  # uo_out bits
MISO_PIN, MISO_BIT = "uio_in", 0      # peripheral-driven input pin

#: What each committed program transmits, what the bench's peripheral
#: coroutine drives back on MISO, and the `.cyclesec` names guarding the
#: two bursts. The echo byte is the functional burst's MISO byte -- the
#: program echoes what it assembled.
CEIL_TX, FUNC_TX = 0xA5, 0x3C
CEIL_MISO, FUNC_MISO = 0xC3, 0x5A
CEIL_CYCLES_PER_BIT, FUNC_CYCLES_PER_BIT = 4, 8

#: Trailing capture margin, in cycles, past the program's HALT -- enough
#: for the echo to be observed held on uo_out.
CAPTURE_MARGIN_CYCLES = 8


try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

# The serial load-phase driver is NOT re-derived here, and neither is the
# per-cycle pin capture: both are imported (functions, not modules' tests)
# from the benches that already proved them -- `load_program` from
# `test_protocol_emulator.py` (core-datapath record), and the
# protocol-agnostic capture scaffolding from `test_firmware_uart.py`
# (issue #71's UART bench), as this issue's body instructs ("reuse
# whatever helper ... the UART sub-issue factors out"). Importing a
# function registers no sibling tests: cocotb discovers tests by scanning
# the *named* module's own namespace only.
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart import CapturedPin, capture_pin_bits  # noqa: E402

ASM_DIR = REPO_ROOT / "firmware" / "asm"
BUILD_DIR = REPO_ROOT / "firmware" / "build"


def program_paths(mode_number: int):
    stem = f"spi_mode{mode_number}"
    return (
        ASM_DIR / f"{stem}.asm",
        BUILD_DIR / f"{stem}.hex",
        BUILD_DIR / f"{stem}.cycles.txt",
    )


def committed_report(mode_number: int) -> str:
    return program_paths(mode_number)[2].read_text(encoding="utf-8")


def committed_total_cycles(mode_number: int) -> int:
    match = re.search(r"^TOTAL-CYCLES (\d+)$", committed_report(mode_number), re.M)
    assert match, f"committed report for mode {mode_number} is missing TOTAL-CYCLES"
    return int(match.group(1))


def parse_cycle_sections(mode_number: int) -> dict:
    pattern = re.compile(
        r"^CYCLES name=(\S+) start=(\d+) end=(\d+) cycles=(\d+) branches=(\S+)$"
    )
    sections = {}
    for line in committed_report(mode_number).splitlines():
        match = pattern.match(line)
        if match:
            name, start, end, cycles, branches = match.groups()
            sections[name] = (int(start), int(end), int(cycles), branches)
    return sections


# =======================================================================
# The independent peripheral: drives MISO from the pins it observes
# =======================================================================


def _bit(byte: int, k: int) -> int:
    """Bit k of `byte`, MSB first (SPI data order, per the model)."""
    return (byte >> (7 - k)) & 1


async def drive_miso(dut, mode, miso_bytes, cycles: int):
    """Reactive peripheral-side MISO driver, one pass per core clock.

    Presents each burst's MISO byte the way the reference model's own
    `encode_burst` would (the model is the convention's authority): CPHA=0
    peripherals present bit 0 at CS fall and bit k at the previous
    trailing edge; CPHA=1 peripherals present bit k at each leading edge.
    The coroutine reads CS/SCLK in the read-only region after each edge
    (post-settle, same discipline as the capture) and writes MISO 1 ns
    later, so its changes land strictly after the capture's sample for
    that edge and strictly before the next one -- deterministic against
    the capture, and never at a sampling instant.
    """
    idle = mode.cpol
    burst = -1
    bit_k = 0
    # prev_cs starts as None (not 1): at run-phase entry uo_out still
    # reads its reset value (all low) until the program's setup OUT
    # drives the released/idle image, so a first-read CS of 0 must not be
    # mistaken for a CS fall -- only a 1 -> 0 edge is.
    prev_sclk, prev_cs = idle, None
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        uo = int(dut.uo_out.value)
        cs = (uo >> CS_BIT) & 1
        sclk = (uo >> SCLK_BIT) & 1
        await Timer(1, unit="ns")
        write = None
        if prev_cs == 1 and cs == 0 and burst < len(miso_bytes) - 1:
            # CS fall: a new burst begins. Once the planned bursts are all
            # presented the driver goes inert -- the functional burst's
            # echoed byte reuses uo_out[0] as a data bit, which is not a
            # CS assertion (the capture-side burst-count assert is the
            # authority on how many bursts really happened).
            burst += 1
            bit_k = 0
            if mode.cpha == 0:
                write = _bit(miso_bytes[burst], 0)
                bit_k = 1
        elif burst >= 0 and prev_cs == 0 and cs == 0 and sclk != prev_sclk:
            if mode.cpha == 0 and sclk == idle and bit_k < 8:
                write = _bit(miso_bytes[burst], bit_k)  # after a trailing edge
                bit_k += 1
            elif mode.cpha == 1 and sclk != idle and bit_k < 8:
                write = _bit(miso_bytes[burst], bit_k)  # after a leading edge
                bit_k += 1
        if write is not None:
            dut.uio_in.value = write
        prev_sclk, prev_cs = sclk, cs


# =======================================================================
# Capture post-processing helpers
# =======================================================================


def burst_windows(cs: CapturedPin) -> list:
    """[(fall_time, rise_time, fall_cycle, rise_cycle)] per CS-low burst."""
    windows = []
    fall = None
    for (t, v), c in zip(cs.signal.transitions, cs.transition_cycles):
        if v == 0:
            assert fall is None, "nested CS assertion"
            fall = (t, c)
        elif v == 1 and fall is not None:
            windows.append((fall[0], t, fall[1], c))
            fall = None
    return windows


def cycles_between(captured: CapturedPin, t0: float, t1: float) -> list:
    """The captured transition cycle indices with times in [t0, t1]."""
    return [
        c
        for (t, _v), c in zip(captured.signal.transitions, captured.transition_cycles)
        if t0 <= t <= t1
    ]


def uo_byte_at(caps: dict, cycle: int) -> int:
    """The captured uo_out byte during cycle `cycle` (bits uo0..uo7)."""
    byte = 0
    for i in range(8):
        pin = caps[f"uo{i}"]
        value = pin.signal.initial
        for (_t, v), c in zip(pin.signal.transitions, pin.transition_cycles):
            if c <= cycle:
                value = v
            else:
                break
        byte |= value << i
    return byte


def load_hex(mode_number: int) -> list:
    words = []
    for line in program_paths(mode_number)[1].read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            words.append(int(line, 16))
    assert words, "committed image is empty"
    return words


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_images_are_fresh(dut):
    """The committed build artifacts match the committed `.asm` sources,
    the programs are lint-clean, and the per-bit budgets the bench grades
    against are the ones the committed cycle reports state (DR 0003:
    committed artifacts are the evidence, not regenerated ad hoc)."""
    for mode_number in range(4):
        src, _hex, _cyc = program_paths(mode_number)
        program = asm.assemble_file(src)
        drift = asm.check_against(program, _hex.parent)
        assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
        assert program.warnings == [], (
            f"mode {mode_number} program must be lint-clean (no branch may "
            "depend on IN-sampled data; these programs branch not at all)"
        )
        assert len(program.instructions) <= 256, "exceeds DR 0001's 256 words"

        sections = parse_cycle_sections(mode_number)
        for section, per_bit in (
            (f"spi_mode{mode_number}_ceil", CEIL_CYCLES_PER_BIT),
            (f"spi_mode{mode_number}_func", FUNC_CYCLES_PER_BIT),
        ):
            assert section in sections, f"committed report is missing {section!r}"
            _start, _end, cycles, branches = sections[section]
            assert cycles == 8 * per_bit, (
                f"section {section} claims {cycles} cycles, this bench grades "
                f"8 bits x {per_bit} cycles"
            )
            assert branches == "false", (
                f"section {section} should be straight-line (no branches)"
            )
        dut._log.info(
            f"mode {mode_number}: {len(program.instructions)} words, "
            f"{committed_total_cycles(mode_number)} cycles to execute"
        )


@cocotb.test()
async def test_all_four_modes_pass_independent_reference_model(dut):
    """The claim, per mode: the committed program, loaded over the real
    load-phase pins and executed by the core, drives bursts that the
    independent `check_burst` grades conformant (idle levels, CS envelope,
    SCLK <= f_clk/4) with both data streams decoded byte-exact -- MOSI
    matching the program's committed payload, MISO matching the byte this
    bench's peripheral coroutine drove -- the ceiling burst's SCLK period
    measuring exactly 4 core cycles at the pin, the functional burst's
    exactly 8, and the echoed assembled RX byte matching the functional
    MISO byte.

    The wrong-mode negative control runs on the same captured ceiling
    burst at the end of each mode's pass, so a capture path that could
    only ever pass fails here.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    for mode_number in range(4):
        mode = MODES[mode_number]
        words = load_hex(mode_number)
        await load_program(dut, words)

        run_cycles = committed_total_cycles(mode_number) + CAPTURE_MARGIN_CYCLES
        driver = cocotb.start_soon(
            drive_miso(dut, mode, [CEIL_MISO, FUNC_MISO], run_cycles)
        )
        specs = {
            "cs": ("uo_out", CS_BIT),
            "sclk": ("uo_out", SCLK_BIT),
            "mosi": ("uo_out", MOSI_BIT),
            "miso": (MISO_PIN, MISO_BIT),
        }
        for i in range(8):
            specs[f"uo{i}"] = ("uo_out", i)
        caps = await capture_pin_bits(dut, specs, run_cycles)
        await driver
        cs, sclk, mosi, miso = caps["cs"], caps["sclk"], caps["mosi"], caps["miso"]

        windows = burst_windows(cs)
        assert len(windows) == 2, (
            f"expected exactly 2 CS bursts, captured {len(windows)}"
        )
        for index, (expected_tx, expected_miso, per_bit, label) in enumerate(
            (
                (CEIL_TX, CEIL_MISO, CEIL_CYCLES_PER_BIT, "ceiling"),
                (FUNC_TX, FUNC_MISO, FUNC_CYCLES_PER_BIT, "functional"),
            )
        ):
            tf, tr, cf, cr = windows[index]
            report = check_burst(
                sclk.signal,
                mosi.signal,
                miso.signal,
                cs.signal,
                mode,
                F_CLK_HZ,
                t0=tf,
                t1=tr,
            )
            dut._log.info(f"mode {mode_number} {label} burst: {report}")
            assert report.ok, (
                f"mode {mode_number} {label} burst violated the model: "
                f"{report.violations}"
            )
            assert report.mosi_bytes == [expected_tx], (
                f"mode {mode_number} {label}: model decoded MOSI "
                f"{report.mosi_bytes!r}, the committed program transmits "
                f"0x{expected_tx:02x}"
            )
            assert report.miso_bytes == [expected_miso], (
                f"mode {mode_number} {label}: model decoded MISO "
                f"{report.miso_bytes!r}, the bench peripheral drove "
                f"0x{expected_miso:02x}"
            )
            assert report.sclk_period_ns == per_bit * CLK_PERIOD_NS, (
                f"mode {mode_number} {label}: SCLK period measures "
                f"{report.sclk_period_ns:.3f} ns, expected exactly "
                f"{per_bit} x {CLK_PERIOD_NS} ns"
            )

            # The same measurement in the cycle domain (clock-rate
            # independent): every SCLK half-period in the burst window.
            edge_cycles = cycles_between(sclk, tf, tr)
            gaps = [b - a for a, b in zip(edge_cycles, edge_cycles[1:])]
            assert len(gaps) == 15, (
                f"mode {mode_number} {label}: {len(gaps) + 1} SCLK edges in "
                f"the window (gaps {gaps}), expected 16"
            )
            half = per_bit // 2
            assert all(gap == half for gap in gaps), (
                f"mode {mode_number} {label}: SCLK half-periods {gaps} "
                f"cycles, expected uniform {half}"
            )

        # ---- DUT-side receive evidence: the echoed assembled byte ------
        _tf, _tr, _cf, rise_cycle = windows[1]
        echo_at = None
        for cycle in range(rise_cycle + 1, rise_cycle + 5):
            if uo_byte_at(caps, cycle) == FUNC_MISO:
                echo_at = cycle
                break
        assert echo_at is not None, (
            f"mode {mode_number}: the assembled RX byte 0x{FUNC_MISO:02x} "
            f"never appeared on uo_out after CS released (last captured "
            f"byte 0x{uo_byte_at(caps, run_cycles):02x})"
        )
        assert uo_byte_at(caps, run_cycles) == FUNC_MISO, (
            f"mode {mode_number}: uo_out did not hold the echo through the "
            "end of the capture"
        )
        dut._log.info(
            f"mode {mode_number}: echoed RX byte 0x{FUNC_MISO:02x} on uo_out "
            f"at cycle {echo_at}, held to the end"
        )

        # ---- negative control: the DUT's own burst under wrong modes ----
        tf, tr, _cf, _cr = windows[0]
        for wrong in MODES:
            if wrong.number == mode.number:
                continue
            wrong_report = check_burst(
                sclk.signal,
                mosi.signal,
                miso.signal,
                cs.signal,
                wrong,
                F_CLK_HZ,
                t0=tf,
                t1=tr,
            )
            failed = (not wrong_report.ok) or wrong_report.mosi_bytes != [CEIL_TX]
            assert failed, (
                f"NEGATIVE CONTROL FAILED TO FAIL: mode {mode_number}'s "
                f"captured ceiling burst round-tripped under wrong mode "
                f"{wrong.number}: {wrong_report}"
            )
        dut._log.info(
            f"mode {mode_number}: captured ceiling burst fails all 3 wrong "
            "modes, as required"
        )


@cocotb.test()
async def test_reference_model_negative_controls_still_fail(dut):
    """The reference model's own deterministic negative controls, re-run
    here so this bench's pass is citable (issue #72 acceptance criterion
    3): an f_clk/3 burst must be flagged with the ceiling named, and
    mode-0 traffic judged as mode 1 must not round-trip.

    No DUT run: this grades the model, which is what makes it a control
    on the grader rather than on the design.
    """
    sclk, mosi, miso, cs, mosi_bytes, miso_bytes = spi_negative_ceiling_case(F_CLK_HZ)
    report = check_burst(sclk, mosi, miso, cs, MODES[0], F_CLK_HZ)
    assert not report.ok, "over-ceiling burst passed"
    assert any("f_clk/4 ceiling" in violation for violation in report.violations), (
        f"ceiling violation not named: {report.violations}"
    )
    dut._log.info(f"negative control (over-ceiling): {report}")

    sclk, mosi, miso, cs, mosi_bytes, miso_bytes = spi_negative_wrong_mode_case()
    report = check_burst(sclk, mosi, miso, cs, MODES[1], F_CLK_HZ)
    assert (
        report.mosi_bytes != mosi_bytes or report.miso_bytes != miso_bytes
    ), "mode-0 traffic round-tripped under mode-1 sampling rules"
    dut._log.info(f"negative control (wrong mode): {report}")
