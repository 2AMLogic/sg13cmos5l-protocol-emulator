"""DUT-facing NEC infrared firmware bench (issue #448, multi-protocol
extra credit, catalog #443).

The claim: the committed program `firmware/asm/nec_ir.asm` (image
`firmware/build/nec_ir.hex`, 160 words of the 256-word store), loaded over
the real serial load-phase pins onto the real top
(`tt_um_2amlogic_protocol_emulator`) and executed by the ISA core, drives
NEC infrared remote frames on IR_TX = `uo_out[7]`: a 38 kHz-class carrier
(1,316 cycles per period, 439 high) gated into a 9-ms-class leader mark,
32 pulse-distance bits and a final mark -- that the **independent** NEC
receiver model (`verification/reference_models/nec_ir.py`, written from
the protocol description alone, demodulator included) decodes into exactly
the address and command the loaded table holds, with every mark, space and
carrier period inside the model's windows.

What is measured, and in what units
-----------------------------------
**Cycles.** The graded quantities are the cycle counts the program's
instruction stream fixes: every carrier period exactly 1,316 (439 high,
877 low -- the leader's two 171-period halves join at a seamless 1,316,
because the 8-bit burst counter forces halves and the junction completes
its low), leader mark exactly 449,195, leader space exactly 225,000, bit
and final marks exactly 28,075, spaces exactly 28,125 (0) and 84,375 (1),
inter-frame idle exactly 3,000,000. The bench measures each of these at
the pin as cycle distances between captured edges and asserts them
exactly -- a stronger claim than the model's +-10%/+-5% windows, which is
the point of the mutation control below.

**Any microsecond/kilohertz figure is arithmetic at an unconfirmed
clock.** 1,316 cycles x 20 ns is 26.32 us = 37,994 Hz only at
target-spec row 4's **target** 50 MHz, which is unconfirmed on this
program's own flow (STA against this core is blocked,
`verification/records/sta-corner-sweep/`), the same stance as
`test_firmware_dmx512.py`. The bench runs its simulation clock at
`CLK_PERIOD_NS = 20` ns purely to *name* that nominal, and the model's ns
windows are derived from the same arithmetic.

The frame table
---------------
The table after the code holds one word per bit, MSB first (address,
~address, command, ~command): `LDI R0, 0x80` (word 0x1080) is a 1,
`LDI R0, 0x00` (0x1000) is a 0, and a `HALT` word (0xF000) ends the
frame. The code reads the words with DR 0012's `PM_DATA_*` and never
executes them, so a host can load any 32-bit frame -- including a
malformed one -- by writing the table words, which is what the random
frame test and the firmware-mutation control do. Every well-formed frame
holds exactly sixteen 1s (a byte and its complement), so the frame length
is data-independent: 3,400,670 cycles plus the idle.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
1. **Mutated WAIT** (the issue's control): every carrier-high `WAIT 181`
   in the source changed to `WAIT 175`, assembled in memory from the
   committed source and run on the same DUT. The carrier period becomes
   1,310 cycles and every mark shortens with it -- all still comfortably
   inside the model's windows (a 0.5% carrier shift, a 1% mark shift), so
   the MODEL still passes and only this bench's exact-cycle assertion
   catches the drift. The control proves the cycle-domain guard is the
   load-bearing check, not the tolerance windows.
2. **Stretched capture**: the DUT's own captured waveform time-stretched
   by 1.15x. Every mark and space lands 15% off nominal, past the model's
   +-10%, while staying self-consistent -- the timing-only failure mode,
   and proof that the capture-and-decode path can fail.

Driven by `klt functional-verification`
(`verification/request-firmware-nec-ir.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the `rtl/` modules it
instantiates and the vendored PDK macro model (`rtl/vendor/`). Like its
siblings, this file is *input* to `klt functional-verification`, not a
pytest module.

Everything on the pin side is deterministic: one committed program, one
seeded random frame, no other randomization, so every run is
byte-reproducible.
"""

import random
import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock

from reference_models.nec_ir import NecIrDecoder
from reference_models.waveform import Signal

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

from firmware_artifacts import parse_hex_image  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

# The serial load-phase driver and the per-edge pin capture are the ones the
# UART bench already uses; importing functions does not register their tests.
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart import capture_pin_bits  # noqa: E402

SRC = REPO_ROOT / "firmware" / "asm" / "nec_ir.asm"
HEX = REPO_ROOT / "firmware" / "build" / "nec_ir.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "nec_ir.cycles.txt"

#: Simulation clock: names row 4's target 50 MHz; not a measurement.
CLK_PERIOD_NS = 20
#: IR_TX: bit 7 of the dedicated output port (DR 0010's nec_ir_tx role).
TX_PIN, TX_BIT = "uo_out", 7

# --- the program's static timing, in core cycles (the graded claims) ----
#: One carrier period, rise to rise -- every period, junction included.
CARRIER_CYCLES = 1316
CARRIER_HIGH_CYCLES = 439
CARRIER_LOW_CYCLES = 877
#: The envelope a demodulator recovers: leader, spaces, marks, idle.
LEADER_MARK_CYCLES = 449_195      # 342 periods in two seamless halves
LEADER_SPACE_CYCLES = 225_000
BIT_MARK_CYCLES = 28_075          # 22 periods
SPACE0_CYCLES = 28_125
SPACE1_CYCLES = 84_375
IDLE_CYCLES = 3_000_000
#: A low this many cycles (no further rise) ends a mark: 0.9 periods.
GAP_CYCLES = 1185
#: Table encodings (see the program header).
DATA_HI, END_WORD = 0x10, 0xF000
MAX_WORDS = 256
#: Capture slack past the final mark, so the model sees the frame's
#: trailing silence and latches it (the floor is 202,500 cycles).
TRAILER_CYCLES = 250_000
#: Capture slack before the first rise (setup is a handful of cycles).
HEAD_SLACK_CYCLES = 64
#: Seed of the random-frame test ("NEC1").
RANDOM_SEED = 0x4E45_4331
#: Stretch factor of the capture-path negative control: past the model's
#: +-10% windows while every mark stays self-consistent.
STRETCH = 1.15

_ADDR_LINE = re.compile(r"^ADDR 0x([0-9A-F]{2}) WORD 0x([0-9A-F]{4}) (.*) cycles=(\d+)$")


def report_rows(text):
    rows = []
    for line in text.splitlines():
        m = _ADDR_LINE.match(line)
        if m:
            rows.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3), int(m.group(4))))
    return rows


def _byte_bits(value):
    return [(value >> i) & 1 for i in range(7, -1, -1)]


class Layout:
    """Where the code ends and the bit table starts, from a cycle report
    and an image, plus the frame arithmetic of a given table."""

    def __init__(self, report_text, words):
        rows = report_rows(report_text)
        wctl = next(i for i, r in enumerate(rows) if r[2].startswith("WCTL PM_ADDR"))
        ldi = rows[wctl - 1]
        assert ldi[2].startswith("LDI R0,"), "PM_ADDR is not set from an LDI R0"
        self.table = ldi[1] & 0xFF
        assert words[self.table] >> 8 == DATA_HI, "the table does not start where the LDI says"
        self.code = words[: self.table]
        bits, end = [], self.table
        while end < len(words) and words[end] != END_WORD:
            assert words[end] >> 8 == DATA_HI, f"word {end} is not a bit word"
            bits.append(1 if words[end] & 0x80 else 0)
            end += 1
        assert words[end] == END_WORD and len(bits) == 32, "the table is not 32 bits + marker"
        self.bits = bits
        self.addr = int("".join(map(str, bits[0:8])), 2)
        self.cmd = int("".join(map(str, bits[16:24])), 2)

    def image_for(self, addr, cmd, *, inv_addr=None, inv_cmd=None):
        """The image with a different frame's 32 bit words (code equal)."""
        ia = 0xFF - addr if inv_addr is None else inv_addr
        ic = 0xFF - cmd if inv_cmd is None else inv_cmd
        bits = (_byte_bits(addr) + _byte_bits(ia) + _byte_bits(cmd) + _byte_bits(ic))
        table = [0x1000 | (b << 7) for b in bits] + [END_WORD]
        words = self.code + table
        assert len(words) <= MAX_WORDS, "frame does not fit program memory"
        return words

    def frame_cycles(self):
        """Leader + 32 bits + final mark (the idle follows)."""
        ones = sum(self.bits)
        zeros = 32 - ones
        return (LEADER_MARK_CYCLES + LEADER_SPACE_CYCLES
                + zeros * (BIT_MARK_CYCLES + SPACE0_CYCLES)
                + ones * (BIT_MARK_CYCLES + SPACE1_CYCLES)
                + BIT_MARK_CYCLES)


def committed():
    words = parse_hex_image(HEX)
    return Layout(CYCLES.read_text(encoding="utf-8"), words), words


# =======================================================================
# Running a program and measuring it, in cycles and through the model
# =======================================================================


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


async def run_and_capture(dut, words, cycles):
    await load_program(dut, words)
    caps = await capture_pin_bits(dut, {"ir": (TX_PIN, TX_BIT)}, cycles)
    return caps["ir"]


def window_of(ir, cycles):
    """(t_start, t_end) in ns of a capture of `cycles` edges, anchored so
    cycle 0 of the capture is t_start (capture cycle 0 is the MODE-drop
    edge; a transition at cycle c is stamped c edges later)."""
    if ir.signal.transitions:
        t_first, c_first = ir.signal.transitions[0][0], ir.transition_cycles[0]
        t0 = t_first - c_first * CLK_PERIOD_NS
    else:
        t0 = 0.0
    return t0, t0 + cycles * CLK_PERIOD_NS


def demod_cycles(ir):
    """(mark widths, space widths, carrier periods) of the captured pin,
    in cycles, with the model's demodulator rule: a low of `GAP_CYCLES` or
    more ends a mark; complete rise-to-rise periods inside a mark are
    carrier periods. Transitions alternate (the pin starts low)."""
    cyc = ir.transition_cycles
    vals = [v for (_t, v) in ir.signal.transitions]
    rises = [i for i, v in enumerate(vals) if v == 1]
    marks, spaces, periods = [], [], []
    i = 0
    while i < len(rises):
        ri = rises[i]
        last, j = ri, i
        while True:
            fall = last + 1  # transitions alternate: the fall follows
            nxt = rises[j + 1] if j + 1 < len(rises) else None
            if nxt is not None and cyc[nxt] - cyc[fall] < GAP_CYCLES:
                periods.append(cyc[nxt] - cyc[last])
                last, j = nxt, j + 1
                continue
            marks.append(cyc[fall] - cyc[ri])
            if nxt is not None:
                spaces.append(cyc[nxt] - cyc[fall])
            j += 1
            break
        i = j
    return marks, spaces, periods


async def grade(dut, layout, words, addr, cmd, label, expect_idle=False):
    """Run one frame, decode it with the independent model, and assert the
    cycle-domain constants. With `expect_idle`, the capture runs through
    the inter-frame idle and into the next frame's leader mark, so the
    idle itself is measured. Returns (Decode, CapturedPin)."""
    if expect_idle:
        # through the idle and the next frame's leader, ending 150,000
        # cycles into the leader SPACE (225,000 wide): never past it into
        # the next frame's bits, and never mid-mark
        cycles = HEAD_SLACK_CYCLES + layout.frame_cycles() + IDLE_CYCLES \
            + LEADER_MARK_CYCLES + 150_000
    else:
        cycles = HEAD_SLACK_CYCLES + layout.frame_cycles() + TRAILER_CYCLES
    ir = await run_and_capture(dut, words, cycles)
    t0, t1 = window_of(ir, cycles)
    result = NecIrDecoder().decode(ir.signal, t0, t1)
    for v in result.violations[:10]:
        dut._log.error(f"[{label}] {v}")
    assert result.violations == [], f"[{label}] {len(result.violations)} violation(s)"
    assert len(result.latched_frames) == 1, f"[{label}] expected one latched frame"
    frame = result.latched_frames[0]
    assert (frame.addr, frame.cmd) == (addr, cmd), (
        f"[{label}] decoded ({frame.addr:#04x}, {frame.cmd:#04x}), "
        f"loaded ({addr:#04x}, {cmd:#04x})")

    marks, spaces, periods = demod_cycles(ir)
    want_spaces = {LEADER_SPACE_CYCLES, SPACE0_CYCLES, SPACE1_CYCLES}
    if expect_idle:
        want_spaces.add(IDLE_CYCLES)
    assert set(marks) == {LEADER_MARK_CYCLES, BIT_MARK_CYCLES}, (
        f"[{label}] envelope marks {sorted(set(marks))}")
    assert marks.count(LEADER_MARK_CYCLES) == (2 if expect_idle else 1)
    assert set(spaces) == want_spaces, (
        f"[{label}] envelope spaces {sorted(set(spaces))}")
    assert spaces.count(LEADER_SPACE_CYCLES) == 1
    if expect_idle:
        assert spaces.count(IDLE_CYCLES) == 1
    assert set(periods) == {CARRIER_CYCLES}, (
        f"[{label}] carrier periods {sorted(set(periods))}")
    w = result.pulse_widths
    summary = {k: (round(min(v) / 1000, 2), round(max(v) / 1000, 2), len(v))
               for k, v in w.items() if v}
    dut._log.info(
        f"[{label}] frame ({addr:#04x}, {cmd:#04x}) latched; envelope us "
        f"(min, max, count): {summary}; carrier periods {len(periods)}, "
        f"junction included")
    return result, ir


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed build artifacts match the committed `.asm` source, the
    word count is inside the 256-word store, the four space-loop sections
    report their 258-cycle bodies, and the only lint warnings are the two
    documented table-branch ones (the marker test and the bit test: the
    pulse-distance encoding's own data dependence, padded level on both
    paths -- see the program header)."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    lines = {int(m.group(1)) for m in (re.match(r"line (\d+): B(NZ|Z)", w)
                                       for w in program.warnings) if m}
    src_lines = SRC.read_text(encoding="utf-8").splitlines()
    assert len(program.warnings) == 2 and len(lines) == 2, program.warnings
    for n in lines:
        joined = " ".join(s.lower() for s in src_lines[n - 2:n])
        assert "marker" in joined or "the bit is 0" in joined, src_lines[n - 1]
    layout, words = committed()
    assert len(words) <= MAX_WORDS
    assert (layout.addr, layout.cmd) == (0xA5, 0x3C)
    assert layout.frame_cycles() == 3_400_670, layout.frame_cycles()
    sections = {}
    for line in CYCLES.read_text(encoding="utf-8").splitlines():
        m = re.match(r"CYCLES name=(\S+) start=\d+ end=\d+ cycles=(\d+) branches=(\S+)$", line)
        if m:
            sections[m.group(1)] = (int(m.group(2)), m.group(3))
    assert set(sections) == {"nec_ir_leader_space", "nec_ir_bit1_space",
                             "nec_ir_bit0_space", "nec_ir_idle_space"}, sections
    for name, (cycles, branches) in sections.items():
        assert cycles == 258, f"section {name}: {cycles} cycles, expected 258"
        assert branches == "true", f"section {name} lost its branch"
    dut._log.info(
        f"committed program: {len(words)} words ({layout.table} code + "
        f"{len(words) - layout.table} table), carrier {CARRIER_CYCLES} cycles, "
        f"leader {LEADER_MARK_CYCLES}, frame {layout.frame_cycles()} cycles, "
        f"frame+idle {layout.frame_cycles() + IDLE_CYCLES} cycles"
    )


@cocotb.test()
async def test_committed_frame(dut):
    """The committed image, unchanged: one frame graded by the independent
    model and by the exact cycle constants; then the stretched capture
    control."""
    start_clock(dut)
    layout, words = committed()
    _result, ir = await grade(dut, layout, words, layout.addr, layout.cmd, "committed",
                              expect_idle=True)

    cycles = HEAD_SLACK_CYCLES + layout.frame_cycles() + TRAILER_CYCLES
    t0, t1 = window_of(ir, cycles)
    bad = NecIrDecoder().decode(ir.time_scaled(STRETCH), t0 * STRETCH, t1 * STRETCH)
    kinds = {v.kind for v in bad.violations}
    assert "mark" in kinds, (
        "NEGATIVE CONTROL FAILED TO FAIL: the captured waveform stretched "
        f"x{STRETCH} still passed the model (kinds {kinds})")
    dut._log.info(f"capture-path control x{STRETCH}: {len(bad.violations)} "
                  f"violation(s), kinds {sorted(kinds)} -- as required")


@cocotb.test()
async def test_random_frame(dut):
    """A seeded random (address, command) loaded into the same code words:
    the table is data, the code is not."""
    start_clock(dut)
    layout, _ = committed()
    rng = random.Random(RANDOM_SEED)
    addr, cmd = rng.randrange(256), rng.randrange(256)
    words = layout.image_for(addr, cmd)
    assert words[: layout.table] == layout.code
    await grade(dut, layout, words, addr, cmd, f"random {addr:#04x}/{cmd:#04x}")


@cocotb.test()
async def test_negative_mutated_wait(dut):
    """Every carrier-high `WAIT 181` changed to `WAIT 175` (the issue's
    mutation control): the carrier period and every mark drift by under
    one percent -- inside every model window, so the MODEL still passes --
    and only the exact-cycle assertion catches it. The bench asserts the
    drift is present (and documents the model's blindness to it)."""
    start_clock(dut)
    text = SRC.read_text(encoding="utf-8")
    n = text.count("WAIT  181")
    assert n == 5, f"expected 5 carrier-high WAITs, found {n}"
    text = text.replace("WAIT  181", "WAIT  175")
    program = asm.assemble_text(text, source_name="<mutant short-high>")
    layout = Layout(asm.render_cycles_report(program), program.words)
    cycles = HEAD_SLACK_CYCLES + LEADER_MARK_CYCLES + LEADER_SPACE_CYCLES + 4 * 57_000
    ir = await run_and_capture(dut, program.words, cycles)
    t0, t1 = window_of(ir, cycles)
    result = NecIrDecoder().decode(ir.signal, t0, t1)
    _marks, _spaces, periods = demod_cycles(ir)
    got = sorted(set(periods))
    assert got == [CARRIER_CYCLES - 6], (
        f"mutant carrier periods {got}; the exact-cycle guard must see the "
        f"6-cycle drift the tolerance windows do not")
    assert not [v for v in result.violations if v.kind in ("carrier", "mark", "space",
                                                           "leader-space")], (
        "the mutant is inside every model window (that is the point of "
        "this control); unexpected model violations: "
        f"{[str(v) for v in result.violations[:4]]}")
    dut._log.info(
        f"mutant short-high: carrier {got} (nominal {CARRIER_CYCLES}), "
        f"model violations {len(result.violations)} -- the cycle guard is the "
        f"check that fires")
