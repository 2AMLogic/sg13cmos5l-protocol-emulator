"""DUT-facing NEC infrared firmware RECEIVE bench (issue #488, follow-up
to the #448 transmitter).

The claim: the committed program `firmware/asm/nec_ir_rx.asm` (image
`firmware/build/nec_ir_rx.hex`, 115 words of the 256-word store), loaded
over the real serial load-phase pins onto the real top
(`tt_um_2amlogic_protocol_emulator`) and executed by the ISA core, decodes
NEC infrared frames **from the demodulating receiver module wired to
IR_RX = `ui_in[4]`** (DR 0010's `nec_ir_rx` role): for every well-formed
frame the bench drives, the firmware writes the frame's address byte to
`uo_out` (RESULT[7:0], the `nec_ir_rx_result` phase) and then its command
byte; a repeat code, a bad-complement frame and a truncated frame write
nothing and leave the previous result intact.

Where the stimulus comes from
-----------------------------
The **independent** model (`verification/reference_models/nec_ir.py`,
written from the protocol description alone) supplies the encoder side:
`encode_frame` / `encode_repeat` produce the *transmitter pin's* waveform
-- idle low, each mark a burst of 38 kHz carrier. A real receiving end is
a demodulating receiver module: its output (the envelope) is idle HIGH
and low for exactly each mark's width. The bench converts the model's
waveform to that envelope before it drives `ui_in[4]` (`envelope_of`,
the model's own stage-1 demodulation rule); `test_envelope_self_check`
pins the conversion against `NecIrDecoder` on a known frame, so the
bench never drives a chattering carrier onto the receiver pin and calls
it decoding.

What is graded, and in what units
---------------------------------
**Writes, against the driven bytes.** The bench captures `uo_out` after
every clock edge and reduces it to its change events. Per valid frame
the expected events are exactly (address, command), in that order -- the
DR 0010 `nec_ir_rx_result` publication order -- and nothing else; per
discard case the expected events are exactly none. The model's own
decoder also passes over each frame's carrier waveform (that frame's
time window only), so every frame the bench grades with was first proven
legal (latched, no violations).

**The sample point is graded through behaviour, not trusted arithmetic.**
The program samples each bit mid-space, 40,781 cycles (815.62 us) after
the mark ends -- inside the [30,937.5 .. 50,625]-cycle interval where
every frame whose `space0_ns` / `space1_ns` / `bit_mark_ns` sit anywhere
on the model's +-10% `TIMING_TOL_PCT` windows still decodes (the issue's
~1.1 ms figure is past the interval's 50,625-cycle ceiling and misreads
a 0 whose mark and space are both -10%, which is why the program samples
earlier). The +-10% edge frames below -- including the razor combination
space0 and bit_mark both -10%, and all three widths together at each
edge -- are the margin check; a frame with `space0_ns` at -15% is
*documented accepted* (one window beyond: mid-space sampling tolerates
wider-than-window skew; discrimination only breaks past ~1.47x stretch);
a x1.5-stretched frame is the rejection control.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
1. **Mutated sample point** (the issue's mutation-control analogue): the
   committed source re-assembled with the sample delay moved to 55,000
   cycles (1.1 ms, the issue's own figure). The razor frame (space0 and
   bit_mark both -10%) must then fail to come back correct -- its 0
   bits' next marks end 4,375 cycles before the mutant samples, so every
   0 reads 1 and the written bytes are not the driven ones.
2. **x1.5-stretched envelope**: every line edge stretched 1.5x. The
   0-space outruns the sample point; the frame must not come back
   correct.
3. **The discard cases are themselves controls**: each asserts the
   *absence* of a write, and the frame after each discard proves the
   decoder resynchronised (a truncated frame followed by a good frame
   must yield the good frame's bytes).

Everything is deterministic: one committed program, one seeded random
frame, no other randomization.

Microsecond figures are arithmetic at target-spec row 4's **unconfirmed**
50 MHz core clock (`CLK_PERIOD_NS = 20` names the nominal); the claim is
the cycle count.

Driven by `klt functional-verification`
(`verification/request-firmware-nec-ir-rx.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the `rtl/` modules it
instantiates and the vendored PDK macro model (`rtl/vendor/`). Like its
siblings, this file is *input* to `klt functional-verification`, not a
pytest module.
"""

import random
import re
import sys
from bisect import bisect_right
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import First, ReadOnly, Timer, ValueChange
from cocotb.utils import get_sim_time

from reference_models.nec_ir import (
    BIT_MARK_NS,
    DEMOD_GAP_NS,
    LEADER_MARK_NS,
    LEADER_SPACE_NS,
    NecIrDecoder,
    REPEAT_SPACE_NS,
    SPACE0_NS,
    SPACE1_NS,
    encode_frame,
    encode_repeat,
)
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

from test_protocol_emulator import load_program  # noqa: E402

SRC = REPO_ROOT / "firmware" / "asm" / "nec_ir_rx.asm"
HEX = REPO_ROOT / "firmware" / "build" / "nec_ir_rx.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "nec_ir_rx.cycles.txt"

#: Simulation clock: names row 4's target 50 MHz; not a measurement.
CLK_PERIOD_NS = 20
#: IR_RX: bit 4 of the dedicated input port (DR 0010's nec_ir_rx role).
RX_PIN, RX_BIT = "ui_in", 4
#: The spill region's word address in the committed image (the program's
#: own scratch, DR 0012 PM_DATA_*): code must end before it.
SCRATCH = 128
#: Words per frame spill (32 partial bytes + the 33rd sample's spill).
SPILL_WORDS = 33
#: Inter-event silence on the line: above the model's latch floor
#: (3,645 us) and the program's commit threshold (1,945.3 us).
GAP_NS = 6_000_000.0
#: Lead-in before the first event on the line (the program hunts from
#: the MODE drop; a short idle-high lead is enough).
LEAD_NS = 400_000.0
#: Seed of the random-frame test ("NECR", the receive counterpart of the
#: transmitter bench's "NEC1").
RANDOM_SEED = 0x4E45_4352
#: The committed sample point and its decision interval, in cycles.
SAMPLE_CYCLES = 40_781
DECISION_LO_CYCLES = 30_938
DECISION_HI_CYCLES = 50_625


# =======================================================================
# The receiver-module envelope (bench helper; the model stays frozen)
# =======================================================================


def envelope_of(carrier: Signal) -> Signal:
    """The demodulating receiver module's output for a transmitter-pin
    waveform: idle HIGH, LOW from each mark's first carrier rise to its
    last fall, HIGH elsewhere. This is stage 1 of the model's own
    demodulation rule (`DEMOD_GAP_NS` hold-off), applied to build the
    stimulus; the model itself is unchanged."""
    rises = [t for (t, v) in carrier.transitions if v == 1]
    falls = [t for (t, v) in carrier.transitions if v == 0]
    env = Signal(1, name=f"{carrier.name}:env")
    i = 0
    while i < len(rises):
        rise = rises[i]
        last, j = rise, i
        while True:
            idx = bisect_right(falls, last)
            fall = falls[idx] if idx < len(falls) else None
            nxt = rises[j + 1] if j + 1 < len(rises) else None
            if fall is None or nxt is None or nxt - fall >= DEMOD_GAP_NS:
                break
            last, j = nxt, j + 1
        env.add(rise, 0)
        if fall is not None:
            env.add(fall, 1)
        i = j + 1
    return env


def _frame_bits(addr, cmd, inv_addr=None, inv_cmd=None):
    bits = []
    for byte in (addr, 0xFF - addr if inv_addr is None else inv_addr,
                 cmd, 0xFF - cmd if inv_cmd is None else inv_cmd):
        bits.extend((byte >> i) & 1 for i in range(8))
    return bits


def model_ok(carrier: Signal, t_from: float, t_to: float, addr, cmd) -> None:
    """The independent model's verdict on one driven frame's carrier, in
    that frame's own time window: exactly one latched frame with the
    driven bytes and no violations (asserted BEFORE the DUT is asked to
    decode it)."""
    dec = NecIrDecoder().decode(carrier, t_from, t_to)
    for v in dec.violations[:5]:
        raise AssertionError(f"stimulus frame rejected by the model: {v}")
    assert len(dec.latched_frames) == 1, \
        f"stimulus frame did not latch ({len(dec.latched_frames)} latched)"
    f = dec.latched_frames[0]
    assert (f.addr, f.cmd) == (addr, cmd), \
        f"model decoded ({f.addr:#04x}, {f.cmd:#04x}), drove ({addr:#04x}, {cmd:#04x})"


# =======================================================================
# Stimulus assembly: one combined envelope for a whole test
# =======================================================================


class Stimulus:
    """A sequence of events on the line, each preceded by a silence gap
    (default `GAP_NS`), plus the uo_out writes expected once the firmware
    has decoded them (the boot clear is not a change: the bus is 0
    already)."""

    def __init__(self):
        self.carrier = Signal(0, name="carrier")
        self.t = 0.0
        self.expect = []       # (addr, cmd) per frame that must publish
        self.label = []        # human name per event, for diagnostics

    def frame(self, addr, cmd, name=None, gap=GAP_NS, check_model=True, **kw):
        t0 = self.t + gap
        t_end = encode_frame(self.carrier, addr, cmd, t0=t0, **kw)
        if check_model:
            model_ok(self.carrier, t0 - 1.0, t_end + GAP_NS, addr, cmd)
        self.t = t_end
        self.expect.append((addr, cmd))
        self.label.append(name or f"frame {addr:#04x}/{cmd:#04x}")
        return self

    def repeat(self, name=None, gap=GAP_NS, **kw):
        self.t = encode_repeat(self.carrier, t0=self.t + gap, **kw)
        self.label.append(name or "repeat")
        return self

    def broken(self, addr, cmd, name=None, gap=GAP_NS, **kw):
        """A frame the firmware must discard (bad complement via
        `inv_addr`/`inv_cmd`, or truncation via `stop_after_bits`):
        nothing is appended to `expect`."""
        self.t = encode_frame(self.carrier, addr, cmd, t0=self.t + gap, **kw)
        self.label.append(name or f"broken {addr:#04x}/{cmd:#04x}")
        return self

    def envelope(self, lead_ns=LEAD_NS):
        env = envelope_of(self.carrier)
        if lead_ns:
            shifted = Signal(1, name="line")
            shifted.transitions = [(t + lead_ns, v) for (t, v) in env.transitions]
            return shifted
        return env

    def cycles(self, lead_ns=LEAD_NS, tail_ns=GAP_NS):
        return int((self.t + lead_ns + tail_ns) / CLK_PERIOD_NS) + 1_000


def stretched(env: Signal, factor: float) -> Signal:
    out = Signal(env.initial, name=f"{env.name}*{factor}")
    out.transitions = [(t * factor, v) for (t, v) in env.transitions]
    return out


# =======================================================================
# Driving the line and capturing the result bus
# =======================================================================


def set_ir(dut, level):
    """Drive the IR_RX line (`ui_in[RX_BIT]`), leaving ui_in's other bits
    as the loader left them (PROG_MODE low, PROG_SER low)."""
    dut.ui_in.value = (int(dut.ui_in.value) & ~(1 << RX_BIT)) | ((level & 1) << RX_BIT)


async def drive_line(dut, env: Signal, base_ns: float):
    """Apply the envelope to `ui_in[RX_BIT]` at absolute sub-cycle times:
    `base_ns` + the envelope's own times (the same discipline the UART RX
    bench's driver uses)."""
    set_ir(dut, env.initial)
    for t, v in env.transitions:
        target_ps = round((base_ns + t) * 1000)
        now_ps = round(float(get_sim_time("ps")))
        assert target_ps > now_ps, "stimulus transition scheduled in the past"
        await Timer(target_ps - now_ps, unit="ps")
        set_ir(dut, v)


async def capture_writes(dut, base_ns: float, end_ns: float):
    """Collect `uo_out`'s value changes as (cycle, value) from `base_ns`
    until `end_ns` (absolute ns). The capture parks on the signal's own
    value-change trigger (the PS/2 bench's monitor pattern), so it costs
    nothing per idle clock edge -- the whole point here, where one test
    runs tens of millions of edges for a handful of result writes."""
    writes = []
    last = int(dut.uo_out.value)
    while True:
        remaining = end_ns - float(get_sim_time("ns"))
        if remaining <= 0:
            break
        await First(ValueChange(dut.uo_out), Timer(int(remaining), "ns"))
        await ReadOnly()
        t = float(get_sim_time("ns"))
        v = int(dut.uo_out.value)
        await Timer(1, unit="ns")  # leave the read-only region
        if t >= end_ns:
            break
        if v != last:
            writes.append((int(round((t - base_ns) / CLK_PERIOD_NS)), v))
            last = v
    return writes


def write_events(uo):
    """(Kept for the discard test's edge-count assertion.) The (edge,
    value) change events of a capture; `uo` here is the list returned by
    `capture_writes` -- an already-event list -- so this is the identity
    a caller can pass either form through. See `run_rx`: it returns the
    event list directly."""
    return uo if uo and isinstance(uo[0], tuple) else \
        [(i, v) for i, v in enumerate(uo) if i and v != uo[i - 1]]


async def run_rx(dut, env: Signal, cycles: int, words=None):
    """Load the committed image (or `words`), idle the line high, drive
    `env` from the MODE drop and capture `uo_out`'s writes for `cycles`
    edges. Returns the (cycle, value) write-event list."""
    if words is None:
        words = parse_hex_image(HEX)
    assert len(words) <= 256, f"image is {len(words)} words"
    await load_program(dut, words)
    set_ir(dut, 1)  # the receiver module idles high
    base_ns = float(get_sim_time("ns"))
    cocotb.start_soon(drive_line(dut, env, base_ns))
    return await capture_writes(dut, base_ns, base_ns + cycles * CLK_PERIOD_NS)


def check_writes(dut, events, stim, label):
    """The graded assertion: the result bus changes exactly as `expect`
    says -- the boot clear to 0 right after the MODE drop (uo_out still
    held the load phase's PM_CRC readout until the program's first OUT
    zeroes it), then (address, command) per valid frame, in that order,
    nothing between events."""
    got = [v for (_e, v) in events]
    want = [0x00] + [b for pair in stim.expect for b in pair]
    assert got == want, (
        f"[{label}] uo_out writes {[f'{v:02X}' for v in got]} != expected "
        f"{[f'{v:02X}' for v in want]} (events: {stim.label})")
    dut._log.info(
        f"[{label}] {len(stim.expect)} frame(s) published: "
        f"{[f'{a:02X}/{c:02X}' for a, c in stim.expect]}; "
        f"{len(stim.label) - len(stim.expect)} discard event(s)")


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_envelope_self_check(dut):
    """The envelope converter against the independent model, on a known
    frame: the model decodes the carrier into exactly (0xA5, 0x3C) with
    no violations, and the envelope's low intervals are exactly the
    model's demodulated marks (leader + 33 bit-class) while its high
    intervals are the leader space followed by the frame's bit spaces in
    wire order. This is what makes driving the envelope (not the
    carrier) legitimate as the receiver module's output."""
    car = Signal(0, name="selfcheck")
    t_end = encode_frame(car, 0xA5, 0x3C, lead_ns=1_000_000.0)
    model_ok(car, 0.0, t_end + GAP_NS, 0xA5, 0x3C)
    env = envelope_of(car)

    lows, highs = [], []
    prev_t, prev_v = 0.0, env.initial
    for (t, v) in env.transitions:
        (lows if prev_v == 0 else highs).append(t - prev_t)
        prev_t, prev_v = t, v
    dec = NecIrDecoder().decode(car, 0.0, t_end + GAP_NS)
    w = dec.pulse_widths
    assert abs(lows[0] - w["leader_mark"][0]) < 1.0, "leader mark width"
    assert sorted(lows[1:]) == sorted(w["bit_mark"]), "bit/final mark widths"
    assert len(lows) == 34, f"{len(lows)} envelope marks, expected 34"
    bits = _frame_bits(0xA5, 0x3C)
    assert abs(highs[1] - LEADER_SPACE_NS) < 1.0, "leader space width"
    # highs[2:] are the 32 bit spaces in wire order (the trailing silence
    # past the final mark never ends at a transition, so it is not in the
    # list; the model's own latch check covers it via model_ok above).
    got = highs[2:]
    want = [SPACE1_NS if b else SPACE0_NS for b in bits]
    assert len(got) == 32 and all(abs(g - e) < 1.0 for g, e in zip(got, want)), \
        "bit spaces in wire order"
    dut._log.info(
        f"envelope == model demodulation: leader {lows[0] / 1e3:.2f} us, "
        f"34 marks, spaces match the wire order of 0xA5/0x3C")


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed build artifacts match the committed `.asm` source;
    the image fits the 256-word store AND leaves the spill region (word
    128 up) free of code; the four delay sections report their exact
    bodies; and the assembler's fifteen data-dependent-branch warnings
    are exactly the documented handshake/data sites (see the program
    header: eleven polls, the sample branch, the word-count check and
    the two complement checks -- never between a mark end and its
    sample)."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    words = parse_hex_image(HEX)
    assert len(words) == 115, f"word count drifted: {len(words)}"
    assert len(words) <= SCRATCH, \
        f"image is {len(words)} words; code must end before the spill region at {SCRATCH}"
    sections = {}
    for line in CYCLES.read_text(encoding="utf-8").splitlines():
        m = re.match(r"CYCLES name=(\S+) start=\d+ end=\d+ cycles=(\d+) branches=(\S+)$", line)
        if m:
            sections[m.group(1)] = (int(m.group(2)), m.group(3))
    assert set(sections) == {"nec_ir_rx_hunt_probe", "nec_ir_rx_split_probe",
                             "nec_ir_rx_sample_wait", "nec_ir_rx_silence_wait"}, sections
    for name, (cycles, branches) in sections.items():
        want = 514 if "probe" in name else 258
        assert cycles == want, f"section {name}: {cycles} cycles, expected {want}"
        assert branches == "true", f"section {name} lost its branch"
    assert len(program.warnings) == 15, program.warnings
    assert all("IN-sampled" in w for w in program.warnings), program.warnings
    # the sample point sits inside the documented decision interval
    assert DECISION_LO_CYCLES < SAMPLE_CYCLES < DECISION_HI_CYCLES
    dut._log.info(
        f"committed program: {len(words)} words, spill region {SCRATCH}.."
        f"{SCRATCH + SPILL_WORDS - 1}, sample at {SAMPLE_CYCLES} cycles "
        f"(interval {DECISION_LO_CYCLES}..{DECISION_HI_CYCLES}), "
        f"{len(program.warnings)} documented branch warnings")


@cocotb.test()
async def test_good_frames(dut):
    """Three well-formed frames on one load: the committed transmitter's
    0xA5/0x3C, the 0x00/0xFF pair (the byte-value extremes: every bit of
    the address byte 0, every bit of the command byte 1), and one seeded
    random pair. Each must publish exactly (address, command) -- address
    first -- with no other writes."""
    start_clock(dut)
    rng = random.Random(RANDOM_SEED)
    rand_a, rand_c = rng.randrange(256), rng.randrange(256)
    assert (rand_a, rand_c) == (0x8D, 0x13), \
        f"seed drift: random pair is {rand_a:#04x}/{rand_c:#04x}"
    stim = Stimulus()
    stim.frame(0xA5, 0x3C, name="committed pair")
    stim.frame(0x00, 0xFF, name="byte extremes")
    stim.frame(rand_a, rand_c, name=f"random seed {RANDOM_SEED:#010x}")
    uo = await run_rx(dut, stim.envelope(), stim.cycles())
    check_writes(dut, uo, stim, "good frames")


@cocotb.test()
async def test_discard_policy_and_resync(dut):
    """Every discard case by name, in one stream: a repeat before any
    valid frame (no write at all), a valid frame, a repeat after it (the
    earlier result must survive), a bad address complement, a bad
    command complement, a 16-bit truncated frame (each: no write), and a
    final good frame proving the decoder resynchronised after every
    discard. `uo_out` must change exactly four times in the whole
    capture: frame A's two bytes and frame B's two."""
    start_clock(dut)
    stim = Stimulus()
    stim.repeat(name="repeat before any frame")
    stim.frame(0xA5, 0x3C, name="frame A")
    stim.repeat(name="repeat after frame A")
    stim.broken(0x77, 0x88, name="bad ~addr", inv_addr=0x00)
    stim.broken(0x77, 0x88, name="bad ~cmd", inv_cmd=0x00)
    stim.broken(0x77, 0x88, name="truncated at 16 bits", stop_after_bits=16)
    stim.frame(0x5A, 0xC3, name="frame B after discards")
    events = await run_rx(dut, stim.envelope(), stim.cycles())
    check_writes(dut, events, stim, "discard policy")
    assert len(events) == 5, \
        f"expected 5 uo_out edges (boot clear + 2 frames), got {events}"


@cocotb.test()
async def test_timing_edges(dut):
    """The model's +-10% window edges, driven as frames: all three data
    widths together at -10% and at +10%, the razor pair space0+bit_mark
    at -10% (the case the issue's ~1.1 ms sample point fails: a 0's next
    mark ends 1,012.5 us after the mark ends), space1+bit_mark at -10%,
    the leader mark alone at each edge, and both split-window edges for
    a repeat after a frame. Every frame must still decode to its driven
    bytes. Then one frame with space0 at -15% -- one window beyond --
    which is DOCUMENTED ACCEPTED (mid-space sampling tolerates
    wider-than-window skew; discrimination only breaks past ~1.47x
    stretch), and finally the x1.5-stretched frame, which must NOT come
    back correct (the rejection control)."""
    start_clock(dut)
    stim = Stimulus()
    # The leader-mark scales sit at 0.905/1.095 rather than exactly
    # +-10%: the encoder builds marks from whole carrier periods, and the
    # quantisation step (26,316 ns, 0.29% of the leader) would push a
    # -10% leader's envelope just below the model's closed window floor.
    # 0.905/1.095 keep the driven leader inside the window while every
    # data width (exact, unquantised) sits exactly on its edge.
    stim.frame(0xA5, 0x3C, name="all widths -10%",
               space0_ns=SPACE0_NS * 0.9, space1_ns=SPACE1_NS * 0.9,
               bit_mark_ns=BIT_MARK_NS * 0.9, leader_mark_ns=LEADER_MARK_NS * 0.905)
    stim.frame(0xA5, 0x3C, name="all widths +10%",
               space0_ns=SPACE0_NS * 1.1, space1_ns=SPACE1_NS * 1.1,
               bit_mark_ns=BIT_MARK_NS * 1.1, leader_mark_ns=LEADER_MARK_NS * 1.095)
    stim.frame(0xA5, 0x3C, name="razor space0+mark -10%",
               space0_ns=SPACE0_NS * 0.9, bit_mark_ns=BIT_MARK_NS * 0.9)
    stim.frame(0xA5, 0x3C, name="space1+mark -10%",
               space1_ns=SPACE1_NS * 0.9, bit_mark_ns=BIT_MARK_NS * 0.9)
    stim.frame(0x31, 0x42, name="frame before split-edge repeats")
    stim.repeat(name="repeat, split -10%", repeat_space_ns=REPEAT_SPACE_NS * 0.9)
    stim.repeat(name="repeat, split +10%", repeat_space_ns=REPEAT_SPACE_NS * 1.1)
    stim.frame(0xC3, 0x96, name="beyond window: space0 -15% (accepted)",
               space0_ns=SPACE0_NS * 0.85, check_model=False)
    uo = await run_rx(dut, stim.envelope(), stim.cycles())
    check_writes(dut, uo, stim, "timing edges")

    # the x1.5 stretch: same frame shape, every interval 1.5x. The DUT is
    # already loaded and hunting on an idle-high line; drive from now.
    stretched_stim = Stimulus()
    stretched_stim.frame(0xA5, 0x3C, name="stretched x1.5")
    env = stretched(stretched_stim.envelope(), 1.5)
    base_ns = float(get_sim_time("ns"))
    cocotb.start_soon(drive_line(dut, env, base_ns))
    cycles = int(stretched_stim.t * 1.5 / CLK_PERIOD_NS) + 4_000
    uo = await capture_writes(dut, base_ns, base_ns + cycles * CLK_PERIOD_NS)
    got = [v for (_e, v) in write_events(uo)]
    assert got != [0xA5, 0x3C], (
        "NEGATIVE CONTROL FAILED TO FAIL: the x1.5-stretched frame came "
        f"back correct ({[f'{v:02X}' for v in got]})")
    dut._log.info(
        f"x1.5 stretch control: writes {[f'{v:02X}' for v in got]} -- not "
        f"the driven pair, as required")


@cocotb.test()
async def test_early_life_and_back_to_back(dut):
    """The line-level edge cases: the line held LOW from the MODE drop
    (a receiver module still powering up, or a mid-mark capture start)
    for 1 ms before idling high -- the program's boot sync must wait it
    out and still decode the first frame; and two frames back to back
    with only 5 ms between the final mark and the next leader (just
    above the model's 3,645 us latch floor) must both publish."""
    start_clock(dut)
    stim = Stimulus()
    stim.frame(0x5C, 0x6D, name="first frame after a low start")
    stim.frame(0x33, 0x44, name="back-to-back, 5 ms gap", gap=5_000_000.0)
    lead = 2_000_000.0
    env = stim.envelope(lead_ns=lead)
    stuck = Signal(1, name="line-with-low-start")
    stuck.transitions = [(1.0, 0), (1_000_000.0, 1)] + list(env.transitions)
    uo = await run_rx(dut, stuck, stim.cycles(lead_ns=lead))
    check_writes(dut, uo, stim, "early life")


@cocotb.test()
async def test_negative_mutated_sample_point(dut):
    """The committed source re-assembled with the sample delay moved to
    55,000 cycles (the issue's 1.1 ms figure): the razor frame (space0
    and bit_mark both -10%) must NOT come back correct -- its 0 bits'
    next marks end 4,375 cycles before the mutant samples, so 0s read
    as 1s and the published bytes are not the driven ones. This is the
    proof that the sample-point placement, not some wide tolerance, is
    what the edge tests above exercise."""
    start_clock(dut)
    text = SRC.read_text(encoding="utf-8")
    n_count = text.count("LDI   R2, 158")
    assert n_count == 1, f"expected 1 sample-count LDI, found {n_count}"
    # 2 + 1 + 213*258 + (WAIT 41 = 42) + 1 = 55,000 cycles to the sample
    mutant_text = (text.replace("LDI   R2, 158", "LDI   R2, 213")
                       .replace("WAIT  11              ; 12", "WAIT  41              ; 42"))
    assert "WAIT  41" in mutant_text, "sample pad site not found"
    program = asm.assemble_text(mutant_text, source_name="<mutant 1.1ms sample>")
    assert len(program.words) == 115
    stim = Stimulus()
    stim.frame(0xA5, 0x3C, name="razor frame vs 1.1 ms mutant",
               space0_ns=SPACE0_NS * 0.9, bit_mark_ns=BIT_MARK_NS * 0.9)
    uo = await run_rx(dut, stim.envelope(), stim.cycles(), words=program.words)
    got = [v for (_e, v) in write_events(uo)]
    assert got != [0xA5, 0x3C], (
        "NEGATIVE CONTROL FAILED TO FAIL: the 1.1 ms-sample mutant decoded "
        f"the razor frame correctly ({[f'{v:02X}' for v in got]})")
    dut._log.info(
        f"mutant 1.1 ms sample vs razor frame: writes "
        f"{[f'{v:02X}' for v in got]} -- not the driven pair, as required")
