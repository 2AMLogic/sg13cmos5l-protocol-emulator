"""DUT-facing UART firmware bench (issue #71, part of #23; target-spec
rows 1 and 10).

The claim this bench substantiates is the one `CLAUDE.md` demands for a
protocol ("firmware is evidence"): a **committed** program
(`firmware/asm/uart_tx.asm`, image `firmware/build/uart_tx.hex`) loaded
over the real serial load-phase pins onto the real top
(`tt_um_2amlogic_protocol_emulator`), executed by the ISA core, with the
TX pin it drives captured off the simulation and judged by the
**independent** UART reference model
(`verification/reference_models/uart.py`) -- `UartDecoder` finding the
start bits, reassembling the bytes and *measuring* the frame's
actual-vs-nominal bit timing, then `check_frame` grading that measurement
against target-spec row 10's bound. Nothing here asserts the waveform
against the bench's own idea of what the program meant to send: the
expected payload bytes are the only bench-side inputs, and the framing,
sampling and timing verdicts all come from the model.

What is measured, and in what units
-----------------------------------
**Cycles.** The bit period this program implements is exactly
**50 core cycles**, which is what the cycle-domain assertions below
measure at the pin: the spacing between consecutive TX edges inside a
frame, in rising edges of the core clock. That number is independent of
any clock frequency.

**Any baud/microsecond figure is arithmetic at an unconfirmed clock.**
DR 0001's UART sketch states the 50-cycle budget as "1 µs = 1,000,000
baud at the target 50 MHz core clock of target-spec row 4". Row 4 is
*unconfirmed* on this program's own klt flow (STA against this core is
blocked -- `verification/records/sta-corner-sweep/`), exactly as
`verification/records/program-load-phase/` already states for its own
81.94 µs figure. So this bench runs its simulation clock at
`CLK_PERIOD_NS = 20` ns purely to *name* that nominal, and decodes with
`UartDecoder(BAUD)` where `BAUD` is derived from the same arithmetic
(`1e9 / (50 cycles x 20 ns)` = 1,000,000). A different clock rate would
change the baud number and change nothing this bench measures. The
sibling `test_protocol_emulator.py` uses a 10 ns period for the same
reason in reverse -- its assertions are counted in edges, so the ns value
there is immaterial.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Two, both graded by the model's own `check_frame`:

1. `encode_slow_frame`'s deterministic 1.025x-scaled transmitter (the
   reference model's own negative control) must FAIL the row-10 drift
   bound while still decoding to the right byte -- the case only the
   *timing* measurement catches.
2. The **DUT's own captured waveform**, time-scaled by the same 1.025x,
   must also FAIL. This is the stronger of the two: it proves this
   bench's capture-and-decode path can fail, not merely that a synthetic
   waveform can.

Driven by `klt functional-verification` (see
`verification/request-firmware-uart.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the two `rtl/` modules it
instantiates and the vendored PDK macro model (`rtl/vendor/`). Like its
siblings, this file is *input* to `klt functional-verification`, not a
pytest module.

Everything is deterministic: one committed program, two fixed payload
bytes, no randomization anywhere, so every run is byte-reproducible.
"""

import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

from reference_models.uart import (
    MAX_FRAME_DRIFT_PCT,
    UART_DATA_BITS,
    UART_FRAME_BITS,
    UartDecoder,
    bit_period_ns,
    encode_frame,
    encode_slow_frame,
)
from reference_models.waveform import Signal

# --- the unconfirmed-clock mapping, stated once -------------------------
#: Simulation clock period. 20 ns names target-spec row 4's **target**
#: 50 MHz; row 4 is unconfirmed (see the module docstring), so this value
#: is a nominal for the ns<->cycle mapping, never a measurement.
CLK_PERIOD_NS = 20

#: The measured quantity: cycles per UART bit, as implemented by
#: `firmware/asm/uart_tx.asm`. Cross-checked against the committed
#: cycle-accounting report's own `.cyclesec` sections below, so a firmware
#: change that moves the period fails here rather than silently re-grading.
BIT_PERIOD_CYCLES = 50

#: Arithmetic at the unconfirmed clock above: 1e9 / (50 x 20) = 1,000,000.
#: Used only to parameterize the reference-model decoder's nominal grid.
BAUD = round(1e9 / (BIT_PERIOD_CYCLES * CLK_PERIOD_NS))

# --- what the committed program transmits -------------------------------
#: Payload bytes, in order, and the `.cyclesec` name guarding each frame's
#: per-bit loop in `firmware/asm/uart_tx.asm`. 0x5A ends in a 0 data bit
#: and 0xA5 in a 1, so both stop-bit adjacencies are exercised.
FRAMES = ((0x5A, "uart_bit_frame1"), (0xA5, "uart_bit_frame2"))

#: Cycles from one frame's START anchor to the next frame's START anchor,
#: derived statically from `uart_tx.asm`'s instruction stream (not from
#: observing the DUT): START -> STOP spans 9 bit periods, and the
#: inter-frame tail is `OUT` (1) + `WAIT 255` (256) + three `LDI` (3).
INTERFRAME_TAIL_CYCLES = 1 + 256 + 3
FRAME_PITCH_CYCLES = (UART_FRAME_BITS - 1) * BIT_PERIOD_CYCLES + INTERFRAME_TAIL_CYCLES

#: TX pin: bit 0 of the dedicated output port (`uo_out`).
TX_PIN, TX_BIT = "uo_out", 0

#: Trailing capture margin, in cycles, past the program's static end --
#: enough for the model's 10-bit frame window to close on the last frame.
CAPTURE_MARGIN_CYCLES = 2 * BIT_PERIOD_CYCLES

#: The reference model's own deterministic negative-control scale factor.
NEGATIVE_CONTROL_SCALE = 1.025


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

# The serial load-phase driver is NOT re-derived here: it is the one
# already proven by `verification/records/core-datapath/`. Importing the
# function (not the module's tests) is deliberate -- cocotb discovers
# tests by scanning the *named* module's own namespace
# (`RegressionManager.discover_tests`), so no sibling test is registered
# by this import, and `test_protocol_emulator.py` stays byte-unchanged
# (a live evidence record hashes it).
from test_protocol_emulator import load_program  # noqa: E402

UART_SRC = REPO_ROOT / "firmware" / "asm" / "uart_tx.asm"
UART_HEX = REPO_ROOT / "firmware" / "build" / "uart_tx.hex"
UART_CYCLES = REPO_ROOT / "firmware" / "build" / "uart_tx.cycles.txt"


# =======================================================================
# Committed-artifact readers
# =======================================================================


def load_committed_image() -> list:
    """Parse the committed hex image (one 4-hex-digit word per line)."""
    return parse_hex_image(UART_HEX)


def committed_report() -> str:
    return UART_CYCLES.read_text(encoding="utf-8")


def parse_cycle_sections() -> dict:
    """`CYCLES name=... start=... end=... cycles=...` report lines."""
    return _parse_sections(committed_report())


def committed_total_cycles() -> int:
    return total_cycles(committed_report())


def program_run_cycles() -> int:
    """The program's **statically known** execution length, in cycles.

    The assembler's `TOTAL-CYCLES` is the fall-through sum, so it counts
    each per-bit loop body exactly once. Each frame's loop runs
    `UART_DATA_BITS` times under an LDI-loaded, assemble-time-constant
    trip count (DR 0001's blessed loop shape -- the count never comes
    from a pin), so the remaining iterations are a literal, not a
    measurement: `(UART_DATA_BITS - 1)` extra bodies per frame at the
    committed section's own cycle count.
    """
    sections = parse_cycle_sections()
    extra = 0
    for _payload, section in FRAMES:
        extra += (UART_DATA_BITS - 1) * sections[section][2]
    return committed_total_cycles() + extra


def expected_edge_offsets(payload: int) -> list:
    """Bit-period multiples, relative to the frame's start edge, at which
    an 8N1 frame for `payload` changes level -- computed from the framing
    convention alone (idle high, start 0, 8 data bits LSB-first, stop 1).

    Used only to check *where edges may legally be*; the payload itself is
    recovered by the independent decoder, never from this list.
    """
    levels = [0] + [(payload >> i) & 1 for i in range(UART_DATA_BITS)] + [1]
    offsets = []
    previous = 1  # idle high before the start bit
    for k, level in enumerate(levels):
        if level != previous:
            offsets.append(k)
        previous = level
    return offsets


# =======================================================================
# Pin capture -- reusable scaffolding (the SPI/I2C sub-issues of #23 reuse
# this; it is deliberately protocol-agnostic and knows nothing about UART)
# =======================================================================


class CapturedPin:
    """One captured pin bit: a reference-model `Signal` plus, for each of
    its transitions, the core-clock cycle index that transition landed on.

    The cycle indices are what makes a *cycle-domain* timing measurement
    possible (`gaps_cycles()`), independent of the simulation clock
    period; the `Signal` is what the reference models consume.
    """

    def __init__(self, name: str, initial: int):
        self.signal = Signal(initial, name=name)
        self.transition_cycles = []

    def observe(self, cycle: int, t_ns: float, value: int) -> None:
        if value != self.signal.current():
            self.signal.add(t_ns, value)
            self.transition_cycles.append(cycle)

    def gaps_cycles(self, first: int = 0, last: int = None) -> list:
        """Cycle gaps between consecutive transitions whose cycle index is
        in `[first, last]`."""
        chosen = [
            c
            for c in self.transition_cycles
            if c >= first and (last is None or c <= last)
        ]
        return [b - a for a, b in zip(chosen, chosen[1:])]

    def time_scaled(self, factor: float) -> Signal:
        """A copy of the captured waveform with every transition time
        stretched by `factor` -- the negative control that re-grades this
        bench's *own* captured waveform as a mistimed transmitter."""
        clone = Signal(self.signal.initial, name=f"{self.signal.name}*{factor}")
        clone.transitions = [(t * factor, v) for (t, v) in self.signal.transitions]
        return clone


def cycle_at_time(captured: CapturedPin, t_ns: float) -> int:
    """The core-clock cycle index of the captured transition at `t_ns`.

    This is how a *model-reported* time (e.g. a `UartFrameReport`'s
    `t_start`) is carried back into the cycle domain for a clock-rate-
    independent measurement: the model decides where each frame begins,
    this helper only looks up which clock edge that instant was.
    """
    for (t, _value), cycle in zip(
        captured.signal.transitions, captured.transition_cycles
    ):
        if t == t_ns:
            return cycle
    raise AssertionError(
        f"no captured transition at t={t_ns} ns on {captured.signal.name!r}"
    )


async def capture_pin_bits(dut, specs: dict, cycles: int) -> dict:
    """Sample the given pin bits after each of the next `cycles` rising
    edges, returning `{name: CapturedPin}`.

    `specs` maps a capture name to `(top-level output name, bit index)`.
    Sampling is **every** clock edge -- never a coarser poll that could
    step over a bit boundary -- and each sample is taken in the `ReadOnly`
    region so the edge's nonblocking assignments have settled (the same
    read discipline `test_protocol_emulator.py`'s `settle_read`
    documents). Cycle 0 is the edge the capture starts from (for a
    program run, the MODE-drop edge `load_program` returns on).
    """
    await ReadOnly()
    caps = {
        name: CapturedPin(name, (int(getattr(dut, pin).value) >> bit) & 1)
        for name, (pin, bit) in specs.items()
    }
    await Timer(1, unit="ns")  # leave the read-only region

    for cycle in range(1, cycles + 1):
        await RisingEdge(dut.clk)
        await ReadOnly()
        t_ns = float(get_sim_time("ns"))
        samples = {
            name: (int(getattr(dut, pin).value) >> bit) & 1
            for name, (pin, bit) in specs.items()
        }
        await Timer(1, unit="ns")  # leave the read-only region
        for name, value in samples.items():
            caps[name].observe(cycle, t_ns, value)
    return caps


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed build artifacts match the committed `.asm` source,
    and the per-bit cycle budget the bench grades against is the one the
    committed cycle report states (DR 0003: committed artifacts are the
    evidence, not regenerated ad hoc)."""
    program = asm.assemble_file(UART_SRC)
    drift = asm.check_against(program, UART_HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    assert program.warnings == [], (
        "the UART program must be lint-clean: no branch may depend on "
        "IN-sampled data (DR 0001 'Timing model')"
    )

    sections = parse_cycle_sections()
    for _payload, name in FRAMES:
        assert name in sections, f"committed report is missing section {name!r}"
        _start, _end, section_cycles, branches = sections[name]
        assert section_cycles == BIT_PERIOD_CYCLES, (
            f"section {name} claims {section_cycles} cycles/bit, this bench "
            f"grades {BIT_PERIOD_CYCLES}"
        )
        assert branches == "true", (
            f"section {name} should contain the constant-trip-count BNZ loop"
        )

    dut._log.info(
        f"committed program: {len(program.instructions)} words, "
        f"{committed_total_cycles()} fall-through cycles, "
        f"{program_run_cycles()} cycles to execute"
    )


@cocotb.test()
async def test_uart_frames_pass_independent_reference_model(dut):
    """The claim: the committed UART program, loaded over the real
    load-phase pins and executed by the core, drives 8N1 frames that the
    independent `UartDecoder` recovers byte-for-byte and that
    `check_frame` grades inside target-spec row 10's drift bound -- and
    whose bit period measures exactly `BIT_PERIOD_CYCLES` core cycles at
    the pin.

    The negative control runs on this same captured waveform at the end,
    so a capture path that could only ever pass fails here.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    words = load_committed_image()
    assert len(words) <= 256, "program exceeds DR 0001's 256-word memory"

    await load_program(dut, words)
    run_cycles = program_run_cycles() + CAPTURE_MARGIN_CYCLES
    dut._log.info(f"capturing {TX_PIN}[{TX_BIT}] for {run_cycles} cycles")
    caps = await capture_pin_bits(dut, {"tx": (TX_PIN, TX_BIT)}, run_cycles)
    tx = caps["tx"]

    # ---- the independent model does the decoding and the grading ------
    decoder = UartDecoder(BAUD)
    reports = decoder.decode(tx.signal)
    assert len(reports) == len(FRAMES), (
        f"decoder found {len(reports)} frame(s), expected {len(FRAMES)}: "
        f"{reports}"
    )
    for report, (payload, _section) in zip(reports, FRAMES):
        dut._log.info(f"decoded {report}")
        assert report.data == payload, (
            f"decoder recovered 0x{report.data:02x}, the committed program "
            f"transmits 0x{payload:02x}"
        )
        assert report.stop_ok, "framing error: stop bit sampled 0"
        assert decoder.check_frame(report), (
            f"row-10 drift bound failed: {report.drift_pct:.3f}% of the bit "
            f"period (bound {MAX_FRAME_DRIFT_PCT}%)"
        )

    # ---- the measurement, in cycles (clock-rate-independent) ----------
    # Each frame's start instant is the *model's* finding; this only maps
    # it onto the clock edge it happened on, so the timing numbers below
    # are in cycles and carry no clock-rate assumption.
    starts = [cycle_at_time(tx, report.t_start) for report in reports]
    assert starts[1] - starts[0] == FRAME_PITCH_CYCLES, (
        f"frame pitch measured {starts[1] - starts[0]} cycles, static "
        f"instruction-stream arithmetic says {FRAME_PITCH_CYCLES}"
    )

    for index, ((payload, _section), start) in enumerate(zip(FRAMES, starts)):
        window_end = start + UART_FRAME_BITS * BIT_PERIOD_CYCLES
        edges = [
            c for c in tx.transition_cycles if start <= c <= window_end
        ]
        offsets = [c - start for c in edges]
        want = [k * BIT_PERIOD_CYCLES for k in expected_edge_offsets(payload)]
        assert offsets == want, (
            f"frame {index} (0x{payload:02x}) edge offsets {offsets} cycles; "
            f"8N1 framing at {BIT_PERIOD_CYCLES} cycles/bit requires {want}"
        )
        gaps = [b - a for a, b in zip(edges, edges[1:])]
        assert gaps, f"frame {index} has no measurable intra-frame interval"
        assert min(gaps) == BIT_PERIOD_CYCLES, (
            f"frame {index}: smallest measured interval between TX edges is "
            f"{min(gaps)} cycles, expected exactly {BIT_PERIOD_CYCLES} "
            f"(DR 0001's UART bit-period budget)"
        )
        assert all(gap % BIT_PERIOD_CYCLES == 0 for gap in gaps), (
            f"frame {index}: intra-frame intervals {gaps} are not whole "
            f"multiples of the {BIT_PERIOD_CYCLES}-cycle bit period"
        )
        dut._log.info(
            f"frame {index}: 0x{payload:02x}, start edge at cycle {start}, "
            f"intra-frame intervals {gaps} cycles, bit period "
            f"{min(gaps)} cycles"
        )

    # ---- negative control on the DUT's OWN captured waveform ----------
    stretched = tx.time_scaled(NEGATIVE_CONTROL_SCALE)
    stretched_reports = UartDecoder(BAUD).decode(stretched)
    assert len(stretched_reports) == len(FRAMES), (
        "negative control changed the frame count; it must only mistime the "
        f"frames: {stretched_reports}"
    )
    for report in stretched_reports:
        dut._log.info(f"negative control (captured x{NEGATIVE_CONTROL_SCALE}): {report}")
        assert not UartDecoder(BAUD).check_frame(report), (
            "NEGATIVE CONTROL FAILED TO FAIL: a "
            f"{NEGATIVE_CONTROL_SCALE}x-mistimed copy of the DUT's own "
            f"waveform still passed check_frame at {report.drift_pct:.3f}% "
            "drift -- this bench cannot be trusted to detect a timing error"
        )


@cocotb.test()
async def test_reference_model_negative_control_still_fails(dut):
    """The reference model's own deterministic negative control, re-run
    here so this bench's pass is citable: a nominal `encode_frame` at the
    same baud passes `check_frame`, and `encode_slow_frame`'s 1.025x bit
    periods FAIL it while still decoding to the correct byte -- the
    timing-only failure mode the row-10 measurement exists to catch.

    No DUT run: this grades the model, which is what makes it a control
    on the grader rather than on the design.
    """
    payload = FRAMES[0][0]
    period_ns = bit_period_ns(BAUD)
    assert period_ns == BIT_PERIOD_CYCLES * CLK_PERIOD_NS, (
        "the ns<->cycle mapping stated in this module's docstring does not "
        f"hold: {period_ns} ns/bit vs {BIT_PERIOD_CYCLES} x {CLK_PERIOD_NS}"
    )

    decoder = UartDecoder(BAUD)

    good = Signal(1, name="model-nominal")
    encode_frame(payload, BAUD, good, t0=period_ns)
    good_reports = decoder.decode(good)
    assert len(good_reports) == 1, f"expected one frame, got {good_reports}"
    assert good_reports[0].data == payload
    assert decoder.check_frame(good_reports[0]), (
        "a nominal reference-model frame must pass check_frame; if it does "
        "not, the bound itself is miscalibrated"
    )

    slow = Signal(1, name="model-1.025x")
    encode_slow_frame(payload, BAUD, slow, t0=period_ns, scale=NEGATIVE_CONTROL_SCALE)
    slow_reports = decoder.decode(slow)
    assert len(slow_reports) == 1, f"expected one frame, got {slow_reports}"
    assert slow_reports[0].data == payload, (
        "the negative control must still decode to the right byte -- its "
        "whole point is a failure only the timing measurement catches"
    )
    assert not decoder.check_frame(slow_reports[0]), (
        "NEGATIVE CONTROL FAILED TO FAIL: encode_slow_frame passed "
        f"check_frame at {slow_reports[0].drift_pct:.3f}% drift"
    )
    dut._log.info(
        f"negative control (model x{NEGATIVE_CONTROL_SCALE}): "
        f"{slow_reports[0]} -> check_frame False, as required "
        f"(bound {MAX_FRAME_DRIFT_PCT}% of the bit period)"
    )
