"""DUT-facing UART receive-path and low-baud firmware bench (issue #91;
target-spec rows 1 and 10).

Issue #71 / `test_firmware_uart.py` measured UART *transmit* at one rate
(50 cycles/bit).  This bench closes the two gaps that record named:

* **the receive direction** -- committed programs `firmware/asm/uart_rx.asm`
  (50 cycles/bit), `uart_rx_115200.asm` (434) and `uart_rx_9600.asm` (5,208)
  are loaded over the real load-phase pins onto the real top
  (`tt_um_2amlogic_protocol_emulator`), executed by the ISA core, and fed
  `ui_in[1]` waveforms built by the **independent** reference model
  (`verification/reference_models/uart.py`: `encode_frame` /
  `encode_slow_frame`, `UartDecoder`, `check_frame`, plus
  `waveform.apply_jitter`).  The received byte is read off `uo_out`.
* **the low-baud end of row 1's 9,600-1,000,000 baud range** -- the nested-
  `WAIT` outer-loop case (a bit period above one 8-bit `WAIT`), for receive
  (`uart_rx_115200`, `uart_rx_9600`) and transmit (`uart_tx_9600.asm`, judged
  by `UartDecoder` exactly like the 1 Mbaud transmitter).

There is NO UART peripheral anywhere: the receiver is `IN` + `WAIT` + ALU
ops (CLAUDE.md: the ISA is the product).

Units.  Timing is stated in **core cycles**.  Baud figures are arithmetic at
the *unconfirmed* target clock of target-spec row 4 (this program's own flow
cannot yet run STA against this core -- `verification/records/sta-corner-
sweep/`): the simulation clock is 20 ns purely to name that nominal, so
P cycles/bit is 1e9/(P x 20) baud.

What is judged, and by whom
---------------------------
* The stimulus is the model's.  The bench only chooses the byte, the
  rate-error scale, the jitter amplitude and the idle gap.
* The expected byte is the byte the model was asked to send; the DUT's
  answer is `uo_out`.
* The firmware exposes its real sample instants on `uio_out[1]` (a mark that
  rises right after each `IN` of the line and falls a few cycles later), so
  the bench measures them **at the pin** instead of trusting the program's
  arithmetic: consecutive samples must be exactly P cycles apart (cycle-
  exact, no data dependence), the first sample must land within the
  start-detect poll's granularity of the static window, and every sample
  must sit inside the sender's bit it was meant to read.  A stop bit that
  reads 0 raises `uio_out[2]`.
  (RX moved to `ui_in[1]` in issue #178, DR 0010's target pin plan; `ui_in[0]`
  is `PROG_SER` and is held low, or toggled on purpose, never the line.)

Rate error and the model's bound
--------------------------------
Row 10's adopted bound is cumulative per-frame drift under ~2 % of the bit
period; the model measures it on the last in-frame edge.  That bound
describes a *transmitter*: nine bit periods at +-e per-bit error give up to
9e of drift, so the bound is ~0.2 % per-bit.  The issue asks the receiver to
tolerate **+-2 % per-bit rate error** -- ten times that, and deliberately
outside what `check_frame` accepts of a transmitter.  This bench therefore
reports, for every stimulus, both numbers: the DUT receiver's verdict, and
the model's `check_frame` verdict on the stimulus, and asserts the receiver
at +-2 % (and the model at +-0.2 %) rather than pretending the two bounds
are one.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
1. Receiver at +-10 % per-bit rate error must return wrong bytes (the
   compare can fail); a sweep records where tolerance actually ends.
2. The model's 1.025x transmitter must FAIL `check_frame` (row 10's bound
   rejects an out-of-bound sender), and a 1.025x re-timing of the DUT's
   own captured low-baud TX waveform must FAIL too.
3. A stop bit forced low must set the framing-error flag.
4. The cycle-exactness checker is fed a one-cycle-perturbed copy of a real
   capture and must reject it.
5. (Archived with the record) a mutated-firmware probe.
"""

import math
import random
import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

from reference_models.uart import (
    MAX_FRAME_DRIFT_PCT,
    UART_FRAME_BITS,
    UartDecoder,
    bit_period_ns,
    encode_frame,
    encode_slow_frame,
)
from reference_models.waveform import Signal, apply_jitter

CLK_PERIOD_NS = 20  # names the unconfirmed 50 MHz target of row 4; not a result


def _find_repo_root() -> Path:
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
    raise RuntimeError("cannot locate the repo root")


REPO_ROOT = _find_repo_root()
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402

# Non-test helper only (cocotb discovers tests by scanning this module's own
# namespace, so importing a helper function registers nothing).
from test_protocol_emulator import load_program  # noqa: E402

ASM_DIR = REPO_ROOT / "firmware" / "asm"
BUILD_DIR = REPO_ROOT / "firmware" / "build"

#: Receive programs: stem -> cycles per bit (cross-checked against the
#: `; BIT-PERIOD-CYCLES n` line in each committed .asm).
RX_PROGRAMS = {"uart_rx": 50, "uart_rx_115200": 434, "uart_rx_9600": 5208}
TX_LOW = ("uart_tx_9600", 5208)
#: The pin-dependent branches in an RX program: the `sync` and `poll`
#: start-edge handshakes and the one post-stop-bit re-arm choice.
RX_LINT_WARNINGS = 3

#: Edges between an `IN` retiring and its sample mark being visible at the
#: pin (asserted by `test_pin_timing_calibration`).
MARK_VISIBLE_AFTER_IN = 1
#: Start-detect poll loop length (IN, AND, BNZ): start-edge granularity.
POLL_PERIOD = 3

#: Pin plan (DR 0010 target, issue #178): RX is `ui_in[1]`; `ui_in[0]` is
#: PROG_SER and must have no influence on reception.  The debug bits the RX
#: images write to `UIO_OUT` follow R1 = the RX mask (2): mark = bit 1,
#: framing-error flag = bit 2.
RX_BIT = 1
MARK_BIT = 1
FERR_BIT = 2
RX_IDLE = 1 << RX_BIT
#: Level of `ui_in[0]` (PROG_SER) the bench presents; directed tests toggle it.
UI0 = {"v": 0}


def set_rx(dut, level):
    """Drive the RX line (`ui_in[1]`), `ui_in[0]` at its current level."""
    dut.ui_in.value = ((level & 1) << RX_BIT) | (UI0["v"] & 1)


PROBE_BYTES = (0xA5, 0x5A, 0x00, 0xFF, 0x80, 0x01, 0x55, 0xAA, 0x40, 0xC3)


# =======================================================================
# Committed-artifact readers
# =======================================================================


def load_image(stem: str) -> list:
    words = []
    for line in (BUILD_DIR / f"{stem}.hex").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            words.append(int(line, 16))
    assert words, f"{stem}: committed image is empty"
    return words


def header_bit_period(stem: str) -> int:
    text = (ASM_DIR / f"{stem}.asm").read_text(encoding="utf-8")
    match = re.search(r"^; BIT-PERIOD-CYCLES (\d+)$", text, re.M)
    assert match, f"{stem}.asm has no '; BIT-PERIOD-CYCLES n' header line"
    return int(match.group(1))


def baud_of(period_cycles: int) -> float:
    """Arithmetic at the unconfirmed clock, never a measurement."""
    return 1e9 / (period_cycles * CLK_PERIOD_NS)


def first_sample_latency_range(period_cycles: int):
    """Static window, in cycles, between the first clock edge that can see
    the start edge and the first sample mark: poll granularity (0..2) + the
    BNZ fall-through (3) + the program's start delay X = floor(1.5P - 4.5)
    + IN->mark visibility."""
    x = int(1.5 * period_cycles - 4.5)
    lo = 3 + x + MARK_VISIBLE_AFTER_IN
    return lo, lo + POLL_PERIOD - 1


# =======================================================================
# Capture and drive
# =======================================================================


async def capture_ports(dut, cycles: int):
    """Sample `uo_out` and `uio_out` after each of the next `cycles` rising
    edges (read-only phase, the discipline the sibling benches use).
    Returns `(times_ns, uo, uio)`; index n is the n-th edge after the call
    (index 0 is the state at the call)."""
    await ReadOnly()
    times = [float(get_sim_time("ns"))]
    uo = [int(dut.uo_out.value)]
    uio = [int(dut.uio_out.value)]
    await Timer(1, unit="ns")
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        times.append(float(get_sim_time("ns")))
        uo.append(int(dut.uo_out.value))
        uio.append(int(dut.uio_out.value))
        await Timer(1, unit="ns")
    return times, uo, uio


async def drive_line(dut, line: Signal, base_ns: float):
    """Apply the model's `Signal` to `ui_in[1]` (the RX line; `ui_in[0]`
    stays at `UI0`) at absolute sub-cycle times: `base_ns` + the signal's own
    times."""
    set_rx(dut, line.initial)
    for t, v in line.transitions:
        target_ps = round((base_ns + t) * 1000)
        now_ps = round(float(get_sim_time("ps")))
        assert target_ps > now_ps, "stimulus transition scheduled in the past"
        await Timer(target_ps - now_ps, unit="ps")
        set_rx(dut, v)


async def toggle_ui0(dut, every_cycles):
    """Flip `ui_in[0]` (PROG_SER) every `every_cycles` clocks (+3 ns, so it
    never lands on a clock edge), leaving the RX bit as the drive coroutine
    last set it."""
    while True:
        await Timer(every_cycles * CLK_PERIOD_NS + 3, unit="ns")
        UI0["v"] ^= 1
        dut.ui_in.value = (int(dut.ui_in.value) & ~1) | UI0["v"]


# =======================================================================
# Stimulus built from the reference model
# =======================================================================


class FrameSpec:
    def __init__(self, data, scale=1.0, jitter_frac=0.0, gap_bits=2.0,
                 stop_low=False, label=""):
        self.data = data
        self.scale = scale
        self.jitter_frac = jitter_frac
        self.gap_bits = gap_bits
        self.stop_low = stop_low
        self.label = label or f"x{scale:g}/j{jitter_frac:g}"
        self.t_start = None  # nominal (pre-jitter) start edge, ns
        self.t_end = None


def build_stimulus(period_cycles: int, frames, rng) -> Signal:
    """Concatenate the frames onto one line using the model's generators."""
    baud = baud_of(period_cycles)
    bit_ns = bit_period_ns(baud)
    line = Signal(1, name=f"ui_in1@{period_cycles}")
    t = max(40, 2 * period_cycles) * CLK_PERIOD_NS + rng.uniform(1.0, 19.0)
    for spec in frames:
        spec.t_start = t
        piece = Signal(1, name="piece")
        if spec.scale == 1.0:
            end = encode_frame(spec.data, baud, piece, t0=t)
        else:
            end = encode_slow_frame(spec.data, baud, piece, t0=t, scale=spec.scale)
        if spec.stop_low:
            assert piece.transitions[-1][1] == 1, "stop_low needs a data-0 last bit"
            stop_rise = piece.transitions.pop()
            piece.transitions.append((stop_rise[0] + bit_ns * spec.scale, 1))
            end += bit_ns * spec.scale
        spec.t_end = end
        if spec.jitter_frac:
            apply_jitter(piece, rng, spec.jitter_frac * bit_ns * spec.scale)
        for tt, vv in piece.transitions:
            line.add(tt, vv)
        t = end + spec.gap_bits * bit_ns
    return line


# =======================================================================
# Analysis
# =======================================================================


def mark_rises(uio, bit=MARK_BIT):
    return [
        n for n in range(1, len(uio))
        if (uio[n] >> bit) & 1 and not (uio[n - 1] >> bit) & 1
    ]


def check_cycle_exact_spacing(marks, period_cycles):
    """Violations of 'consecutive sample marks of one frame are exactly
    `period_cycles` apart'."""
    return [
        (k, b - a) for k, (a, b) in enumerate(zip(marks, marks[1:]))
        if b - a != period_cycles
    ]


def analyze(frames, line, times, uo, uio, period_cycles):
    """Per-frame measurement of one run.  Never asserts; returns dicts."""
    all_marks = mark_rises(uio)
    bit_ns = bit_period_ns(baud_of(period_cycles))
    results = []
    prev = 0
    for i, spec in enumerate(frames):
        t_lo = spec.t_start + 0.7 * bit_ns
        t_hi = (frames[i + 1].t_start + 0.7 * bit_ns) if i + 1 < len(frames) \
            else float("inf")
        marks = [c for c in all_marks if t_lo <= times[c] < t_hi]
        res = {"label": spec.label, "marks": marks, "n_marks": len(marks),
               "prev": prev}
        # the (jittered) start edge as applied, and the first clock edge
        # that can see it
        t_edge = next(
            t for t, v in line.transitions
            if v == 0 and t >= spec.t_start - 0.2 * bit_ns
        )
        e_obs = next(n for n, tn in enumerate(times) if tn > t_edge)
        res["e_obs"] = e_obs
        if marks:
            res["first_latency"] = marks[0] - e_obs
        res["got"] = None
        if len(marks) == UART_FRAME_BITS - 1:
            res["spacing_violations"] = check_cycle_exact_spacing(marks, period_cycles)
            res["before"] = uo[marks[7]]
            res["got"] = uo[marks[7] + 20]
            res["err_flag"] = (uio[marks[8] + 8] >> FERR_BIT) & 1
            res["fracs"] = [
                (times[m - MARK_VISIBLE_AFTER_IN] - t_edge) / (bit_ns * spec.scale)
                - (k + 1)
                for k, m in enumerate(marks)
            ]
        prev = spec.data
        results.append(res)
    return results


def frame_ok(spec, res, period_cycles, strict_center=False):
    """The full per-frame verdict.  Returns a list of failure strings."""
    if res["n_marks"] != UART_FRAME_BITS - 1:
        return [f"{res['n_marks']} sample marks, expected {UART_FRAME_BITS - 1}"]
    fails = []
    if res["spacing_violations"]:
        fails.append(f"sample spacing != {period_cycles}: {res['spacing_violations']}")
    if res["got"] != spec.data:
        fails.append(f"received 0x{res['got']:02x}, sent 0x{spec.data:02x}")
    if res["before"] != res["prev"]:
        fails.append(
            f"uo_out was 0x{res['before']:02x} before the emit, expected the "
            f"previous frame's 0x{res['prev']:02x}"
        )
    want_err = 1 if spec.stop_low else 0
    if res["err_flag"] != want_err:
        fails.append(f"framing-error flag {res['err_flag']}, expected {want_err}")
    lo, hi = first_sample_latency_range(period_cycles)
    if not lo <= res["first_latency"] <= hi:
        fails.append(
            f"first sample mark {res['first_latency']} cycles after the start "
            f"edge became visible; static window [{lo}, {hi}]"
        )
    # Each sample must lie inside the sender's own bit: nominal centre 0.5,
    # allowed to walk by the accumulated rate error and the injected jitter.
    for k, fr in enumerate(res["fracs"]):
        slack = abs(spec.scale - 1.0) * (k + 1.5) + spec.jitter_frac
        if not (0.25 - slack <= fr <= 0.75 + slack):
            fails.append(f"sample {k} at {fr:+.3f} of its bit (centre 0.5)")
    if strict_center:
        tol = (POLL_PERIOD + 1) / period_cycles + 0.001
        for k, fr in enumerate(res["fracs"]):
            if abs(fr - 0.5) > tol:
                fails.append(f"nominal sample {k} off-centre by {fr - 0.5:+.3f} bit")
    return fails


async def run_rx(dut, stem, frames, seed, ui0_toggle_cycles=0, start_clock=True,
                 words=None):
    """Load `stem`, drive `frames`, capture, analyse.  Returns
    `(results, line)` with `line` on the capture's absolute time base.
    `start_clock=False` lets a caller that runs many programs in one test
    (the seeded regression, issue #192) own the single clock coroutine;
    `words` runs that image instead of the committed `stem` one (the
    regression's own assembly of the case; `stem` still names the bit period)."""
    period = RX_PROGRAMS[stem]
    rng = random.Random(seed)
    if start_clock:
        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    if words is None:
        words = load_image(stem)
    assert len(words) <= 256, f"{stem}: {len(words)} words exceeds the 256-word store"
    await load_program(dut, words)
    UI0["v"] = 0  # PROG_SER idles low after the MODE drop
    set_rx(dut, 1)  # RX idles high from the MODE drop onward
    base_ns = float(get_sim_time("ns"))
    line = build_stimulus(period, frames, rng)
    cycles = math.ceil(frames[-1].t_end / CLK_PERIOD_NS) + 3 * period
    cocotb.start_soon(drive_line(dut, line, base_ns))
    toggler = None
    if ui0_toggle_cycles:
        toggler = cocotb.start_soon(toggle_ui0(dut, ui0_toggle_cycles))
    times, uo, uio = await capture_ports(dut, cycles)
    if toggler is not None:
        toggler.cancel()
    UI0["v"] = 0
    for f in frames:
        f.t_start += base_ns
        f.t_end += base_ns
    shifted = Signal(line.initial, name=line.name)
    shifted.transitions = [(t + base_ns, v) for t, v in line.transitions]
    return analyze(frames, shifted, times, uo, uio, period), shifted


def model_check_verdicts(line, period, frames):
    """The reference model's own opinion of each stimulus frame:
    `check_frame` (True = inside row 10's cumulative-drift bound)."""
    dec = UartDecoder(baud_of(period))
    out = []
    for f in frames:
        try:
            reps = dec.decode(line, t_from=f.t_start - 1.0, max_frames=1)
        except ValueError:
            out.append(None)
            continue
        out.append(dec.check_frame(reps[0]) if reps else None)
    return out


def distinct_bytes(n):
    out, prev = [], 0
    for i in range(n):
        b = PROBE_BYTES[i % len(PROBE_BYTES)]
        if b == prev:
            b ^= 0x5A
        out.append(b)
        prev = b
    return out


def log_run(dut, stem, frames, results, verdicts):
    for spec, res, ok in zip(frames, results, verdicts):
        fr = res.get("fracs")
        span = f"[{min(fr):+.3f}, {max(fr):+.3f}]" if fr else "n/a"
        got = f"0x{res['got']:02x}" if res.get("got") is not None else "----"
        dut._log.info(
            f"{stem} {spec.label:>12s} gap {spec.gap_bits:3.1f}b sent "
            f"0x{spec.data:02x} got {got} first-latency "
            f"{res.get('first_latency')} cyc, sample-position span {span} "
            f"bit, model check_frame(stimulus)={ok}"
        )


def standard_frames(rng, reduced=False):
    """Directed + constrained-random frame mix for one program."""
    plan = [
        (1.0, 0.0, "nominal", 0.0), (1.0, 0.0, "nominal", 0.5),
        (1.0, 0.0, "nominal", 2.5),
        (1.0, 0.10, "jitter10%", 1.0), (1.0, 0.10, "jitter10%", 2.5),
        (1.02, 0.0, "+2%", 1.0), (1.02, 0.0, "+2%", 2.5),
        (0.98, 0.0, "-2%", 1.0), (0.98, 0.0, "-2%", 2.5),
        (1.02, 0.10, "+2%+jit10%", 1.0), (0.98, 0.10, "-2%+jit10%", 2.5),
        (1.002, 0.0, "+0.2%", 1.0), (0.998, 0.0, "-0.2%", 1.0),
    ]
    if reduced:  # the slow programs: a representative subset
        plan = [plan[0], plan[2], plan[3], plan[5], plan[7], plan[9]]
    frames = []
    for b, (scale, jit, label, gap) in zip(distinct_bytes(len(plan)), plan):
        frames.append(FrameSpec(b, scale=scale, jitter_frac=jit,
                                gap_bits=gap, label=label))
    return frames


async def run_standard(dut, stem, seed, reduced):
    period = RX_PROGRAMS[stem]
    frames = standard_frames(random.Random(seed), reduced=reduced)
    results, line = await run_rx(dut, stem, frames, seed=seed + 1)
    verdicts = model_check_verdicts(line, period, frames)
    log_run(dut, stem, frames, results, verdicts)
    failed = []
    for spec, res in zip(frames, results):
        strict = spec.scale == 1.0 and not spec.jitter_frac
        failed += [f"{spec.label} 0x{spec.data:02x}: {m}"
                   for m in frame_ok(spec, res, period, strict)]
    assert not failed, "\n".join(failed)
    for spec, ok in zip(frames, verdicts):
        if spec.label in ("nominal", "+0.2%", "-0.2%"):
            assert ok, f"{spec.label}: model rejects its own in-bound stimulus"


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_images_are_fresh(dut):
    """Committed images match their committed sources, fit the 256-word
    store, carry the bit period this bench grades, and the assembler's
    data-dependent-latency lint flags exactly the receivers' handshake
    branches (and nothing at all in the transmitter)."""
    for stem, period in [*RX_PROGRAMS.items(), TX_LOW]:
        program = asm.assemble_file(ASM_DIR / f"{stem}.asm")
        drift = asm.check_against(program, BUILD_DIR)
        assert not drift, f"{stem}: committed firmware/build/ artifacts drifted: {drift}"
        assert len(program.instructions) <= 256, f"{stem}: exceeds the program store"
        assert header_bit_period(stem) == period, f"{stem}: header period != {period}"
        want = RX_LINT_WARNINGS if stem.startswith("uart_rx") else 0
        assert len(program.warnings) == want, (
            f"{stem}: {len(program.warnings)} lint warning(s), expected {want}: "
            f"{program.warnings}"
        )
        dut._log.info(
            f"{stem}: {len(program.instructions)}/256 words, "
            f"{len(program.warnings)} handshake warning(s), {period} cycles/bit"
        )


@cocotb.test()
async def test_pin_timing_calibration(dut):
    """Directed: pin down the port timings the other tests lean on, with a
    three-instruction program (`IN R2,UI_IN; OUT UIO_OUT,R2; HALT`): which
    edge an `IN` samples the line at, and when its `OUT` is visible.
    `ui_in[1]` (RX) is raised just after edge 1 (must be seen by the `IN`
    retiring at edge 2) or just after edge 2 (must be missed)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = asm.assemble_text("IN R2, UI_IN\nOUT UIO_OUT, R2\nHALT\n")
    words = [i.word for i in program.instructions]
    seen = {}
    for label, edge_offset in (("after-edge-1", 1), ("after-edge-2", 2)):
        await load_program(dut, words)
        UI0["v"] = 0
        set_rx(dut, 0)
        for _ in range(edge_offset):
            await RisingEdge(dut.clk)
        await Timer(5, unit="ns")
        set_rx(dut, 1)
        _times, _uo, uio = await capture_ports(dut, 8)
        rises = mark_rises(uio, RX_BIT)
        seen[label] = rises[0] + edge_offset if rises else None
        set_rx(dut, 0)
    dut._log.info(f"calibration (visible-at edge number, edge 0 = MODE drop): {seen}")
    assert seen["after-edge-1"] == 2 + MARK_VISIBLE_AFTER_IN, seen
    assert seen["after-edge-2"] is None, seen


@cocotb.test()
async def test_uart_rx_1mbaud_class(dut):
    """50 cycles/bit: bytes, cycle-exact sampling, jitter, +-2 % rate error."""
    await run_standard(dut, "uart_rx", seed=9100, reduced=False)


@cocotb.test()
async def test_uart_rx_115200_class(dut):
    """434 cycles/bit (nested WAIT, one outer pass)."""
    await run_standard(dut, "uart_rx_115200", seed=9110, reduced=False)


@cocotb.test()
async def test_uart_rx_9600_class(dut):
    """5,208 cycles/bit (nested WAIT, 20 outer passes): row 1's low-baud end."""
    await run_standard(dut, "uart_rx_9600", seed=9120, reduced=True)


@cocotb.test()
async def test_negative_control_rate_error_beyond_tolerance(dut):
    """Drive the receiver past its tolerance: +-10 % per-bit error MUST give
    wrong bytes (the compare can fail).  The sweep records where tolerance
    actually ends (informational), except that +-2 % must pass.  The
    model's own verdict on a 1.025x transmitter is asserted too."""
    stem = "uart_rx"
    period = RX_PROGRAMS[stem]
    scales = [1.02, 0.98, 1.04, 0.96, 1.06, 0.94, 1.08, 0.92, 1.10, 0.90]
    probe = (0x80, 0x40, 0x01, 0xA5)
    frames = [FrameSpec(b, scale=s, gap_bits=12.0, label=f"x{s:g}")
              for s in scales for b in probe]
    results, _line = await run_rx(dut, stem, frames, seed=9131)
    by_scale = {}
    for spec, res in zip(frames, results):
        by_scale.setdefault(spec.scale, []).append(res.get("got") == spec.data)
    for s in scales:
        dut._log.info(
            f"sweep {stem} rate x{s:g}: {sum(by_scale[s])}/{len(by_scale[s])} "
            f"frames received correctly"
        )
    for s in (1.02, 0.98):
        assert all(by_scale[s]), f"receiver must tolerate +-2 % (x{s:g}): {by_scale[s]}"
    for s in (1.10, 0.90):
        assert not all(by_scale[s]), (
            f"NEGATIVE CONTROL FAILED TO FAIL: x{s:g} rate error still received "
            "every byte correctly; the compare cannot be trusted"
        )

    dec = UartDecoder(baud_of(period))
    slow = Signal(1, name="model-1.025x")
    encode_slow_frame(0x5A, baud_of(period), slow, t0=period * CLK_PERIOD_NS, scale=1.025)
    rep = dec.decode(slow)[0]
    assert rep.data == 0x5A and not dec.check_frame(rep), (
        f"model accepted a 1.025x transmitter at {rep.drift_pct:.3f}% drift"
    )
    dut._log.info(
        f"model negative control: 1.025x sender decodes to 0x5a but check_frame "
        f"False at {rep.drift_pct:.3f}% (bound {MAX_FRAME_DRIFT_PCT}%)"
    )


@cocotb.test()
async def test_framing_error_flag_and_recovery(dut):
    """A stop bit held low raises `uio_out[2]`; the next, good frame is still
    received (and clears it)."""
    stem = "uart_rx"
    frames = [
        FrameSpec(0x5A, gap_bits=4.0, stop_low=True, label="stop-low"),
        FrameSpec(0xA5, gap_bits=2.0, label="good-after"),
    ]
    results, _line = await run_rx(dut, stem, frames, seed=9141)
    failed = []
    for spec, res in zip(frames, results):
        failed += [f"{spec.label}: {m}" for m in frame_ok(spec, res, RX_PROGRAMS[stem])]
        dut._log.info(f"{spec.label}: got {res.get('got')} err_flag {res.get('err_flag')}")
    assert not failed, "\n".join(failed)


@cocotb.test()
async def test_ui_in0_prog_ser_has_no_effect(dut):
    """`ui_in[0]` (PROG_SER) toggled mid-frame, every 7 clocks, must not change
    the received byte, the sample marks or the framing flag: RX is `ui_in[1]`
    only.  Compared against the same frames received with `ui_in[0]` held low."""
    stem = "uart_rx"
    period = RX_PROGRAMS[stem]
    probe = (0xA5, 0x5A, 0x00, 0xFF)
    runs = {}
    for name, toggle in (("held-low", 0), ("toggling", 7)):
        frames = [FrameSpec(b, gap_bits=2.0, label=f"{name}-{b:02x}") for b in probe]
        results, _line = await run_rx(dut, stem, frames, seed=9161,
                                      ui0_toggle_cycles=toggle)
        for spec, res in zip(frames, results):
            bad = frame_ok(spec, res, period)
            assert not bad, f"{spec.label}: {bad}"
        runs[name] = [(res.get("got"), res["n_marks"], res.get("err_flag"))
                      for res in results]
    assert runs["held-low"] == runs["toggling"], runs
    assert [g for g, _n, _e in runs["toggling"]] == list(probe), runs
    dut._log.info(f"ui_in[0] toggling mid-frame left reception unchanged: {runs['toggling']}")


@cocotb.test()
async def test_negative_control_spacing_checker_can_fail(dut):
    """The cycle-exactness checker passes a real capture and rejects the same
    capture with one sample mark displaced by a single cycle."""
    stem = "uart_rx"
    period = RX_PROGRAMS[stem]
    frames = [FrameSpec(0xA5, gap_bits=2.0, label="control")]
    results, _line = await run_rx(dut, stem, frames, seed=9151)
    marks = results[0]["marks"]
    assert len(marks) == UART_FRAME_BITS - 1
    assert check_cycle_exact_spacing(marks, period) == []
    bent = list(marks)
    bent[4] += 1
    violations = check_cycle_exact_spacing(bent, period)
    assert violations, "NEGATIVE CONTROL FAILED TO FAIL: a displaced mark passed"
    dut._log.info(f"displaced-mark control rejected as required: {violations}")


@cocotb.test()
async def test_uart_tx_9600_low_baud(dut):
    """Low-baud transmit (nested WAIT): `uart_tx_9600` frames recovered and
    graded by the independent model at 5,208 cycles/bit, every TX edge on a
    whole multiple of the period; a 1.025x re-timing of the captured
    waveform must fail `check_frame`."""
    stem, period = TX_LOW
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    words = load_image(stem)
    assert len(words) <= 256, f"{stem}: exceeds the program store"
    await load_program(dut, words)
    run_cycles = 2 * period + 2 * (UART_FRAME_BITS + 2) * period + 3 * period
    times, uo, _uio = await capture_ports(dut, run_cycles)
    tx = Signal(uo[0] & 1, name="tx")
    edge_cycle = {}
    for n in range(1, len(uo)):
        if (uo[n] & 1) != tx.current():
            tx.add(times[n], uo[n] & 1)
            edge_cycle[times[n]] = n
    dec = UartDecoder(baud_of(period))
    reports = dec.decode(tx)
    assert [r.data for r in reports] == [0x5A, 0xA5], reports
    for r in reports:
        dut._log.info(f"decoded {r}")
        assert r.stop_ok and dec.check_frame(r), (
            f"row-10 bound failed at {r.drift_pct:.3f}%"
        )
        start = edge_cycle[r.t_start]
        edges = sorted(c for c in edge_cycle.values()
                       if start <= c <= start + UART_FRAME_BITS * period)
        gaps = [b - a for a, b in zip(edges, edges[1:])]
        assert min(gaps) == period and all(g % period == 0 for g in gaps), (
            f"edge gaps {gaps} are not whole multiples of {period} cycles"
        )
        dut._log.info(
            f"frame 0x{r.data:02x}: start edge at cycle {start}, intra-frame "
            f"edge gaps {gaps} cycles, bit period {min(gaps)}"
        )
    stretched = Signal(tx.initial, name="tx*1.025")
    stretched.transitions = [(t * 1.025, v) for t, v in tx.transitions]
    bad = UartDecoder(baud_of(period)).decode(stretched)
    assert len(bad) == 2
    for r in bad:
        dut._log.info(f"negative control (captured x1.025): {r}")
        assert not dec.check_frame(r), (
            "NEGATIVE CONTROL FAILED TO FAIL: 1.025x captured waveform passed"
        )
