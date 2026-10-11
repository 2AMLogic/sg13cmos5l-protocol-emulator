"""DUT-facing WS2812 firmware bench (target-spec row 13, issue #141 part 2;
the protocol choice is DR 0018, made after DR 0017's ISA freeze).

The claim: the committed program `firmware/asm/ws2812.asm` (image
`firmware/build/ws2812.hex`), loaded over the real serial load-phase pins
onto the real top and run by the ISA core, drives a WS2812 data line on
DIN = `uo_out[7]` that the **independent** WS2812B receiver model
(`verification/reference_models/ws2812.py`, written from the datasheet
alone) decodes into exactly the frame the test loaded, with every high and
low pulse inside the datasheet's window and a reset of at least 50 us
between frames.

What is graded, and by whom
---------------------------
The bench captures DIN on every clock edge into a nanosecond waveform and
gives it to `Ws2812Decoder`. The decoder measures every pulse, classifies
every bit, checks every window, splits frames at resets, and reconstructs
the GRB pixels. The bench then compares those pixels with the table it
loaded. The bench does not tell the model what the waveform should look
like. The only bench-side inputs are the pixels and the time base.

Time base. The simulation clock is 20 ns, target-spec row 4's **target**
50 MHz, which is not confirmed on this program's flows. So every ns figure
here is core cycles x 20 ns. The bench also asserts the pulse widths in
cycles, derived from the committed cycle report, so that a change in the
firmware fails here and is not silently re-graded.

Frames. The table after the code is data (one `LDI R0, b` word per byte,
then a `HALT` end marker; see the program header). `test_committed_frame`
loads the committed image unchanged. `test_random_frames` loads the same
code words with seeded random tables of 1 to 73 pixels (73 fills program
memory to the last word). Each run captures two whole frames and the reset
after the second.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Three mutant programs, each assembled in memory from the committed source
with one defect, run on the same DUT and must be rejected by the model for
the defect's own reason:

1. **short T1H**: the `1` code's high is 32 cycles (640 ns, below the
   650 ns floor). The bit period is re-padded to 56 cycles so that T0H,
   T0L and T1L all stay legal and only T1H is wrong.
2. **dropped bit**: the first byte of every frame is sent with 7 bits.
   Timing is legal throughout. The frame is 191 bits, not a whole number
   of pixels, and its pixels do not match the table.
3. **short reset**: the latch loop runs once, so the low between frames is
   about 5.5 us. That is longer than any bit's low and shorter than RES.

A fourth control re-grades the DUT's own captured golden waveform with time
stretched by 1.2x. T1H becomes 960 ns, outside its window, so the model must
reject it. That shows the capture-and-decode path can fail.

Driven by `klt functional-verification` (`verification/request-firmware-
ws2812.json`) at RTL, and by `flow/run-ws2812-gate-level.sh` on the LibreLane
netlist (zero-delay). All of it is pin-observable, so the same file runs
unchanged on gates.
"""

import random
import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock

from reference_models.ws2812 import (
    PERIOD_WINDOW,
    RES_MIN_NS,
    T0H_WINDOW,
    T0L_WINDOW,
    T1H_WINDOW,
    T1L_WINDOW,
    Ws2812Decoder,
)

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

from firmware_artifacts import parse_cycle_sections, parse_hex_image  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

# The load-phase driver and the per-edge pin capture are the ones the UART
# bench already uses; importing functions does not register their tests.
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart import capture_pin_bits  # noqa: E402

SRC = REPO_ROOT / "firmware" / "asm" / "ws2812.asm"
HEX = REPO_ROOT / "firmware" / "build" / "ws2812.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "ws2812.cycles.txt"

#: Simulation clock: names row 4's target 50 MHz; not a measurement.
CLK_PERIOD_NS = 20
#: DIN: bit 7 of the dedicated output port.
DIN_PIN, DIN_BIT = "uo_out", 7
#: Table entry encodings (see the program header).
DATA_HI, END_WORD = 0x10, 0xF000
MAX_WORDS = 256
#: Seed for the random tables, and the table sizes it draws.
RANDOM_SEED = 0x2812
RANDOM_SIZES = (1, 2, 5, 17, 73)
#: Stretch factor of the capture-path negative control.
STRETCH = 1.2

_ADDR_LINE = re.compile(r"^ADDR 0x([0-9A-F]{2}) WORD 0x([0-9A-F]{4}) (.*) cycles=(\d+)$")


# =======================================================================
# Static facts read from the committed artifacts (not from the DUT)
# =======================================================================


def report_rows(text):
    rows = []
    for line in text.splitlines():
        m = _ADDR_LINE.match(line)
        if m:
            rows.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3), int(m.group(4))))
    return rows


class Layout:
    """Where the code ends and the table starts, and the cycle offsets of
    the three OUTs of a bit, from a cycle report and an image."""

    def __init__(self, report_text, words):
        rows = report_rows(report_text)
        sections = parse_cycle_sections(report_text)
        b0, b1, self.bit_cycles, _ = sections["ws2812_bit"]
        t0, t1, self.tail_cycles, _ = sections["ws2812_byte_tail"]
        offset, outs, bz_offset = 0, [], None
        for addr, _w, text, cyc in rows[b0:b1 + 1]:
            if text.startswith("OUT UO_OUT"):
                outs.append(offset)
            if text.startswith("BZ"):
                bz_offset = offset + cyc
            offset += cyc
        assert len(outs) == 3 and bz_offset is not None, "unexpected bit-loop shape"
        self.t0h = outs[1] - outs[0]
        self.t1h = outs[2] - outs[0]
        self.byte_bit_cycles = bz_offset + self.tail_cycles
        # the table: the LDI before `WCTL PM_ADDR` names its address
        wctl = next(i for i, r in enumerate(rows) if r[2].startswith("WCTL PM_ADDR"))
        ldi = rows[wctl - 1]
        assert ldi[2].startswith("LDI R1,"), "PM_ADDR is not set from an LDI"
        self.table = ldi[1] & 0xFF
        self.code = words[: self.table]
        # the latch loop count: the second instruction of `latch` (LDI R1, n)
        self.latch_count = rows[4][1] & 0xFF
        assert rows[4][2].startswith("LDI R1,") and rows[6][2].startswith("SUB R1, R3")

    def frame_from_words(self, words):
        """The pixels a table in `words` holds (the frame a test loaded)."""
        data = []
        for w in words[self.table:]:
            if w == END_WORD:
                break
            assert w >> 8 == DATA_HI, f"table word 0x{w:04X} is not `LDI R0, b`"
            data.append(w & 0xFF)
        assert len(data) % 3 == 0
        return [tuple(data[i:i + 3]) for i in range(0, len(data), 3)]

    def image_for(self, pixels):
        table = [(DATA_HI << 8) | b for px in pixels for b in px] + [END_WORD]
        words = self.code + table
        assert len(words) <= MAX_WORDS, f"{len(pixels)} pixels do not fit"
        return words

    def max_pixels(self):
        return (MAX_WORDS - self.table - 1) // 3

    def capture_cycles(self, n_pixels):
        """Cycles to capture two whole frames and most of the reset after the
        second, stopping before the third frame starts (static arithmetic)."""
        latch = 2 + self.latch_count * 258 + 7
        first_rise = 3 + latch + 4
        pitch = (24 * n_pixels - 1) * self.bit_cycles + 50 + latch
        return first_rise + 2 * pitch - 200


def committed():
    words = parse_hex_image(HEX)
    return Layout(CYCLES.read_text(encoding="utf-8"), words), words


# =======================================================================
# Running a program and grading it
# =======================================================================


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


async def run_and_capture(dut, words, cycles):
    """Load `words`, run, and capture DIN on each of `cycles` edges. The
    caller's test has started the clock (once per test)."""
    await load_program(dut, words)
    caps = await capture_pin_bits(dut, {"din": (DIN_PIN, DIN_BIT)}, cycles)
    return caps["din"]


def window_of(din, cycles):
    """(t_start, t_end) in ns of a capture of `cycles` edges. Capture cycle
    0 is the MODE-drop edge; a transition at cycle c is stamped c edges
    later, so the first transition fixes the start time."""
    if din.signal.transitions:
        t_first, c_first = din.signal.transitions[0][0], din.transition_cycles[0]
        t0 = t_first - c_first * CLK_PERIOD_NS
    else:
        t0 = 0.0
    return t0, t0 + cycles * CLK_PERIOD_NS


def high_low_cycles(din):
    """(high widths, low widths) between consecutive transitions, in cycles,
    excluding the leading low."""
    c = din.transition_cycles
    vals = [v for (_t, v) in din.signal.transitions]
    highs, lows = [], []
    for i in range(len(c) - 1):
        (highs if vals[i] == 1 else lows).append(c[i + 1] - c[i])
    return highs, lows


async def grade(dut, layout, words, pixels, label):
    cycles = layout.capture_cycles(len(pixels))
    din = await run_and_capture(dut, words, cycles)
    t0, t1 = window_of(din, cycles)
    result = Ws2812Decoder().decode(din.signal, t0, t1)
    for v in result.violations[:10]:
        dut._log.error(f"[{label}] {v}")
    assert result.violations == [], f"[{label}] {len(result.violations)} timing violation(s)"
    latched = result.latched_frames
    assert len(latched) == 2, f"[{label}] {len(latched)} latched frame(s), expected 2"
    for k, f in enumerate(latched):
        got = f.pixels()
        assert got == pixels, f"[{label}] frame {k}: decoded {got[:4]}..., loaded {pixels[:4]}..."
    # the same pulses in cycles, against the committed cycle report
    highs, lows = high_low_cycles(din)
    assert set(highs) <= {layout.t0h, layout.t1h}, f"[{label}] high widths {sorted(set(highs))}"
    bit_lows = {x for x in lows if x * CLK_PERIOD_NS < RES_MIN_NS}
    want_lows = {layout.bit_cycles - layout.t0h, layout.bit_cycles - layout.t1h}
    assert bit_lows <= want_lows, f"[{label}] bit lows {sorted(bit_lows)}, want {sorted(want_lows)}"
    assert layout.byte_bit_cycles == layout.bit_cycles
    w = result.pulse_widths
    summary = {k: (round(min(v), 3), round(max(v), 3), len(v)) for k, v in w.items() if v}
    dut._log.info(
        f"[{label}] {len(pixels)} px x 2 frames OK; ns (min, max, count): {summary}; "
        f"leading low {result.leading_low_ns:.0f} ns"
    )
    return result


def margins(result):
    """Smallest distance (ns) from any measured pulse to its window edge."""
    pairs = (("T0H", T0H_WINDOW), ("T1H", T1H_WINDOW), ("T0L", T0L_WINDOW),
             ("T1L", T1L_WINDOW), ("bit", PERIOD_WINDOW))
    out = {}
    for key, (lo, hi) in pairs:
        vals = result.pulse_widths[key]
        if vals:
            out[key] = round(min(min(v - lo, hi - v) for v in vals), 3)
    return out


def mutate(text, old, new):
    assert text.count(old) == 1, f"mutation site {old!r} found {text.count(old)} times"
    return text.replace(old, new)


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed image and report match the source, both paths through a
    bit take the same number of cycles, and the only lint warnings are the
    two end-of-table branches.

    Those warnings are expected: the assembler taints every `RCTL PM_DATA_*`
    read, because program memory can hold pin data. Here the read is the
    table's end marker, and the branch picks "next byte" or "reset", both
    padded to the same length. It is not a loop whose length comes from data.
    """
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    lines = {int(m.group(1)) for m in (re.match(r"line (\d+): BNZ", w) for w in program.warnings) if m}
    src_lines = SRC.read_text(encoding="utf-8").splitlines()
    assert len(program.warnings) == 2 and len(lines) == 2, program.warnings
    for n in lines:
        assert "end" in src_lines[n - 1].lower() or "empty" in src_lines[n - 1].lower(), src_lines[n - 1]
    layout, words = committed()
    assert layout.bit_cycles == layout.byte_bit_cycles, (
        f"bit loop {layout.bit_cycles} cycles, byte-boundary bit {layout.byte_bit_cycles}")
    assert len(words) <= MAX_WORDS
    dut._log.info(
        f"{len(words)} words ({layout.table} code + {len(words) - layout.table} table), "
        f"bit {layout.bit_cycles} cycles, T0H {layout.t0h}, T1H {layout.t1h}, "
        f"latch loop x{layout.latch_count}, up to {layout.max_pixels()} pixels"
    )


@cocotb.test()
async def test_committed_frame(dut):
    """The committed image, unchanged: two frames of its 8-pixel table,
    graded by the independent model; then the capture-path control."""
    start_clock(dut)
    layout, words = committed()
    pixels = layout.frame_from_words(words)
    assert len(pixels) == 8
    cycles = layout.capture_cycles(len(pixels))
    din = await run_and_capture(dut, words, cycles)
    t0, t1 = window_of(din, cycles)
    result = Ws2812Decoder().decode(din.signal, t0, t1)
    assert result.violations == [], [str(v) for v in result.violations[:5]]
    assert [f.pixels() for f in result.latched_frames] == [pixels, pixels]
    dut._log.info(f"committed frame: margins to the window edges (ns) {margins(result)}; "
                  f"resets {[round(x) for x in result.pulse_widths['reset']]} ns")

    stretched = din.time_scaled(STRETCH)
    bad = Ws2812Decoder().decode(stretched, t0 * STRETCH, t1 * STRETCH)
    assert any(v.kind == "high" for v in bad.violations), (
        "NEGATIVE CONTROL FAILED TO FAIL: the captured waveform stretched "
        f"x{STRETCH} still passed the model")
    dut._log.info(f"capture-path control x{STRETCH}: {len(bad.violations)} violation(s), as required")


@cocotb.test()
async def test_random_frames(dut):
    """Seeded random tables, from 1 pixel to the 73 that fill program memory,
    on the committed code words."""
    start_clock(dut)
    layout, _ = committed()
    assert RANDOM_SIZES[-1] == layout.max_pixels()
    rng = random.Random(RANDOM_SEED)
    for n in RANDOM_SIZES:
        pixels = [tuple(rng.randrange(256) for _ in range(3)) for _ in range(n)]
        words = layout.image_for(pixels)
        assert words[: layout.table] == layout.code
        await grade(dut, layout, words, pixels, f"random {n} px")


async def run_mutant(dut, name, text):
    start_clock(dut)
    program = asm.assemble_text(text, source_name=f"<mutant {name}>")
    words = program.words
    layout = Layout(asm.render_cycles_report(program), words)
    pixels = layout.frame_from_words(words)
    cycles = min(layout.capture_cycles(len(pixels)), committed()[0].capture_cycles(len(pixels)))
    din = await run_and_capture(dut, words, cycles)
    t0, t1 = window_of(din, cycles)
    result = Ws2812Decoder().decode(din.signal, t0, t1)
    dut._log.info(f"mutant {name}: {len(result.violations)} violation(s), kinds "
                  f"{sorted({v.kind for v in result.violations})}; first: "
                  f"{result.violations[0] if result.violations else None}")
    return result, pixels


@cocotb.test()
async def test_negative_short_t1h(dut):
    text = SRC.read_text(encoding="utf-8")
    text = mutate(text, "WAIT  17               ; s22", "WAIT  9                ; s22")
    text = mutate(text, "WAIT  17               ; s44", "WAIT  18               ; s44")
    text = mutate(text, "WAIT  11               ; s50", "WAIT  12               ; s50")
    result, _ = await run_mutant(dut, "short-T1H", text)
    kinds = {v.kind for v in result.violations}
    assert kinds == {"high"}, f"short T1H must fail on the high width only, got {kinds}"
    assert all("640" in v.detail for v in result.violations)


@cocotb.test()
async def test_negative_dropped_bit(dut):
    text = SRC.read_text(encoding="utf-8")
    text = mutate(text, "LDI   R3, 1            ; bit counter", "LDI   R3, 2            ; bit counter")
    text = mutate(text, "LDI   R1, 60 ", "LDI   R1, 120")
    result, pixels = await run_mutant(dut, "dropped-bit", text)
    kinds = {v.kind for v in result.violations}
    assert kinds == {"partial-pixel"}, f"a dropped bit must fail as a partial pixel only, got {kinds}"
    assert all(len(f.bits) == 24 * len(pixels) - 1 for f in result.latched_frames)


@cocotb.test()
async def test_negative_short_reset(dut):
    text = SRC.read_text(encoding="utf-8")
    text = mutate(text, "LDI   R1, 60 ", "LDI   R1, 1  ")
    result, pixels = await run_mutant(dut, "short-reset", text)
    kinds = {v.kind for v in result.violations}
    assert "low" in kinds and "leading-reset" in kinds, kinds
    assert all(f.pixels() != pixels for f in result.latched_frames if len(f.bits) % 24 == 0)
    assert not any(v.kind == "high" for v in result.violations), "only the resets are wrong"
