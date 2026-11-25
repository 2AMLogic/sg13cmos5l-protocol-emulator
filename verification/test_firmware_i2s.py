"""DUT-facing I2S firmware bench (issue #451, multi-protocol extra credit,
catalog #443).

The claim: the committed program `firmware/asm/i2s_tx.asm` (image
`firmware/build/i2s_tx.hex`), loaded over the real serial load-phase pins
onto the real top and run by the ISA core, is an I2S (Philips) controller:
BCLK on `uo_out[6]`, WS on `uo_out[5]`, SD on `uo_out[7]`, 16-bit stereo
samples in 32-BCLK slots, that the **independent** receiver model
(`verification/reference_models/i2s.py`, written from the I2S bus
specification alone) decodes into exactly the samples the test loaded into
program memory, with BCLK, WS and SD inside the specification's duty,
set-up and hold limits.

What is graded, and by whom
---------------------------
The bench captures the three pins on every clock edge into nanosecond
waveforms and gives them to `I2sReceiver`, which samples SD on BCLK's rising
edges, tracks WS, applies the one-BCLK delay and reassembles the words. The
bench then compares the decoded samples with the table it loaded. The model
never sees the table; the bench never tells the model what to expect.

**Cycles.** The bench also asserts, from the pins and the committed cycle
report, the figures the README tabulates: BCLK period 16 cycles (8 low, 8
high), WS and SD changing only on the cycle BCLK falls, 32-BCLK = 512-cycle
slots, 1,024-cycle frames. **Any kHz figure is arithmetic at the
unconfirmed target clock.** The simulation clock is `CLK_PERIOD_NS` = 20 ns,
target-spec row 4's **target** 50 MHz, which no flow of this program has
confirmed (the klt-flow STA leg has hold violations); every Hz here is
cycles x 20 ns, not a measurement.

Samples. The table is data in the last 64 words of program memory (one
`LDI R0, b` word per byte, four words per stereo frame, 16 frames). The
committed run loads the image unchanged and captures 18 frames so that the
table wraps once. The extremes and random runs load the same code words with
other tables.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Three mutant programs, assembled in memory from the committed source with
one defect each, run on the same DUT and must be rejected for the defect's
own reason:

1. **No one-BCLK delay**: WS changes together with the MSB instead of one
   BCLK before it (left-justified framing). Timing is legal throughout; the
   decoded samples are not the loaded ones.
2. **Short slot**: the left slot's pad is one period short (31 BCLK).
3. **Stretched period**: one BCLK period of the frame is 17 cycles.

A fourth control re-grades the DUT's own captured waveform with SD delayed
by 0.4 T, which the model must reject as a set-up violation: the
capture-and-decode path can fail.

Driven by `klt functional-verification`
(`verification/request-firmware-i2s.json`) at RTL.
"""

import random
import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock

from reference_models.i2s import I2sReceiver
from reference_models.waveform import Signal

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

SRC = REPO_ROOT / "firmware" / "asm" / "i2s_tx.asm"
HEX = REPO_ROOT / "firmware" / "build" / "i2s_tx.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "i2s_tx.cycles.txt"

#: Simulation clock: names row 4's target 50 MHz; not a measurement.
CLK_PERIOD_NS = 20
#: The three outputs, bits of the dedicated output port (DR 0010 `i2s`).
BCLK_PIN, BCLK_BIT = "uo_out", 6
WS_PIN, WS_BIT = "uo_out", 5
SD_PIN, SD_BIT = "uo_out", 7

#: What the program implements, in core cycles.
BCLK_PERIOD_CYCLES = 16
SLOT_BITS, DATA_BITS = 32, 16
SLOT_CYCLES = SLOT_BITS * BCLK_PERIOD_CYCLES  # 512
FRAME_CYCLES = 2 * SLOT_CYCLES                # 1,024
#: The table: the last 64 words, 16 stereo frames of 4 words.
TABLE_BASE, TABLE_FRAMES = 0xC0, 16
MAX_WORDS = 256
DATA_HI = 0x10  # high byte of `LDI R0, b`
#: Frames captured: past the table's 16, so the wrap is exercised.
CAPTURE_FRAMES = 18
CAPTURE_CYCLES = CAPTURE_FRAMES * FRAME_CYCLES
#: Seed for the random tables.
RANDOM_SEED = 0x1251
#: The capture-path control moves SD this fraction of T late.
SD_DELAY_T = 0.4

_ADDR_LINE = re.compile(r"^ADDR 0x([0-9A-F]{2}) WORD 0x([0-9A-F]{4}) (.*) cycles=(\d+)$")


# =======================================================================
# Static facts and tables (not read from the DUT)
# =======================================================================


def committed_words():
    return parse_hex_image(HEX)


def table_of(words):
    """The 16 (left, right) unsigned samples in `words`' table region."""
    t = words[TABLE_BASE:TABLE_BASE + 4 * TABLE_FRAMES]
    assert len(t) == 4 * TABLE_FRAMES
    for w in t:
        assert w >> 8 == DATA_HI, f"table word 0x{w:04X} is not `LDI R0, b`"
    b = [w & 0xFF for w in t]
    return [((b[4 * n] << 8) | b[4 * n + 1], (b[4 * n + 2] << 8) | b[4 * n + 3])
            for n in range(TABLE_FRAMES)]


def image_for(code_words, frames):
    assert len(frames) == TABLE_FRAMES
    table = []
    for left, right in frames:
        for s in (left, right):
            s &= 0xFFFF
            table += [(DATA_HI << 8) | (s >> 8), (DATA_HI << 8) | (s & 0xFF)]
    words = list(code_words[:TABLE_BASE]) + table
    assert len(words) == MAX_WORDS
    return words


def signed16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def expected_stream(frames, n_frames):
    """Signed samples in transmission order, the table repeated."""
    out = []
    for i in range(n_frames):
        left, right = frames[i % TABLE_FRAMES]
        out += [signed16(left), signed16(right)]
    return out


# =======================================================================
# Running a program and grading it
# =======================================================================


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


async def run_and_capture(dut, words, cycles):
    await load_program(dut, words)
    return await capture_pin_bits(
        dut,
        {"bclk": (BCLK_PIN, BCLK_BIT), "ws": (WS_PIN, WS_BIT), "sd": (SD_PIN, SD_BIT)},
        cycles,
    )


def decode(caps, **kw):
    return I2sReceiver(**kw).decode(
        caps["bclk"].signal, caps["ws"].signal, caps["sd"].signal, -1.0, 1e18)


def check_cycles(caps):
    """The same waveform in cycles, against the committed cycle report: BCLK
    toggles every 8 cycles; WS and SD change only on a BCLK falling cycle;
    WS changes every 512 cycles."""
    bc = caps["bclk"].transition_cycles
    bv = [v for _t, v in caps["bclk"].signal.transitions]
    gaps = [b - a for a, b in zip(bc, bc[1:])]
    assert set(gaps) == {BCLK_PERIOD_CYCLES // 2}, f"BCLK gaps {sorted(set(gaps))}"
    falls = {c for c, v in zip(bc, bv) if v == 0}
    for name in ("ws", "sd"):
        stray = [c for c in caps[name].transition_cycles if c not in falls]
        assert not stray, f"{name} changed off a BCLK falling edge at cycles {stray[:5]}"
    wgaps = {b - a for a, b in zip(caps["ws"].transition_cycles, caps["ws"].transition_cycles[1:])}
    assert wgaps == {SLOT_CYCLES}, f"WS gaps {sorted(wgaps)}"


async def grade(dut, words, frames, label, n_frames=CAPTURE_FRAMES):
    caps = await run_and_capture(dut, words, n_frames * FRAME_CYCLES)
    res = decode(caps)
    for v in res.violations[:10]:
        dut._log.error(f"[{label}] {v}")
    assert res.violations == [], f"[{label}] {len(res.violations)} violation(s)"
    check_cycles(caps)
    got = res.samples()
    # the first slot (left of frame 0) has no WS edge before it: the decoded
    # run starts at frame 0's right word and alternates R, L, R, ...
    want = expected_stream(frames, n_frames)[1:]
    chans = [c for c, _v in got]
    assert chans == (["R", "L"] * len(got))[:len(got)], f"[{label}] channels {chans[:6]}"
    assert len(got) >= 2 * n_frames - 3, f"[{label}] only {len(got)} words decoded"
    assert [v for _c, v in got] == want[:len(got)], f"[{label}] decoded samples differ from the table"
    dut._log.info(
        f"[{label}] {len(got)} words OK over {n_frames} frames; BCLK {res.period_ns:.1f} ns; "
        f"min set-up {res.setup_min_ns:.1f} ns, min hold {res.hold_min_ns:.1f} ns")
    return res, caps


def mutate(text, old, new, count=1):
    assert text.count(old) == count, f"mutation site {old!r} found {text.count(old)} times"
    return text.replace(old, new, 1)


async def run_mutant(dut, name, text, n_frames=5):
    start_clock(dut)
    program = asm.assemble_text(text, source_name=f"<mutant {name}>")
    caps = await run_and_capture(dut, program.words, n_frames * FRAME_CYCLES)
    res = decode(caps)
    dut._log.info(f"mutant {name}: {len(res.violations)} violation(s), kinds "
                  f"{sorted({v.kind for v in res.violations})}; first: "
                  f"{res.violations[0] if res.violations else None}")
    return res, caps, table_of(program.words)


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed image and report match the source, the program is
    lint-clean, every BCLK period block is 16 cycles, and the table is the
    last 64 words."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    assert program.warnings == [], program.warnings
    sections = parse_cycle_sections(CYCLES.read_text(encoding="utf-8"))
    for ch in "lr":
        for name in (f"i2s_a_{ch}", f"i2s_hi_{ch}_bit", f"i2s_lo_{ch}_bit", f"i2s_pad_{ch}_bit"):
            assert sections[name][2] == BCLK_PERIOD_CYCLES, (name, sections[name])
        for half in ("hi", "lo"):  # s0..s3 of the bit block + the tail
            assert 4 + sections[f"i2s_{half}_{ch}_tail"][2] == BCLK_PERIOD_CYCLES
        assert 6 + sections[f"i2s_pad_{ch}_last"][2] == BCLK_PERIOD_CYCLES
    words = committed_words()
    assert len(words) == MAX_WORDS
    code_end = max(i for i, w in enumerate(words[:TABLE_BASE]) if w != 0) + 1
    dut._log.info(f"{len(words)} words: {code_end} code (the rest of 0..0xBF is NOP filler) + "
                  f"{4 * TABLE_FRAMES} table")


@cocotb.test()
async def test_committed_stream(dut):
    """The committed image, unchanged: 18 frames (the 16-frame table wraps
    once), decoded by the independent model and compared with the table."""
    start_clock(dut)
    words = committed_words()
    frames = table_of(words)
    res, caps = await grade(dut, words, frames, "committed")
    # the pins before the first frame: all three low (a defined start)
    assert [c.signal.initial for c in caps.values()] == [0, 0, 0]
    assert caps["ws"].signal.transitions[0][1] == 1, "the first WS edge is the rise into the right slot"
    # full-scale extremes are in the committed table
    flat = [s for f in frames for s in f]
    assert 0x7FFF in flat and 0x8000 in flat


@cocotb.test()
async def test_extremes_and_random_tables(dut):
    """Other tables on the committed code words: the sign/MSB extremes in
    both channels, then seeded random tables."""
    start_clock(dut)
    code = committed_words()
    extremes = [(0x7FFF, 0x8000), (0x8000, 0x7FFF), (0xFFFF, 0x0000), (0x0001, 0xFFFE),
                (0x8000, 0x8000), (0x7FFF, 0x7FFF), (0x5555, 0xAAAA), (0xAAAA, 0x5555),
                (0x0000, 0xFFFF), (0x00FF, 0xFF00), (0x0100, 0x00FF), (0xFFFF, 0xFFFF),
                (0x0000, 0x0000), (0x8001, 0x7FFE), (0x4000, 0xC000), (0x1234, 0xEDCC)]
    await grade(dut, image_for(code, extremes), extremes, "extremes")
    rng = random.Random(RANDOM_SEED)
    for k in range(2):
        frames = [(rng.randrange(0x10000), rng.randrange(0x10000)) for _ in range(TABLE_FRAMES)]
        await grade(dut, image_for(code, frames), frames, f"random {k}")


@cocotb.test()
async def test_negative_no_one_bclk_delay(dut):
    """WS moved one BCLK late (the MSB goes out with the WS edge). Legal
    timing, wrong framing: the decoded samples are not the loaded ones."""
    text = SRC.read_text(encoding="utf-8")
    text = mutate(text, "LDI   R1, 0x20          ; s10  the next a_ image: WS flips, SD 0",
                  "LDI   R1, 0x00          ; s10  MUTANT: WS flips one BCLK late")
    text = mutate(text, "LDI   R1, 0x00          ; s10  the next a_ image: WS flips, SD 0",
                  "LDI   R1, 0x20          ; s10  MUTANT: WS flips one BCLK late")
    res, caps, frames = await run_mutant(dut, "no-delay", text)
    got = [v for _c, v in res.samples()]
    want = expected_stream(frames, 5)[1:]
    assert got != want[:len(got)], "NEGATIVE CONTROL FAILED TO FAIL: the no-delay mutant decoded as loaded"
    assert not {"period", "duty", "setup", "hold"} & {v.kind for v in res.violations}, \
        "the no-delay mutant must be legal in timing and wrong in framing only"


@cocotb.test()
async def test_negative_short_slot(dut):
    text = SRC.read_text(encoding="utf-8")
    text = mutate(text, "LDI   R3, 15            ; s10  15 pad periods",
                  "LDI   R3, 14            ; s10  MUTANT", count=2)
    res, _caps, _frames = await run_mutant(dut, "short-slot", text)
    kinds = {v.kind for v in res.violations}
    assert "slot-length" in kinds, kinds


@cocotb.test()
async def test_negative_stretched_period(dut):
    text = SRC.read_text(encoding="utf-8")
    text = mutate(text, "WAIT  4                 ; s3   5 cycles",
                  "WAIT  5                 ; s3   MUTANT 6 cycles", count=2)
    res, _caps, _frames = await run_mutant(dut, "stretched-period", text)
    kinds = {v.kind for v in res.violations}
    assert "period" in kinds, kinds


@cocotb.test()
async def test_capture_path_control(dut):
    """The DUT's own captured waveform with SD delayed 0.4 T: the model must
    reject it as a set-up violation (and the unmodified capture is clean)."""
    start_clock(dut)
    words = committed_words()
    caps = await run_and_capture(dut, words, 4 * FRAME_CYCLES)
    assert decode(caps).violations == []
    T = BCLK_PERIOD_CYCLES * CLK_PERIOD_NS
    late = Signal(caps["sd"].signal.initial, name="sd-late")
    late.transitions = [(t + SD_DELAY_T * T, v) for t, v in caps["sd"].signal.transitions]
    bad = I2sReceiver().decode(caps["bclk"].signal, caps["ws"].signal, late, -1.0, 1e18)
    assert any(v.kind == "setup" for v in bad.violations), \
        "NEGATIVE CONTROL FAILED TO FAIL: SD delayed 0.4 T still passed the model"
    dut._log.info(f"capture-path control: {len(bad.violations)} violation(s), as required")
