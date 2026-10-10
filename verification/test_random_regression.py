"""Seeded constrained-random regression of generated firmware on the real
core (issue #93; verification-plan.md section 4; target-spec row 8).

Until this bench, the constrained-random leg (issue #25) validated the
reference models with random stimulus, and the DUT-facing benches
(#71/#72/#73) ran a handful of directed cases on fixed committed
payloads. This bench joins the two: from ONE recorded seed it generates
assembler source from templates (`firmware_templates.py` -- UART TX frames,
SPI modes 0-3, I2C write at both speed grades; payload bytes, SPI mode,
burst count and rate, I2C address and data as immediates), assembles each
program with the DR 0003 assembler (`asm.assemble_text`), loads it over
the real serial load-phase pins onto `tt_um_2amlogic_protocol_emulator`,
runs it, and hands the captured pin waveform to the existing
**independent** models (`reference_models.uart/spi/i2c`). The generator
shares no code with the models or the RTL; the only bench-side inputs to
a verdict are the parameters the template rendered (payload bytes etc.).

Size and opt-in. The default is `DEFAULT_CASES` (20) programs per protocol
-- the shared-host limit. A larger sweep is opt-in via the environment
variable `RANDOM_REGRESSION_CASES=<n>`; case i of a bigger sweep is
byte-identical to case i of the default one (per-case RNG), so a larger
sweep only appends.

Reproducibility. `RECORDED_SEED` is mirrored into
`request-random-regression.json`'s `random_seed` (and asserted equal
below, the `test_protocol_models.py` pattern). Every failure message
leads with `seed=<S> protocol=<p> index=<i>`; regenerating that triple
(`python3 verification/firmware_templates.py --seed S --out DIR`)
reproduces the failing `.asm` byte for byte. If the environment variable
`RANDOM_REGRESSION_ARTIFACT_DIR` names a directory, the bench writes each
program's `.asm`, `.hex`, `.cycles.txt` there plus `verdicts.json` and
`coverage.json` (deterministic: no timestamps), which is how the evidence
record's artifacts were produced.

What is measured, and in what units. Cycles are core clocks, measured at
the pins. The 20 ns clock period only *names* target-spec row 4's
unconfirmed 50 MHz so the models (ns-denominated) can be fed; it is not a
frequency result. This is an Icarus RTL simulation; no synthesis or timing
number is produced or implied.

Negative controls (a regression that cannot fail cannot cite its passes):
mutated templates run on the DUT and graded by the same models -- a UART
program whose bit period is 3 cycles short, back-to-back streams of three
0xFF frames whose data-bit periods are 3 cycles long and 3 cycles short
(issue #97: 0xFF has no in-frame edge after bit 1, so only the model's
frame-pitch check can see the slow one), an SPI program driving the
wrong CPOL idle level, and I2C programs whose data-clock low phase is 10
cycles under the Table 10 floor -- must each be FAILED by the model; and
every SPI burst with a non-zero MOSI byte is re-graded under the three
wrong modes and must fail.

Like its siblings this file is *input* to `klt functional-verification`,
not a pytest module. Issue #104 adds the I2C write -> repeated START -> controller read family
(`i2c_rd`, polling firmware from `firmware/tools/gen_i2c_sr.py` with the
address and pointer as immediates; read payload drawn by class) with
**bounded peripheral clock stretching**: the reactive peripheral of
`test_firmware_i2c_sr.py` holds SCL low after 1-3 of three fixed sites
(before the repeated START, first read clock, before the STOP) for a
seeded duration (short/medium/long classes). The independent model grades
every transfer and the received byte is checked at the DUT's observable
result (`uo_out`). Determinism is claimed only for non-stretched phases:
every SCL interval except the stretched low and the high that follows it
is compared byte-identical against an unstretched run on the same grade;
the poll/handshake interval is bounded, not asserted exact. Controls: the
non-polling sibling under a selected schedule must fail, and a truncated
capture must fail.

SPI runs on the same pad model wired as an SPI board (issue #155): the
generated programs drive CS / MOSI / SCLK on `uio[0]` / `uio[1]` /
`uio[3]` through `WCTL UIO_DIR` and sample MISO on `uio[2]` (DR 0010's
target plan), and every run must end with the design having driven
exactly those three pins, without contention.

Both I2C families run on the silicon-true pad model (issue #136, DR 0012;
`verification/uio_pads.py`, through the directed benches' own
`run_words` / `run_on_pads`): the lines graded are SCL and SDA as
resolved per pin from the design's `uio_oe` / `uio_out`, a pull-up and
the open-drain peripheral, and read on `uio_in`; and every generated
program must end its run having driven exactly SCL and SDA, only ever
low, with no contention. Until #136 this was a bench-composed wired-AND
bus that never read `uio_oe`; the records minted that way are superseded.
A further control per grade and family: the generated program with its
`WCTL UIO_OD` turned into a reserved no-op must fail. The pad model is
zero-delay and logical -- nothing here is a claim about pull-up rise
time or pad drive strength -- and it decides nothing about the pin plan
(#94).

UART spacing (issue #97). Odd-indexed multi-frame UART programs send
their frames back to back (next START one bit after the STOP) and are
graded with the model's back-to-back frame-pitch check plus an exact
10-bit start-to-start cycle count; the others idle 256 cycles between
frames, where a single frame's timing is graded on its last in-frame edge
only (the model's documented isolated-frame limitation).

UART RX (issue #192). The committed receive programs (`uart_rx` 50,
`uart_rx_115200` 434, `uart_rx_9600` 5,208 core cycles per bit) are run
unchanged; what is seeded is the stimulus on `ui_in[1]` (payload class,
in-bound rate error / jitter, spacing), built and graded with the directed
bench's own helpers (`test_firmware_uart_rx.py`: the independent
`reference_models.uart` encoder / decoder, `frame_ok`): the received byte on
`uo_out`, the framing flag, cycle-exact sample spacing and sample position
inside the sender's bit. `ui_in[0]` (PROG_SER) is held low. Controls: the
receiver with one inter-sample WAIT stretched by 2 cycles must be rejected
for sample spacing, and a +-10 % per-bit sender must be rejected for a wrong
byte or an out-of-bit sample.

Limits: RTL, zero-delay Icarus simulation only. No SDF, no electrical pad
behaviour and no measured wall-clock baud is implied; baud figures are
arithmetic at row 4's unconfirmed clock.
"""

import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))
sys.path.insert(0, str(REPO_ROOT / "verification"))
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402
import firmware_templates as ft  # noqa: E402
import gen_i2c_sr  # noqa: E402

# Reused (functions only; importing registers no sibling tests).
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart import (  # noqa: E402
    capture_pin_bits,
    cycle_at_time,
    expected_edge_offsets,
)
from test_firmware_spi import burst_windows, cycles_between  # noqa: E402
from test_firmware_spi import run_on_pads as run_spi_on_pads  # noqa: E402
from test_firmware_i2c import (  # noqa: E402
    FAST,
    STD,
    grade_transfer,
    without_uio_od,
)
from test_firmware_i2c import run_words as run_i2c_on_pads  # noqa: E402
from test_firmware_i2c_sr import run_on_pads as run_i2c_rd_on_pads  # noqa: E402
from test_firmware_uart_rx import (  # noqa: E402
    FrameSpec,
    frame_ok,
    model_check_verdicts,
    run_rx,
)
from reference_models.i2c import check_transfer  # noqa: E402
from reference_models.spi import MODES, check_burst  # noqa: E402
from reference_models.uart import MAX_FRAME_DRIFT_PCT, UartDecoder  # noqa: E402
from reference_models.waveform import Signal  # noqa: E402

#: The one recorded seed; mirrored into the request's `random_seed`.
RECORDED_SEED = 20261009
_REQUEST = REPO_ROOT / "verification" / "request-random-regression.json"

CLK_PERIOD_NS = 20  # names row 4's unconfirmed 50 MHz; not a measurement
F_CLK_HZ = 1e9 / CLK_PERIOD_NS
I2C_CAPTURE_MARGIN = 300
TIME_TOL_NS = 1e-3  # absolute tolerance on float-ns comparisons
SPI_CAPTURE_MARGIN = 8

#: UART tx pin
TX_PIN, TX_BIT = "uo_out", 0

_GRADE = {"i2c_fast": FAST, "i2c_std": STD}


def case_count() -> int:
    raw = os.environ.get("RANDOM_REGRESSION_CASES")
    n = int(raw) if raw else ft.DEFAULT_CASES
    assert n > 0, "RANDOM_REGRESSION_CASES must be positive"
    return n


_ARTIFACT_DIR = os.environ.get("RANDOM_REGRESSION_ARTIFACT_DIR")

#: Everything graded in this run, for verdicts.json / coverage.json.
VERDICTS = []
CASES_RUN = []


def ident(case) -> str:
    return f"seed={RECORDED_SEED} protocol={case.protocol} index={case.index}"


def _emit(case) -> None:
    if _ARTIFACT_DIR:
        out = Path(_ARTIFACT_DIR)
        out.mkdir(parents=True, exist_ok=True)
        ft.write_artifacts(case, out)


def _assemble(case):
    """Assemble with the DR 0003 assembler; a template that does not
    assemble clean is a generator bug, reported with the case identity."""
    try:
        program = case.assemble()
    except asm.AsmError as exc:  # pragma: no cover - generator bug
        raise AssertionError(f"{ident(case)}: template did not assemble: {exc}")
    assert len(program.words) <= 256, f"{ident(case)}: exceeds 256 words"
    return program


def _record(case, passed, detail, **extra) -> None:
    program = case.assemble()
    VERDICTS.append(
        {
            "name": case.name,
            "protocol": case.protocol,
            "index": case.index,
            "params": case.params,
            "words": len(program.words),
            "total_cycles": program.total_cycles,
            "hex_sha256": hashlib.sha256(
                asm.render_hex(program).encode()
            ).hexdigest(),
            "verdict": "PASS" if passed else "FAIL",
            "detail": detail,
            **extra,
        }
    )


# =======================================================================
# UART
# =======================================================================


async def run_uart(dut, case, clock_started=True):
    program = _assemble(case)
    await load_program(dut, program.words)
    run_cycles = ft.uart_run_cycles(case, program) + 2 * case.params["period"]
    caps = await capture_pin_bits(dut, {"tx": (TX_PIN, TX_BIT)}, run_cycles)
    return caps["tx"]


def grade_uart(case, tx):
    """Returns (ok, detail). Every verdict is the model's: the decoder
    recovers bytes and measures drift, check_frame applies the row-10
    bound; cycle gaps are then measured at the pin."""
    period = case.params["period"]
    baud = 1e9 / (period * CLK_PERIOD_NS)
    back_to_back = case.params.get("back_to_back", False)
    # A back-to-back case declares its stream to the model, so a late
    # following start is graded as pitch drift rather than idle (#97).
    decoder = UartDecoder(baud, back_to_back=back_to_back)
    try:
        reports = decoder.decode(tx.signal)
    except ValueError as exc:  # UartFrameError: the model rejects the frame
        return False, f"model rejected the waveform: {exc}"
    want = case.params["payloads"]
    if len(reports) != len(want):
        return False, f"decoded {len(reports)} frame(s), expected {len(want)}"
    for n, (report, payload) in enumerate(zip(reports, want)):
        if report.data != payload:
            return False, f"frame {n}: decoded 0x{report.data:02x} != 0x{payload:02x}"
        if not report.stop_ok:
            return False, f"frame {n}: framing error"
        if not decoder.check_frame(report):
            pitch = (
                "n/a" if report.pitch_drift_pct is None
                else f"{report.pitch_drift_pct:.3f}%"
            )
            return False, (
                f"frame {n}: row-10 drift {report.drift_pct:.3f}% "
                f"(last edge), pitch {pitch}"
            )
        start = cycle_at_time(tx, report.t_start)
        # Half-open window: on a back-to-back stream the next frame's start
        # edge sits exactly at start + 10 * period and is not this frame's.
        edges = [
            c
            for c in tx.transition_cycles
            if start <= c < start + 10 * period
        ]
        offsets = [c - start for c in edges]
        wanted = [k * period for k in expected_edge_offsets(payload)]
        if offsets != wanted:
            return False, f"frame {n}: edge offsets {offsets} != {wanted} cycles"
        if back_to_back and n + 1 < len(reports):
            gap = cycle_at_time(tx, reports[n + 1].t_start) - start
            if gap != 10 * period:
                return False, (
                    f"frame {n}: start-to-start {gap} cycles != "
                    f"{10 * period} on a back-to-back stream"
                )
    spacing = " back to back" if back_to_back else ""
    return True, f"{len(want)} frame(s){spacing} @ {period} cycles/bit"


@cocotb.test()
async def test_recorded_seed_matches_request(dut):
    """The seed is recorded in the request, not just in source."""
    request = json.loads(_REQUEST.read_text())
    assert request["options"]["random_seed"] == RECORDED_SEED, (
        f"request random_seed {request['options']['random_seed']} != "
        f"bench RECORDED_SEED {RECORDED_SEED}"
    )
    n = case_count()
    if n > ft.DEFAULT_CASES:
        dut._log.warning(
            f"OPT-IN SWEEP: {n} programs per protocol (default "
            f"{ft.DEFAULT_CASES})"
        )
    dut._log.info(f"seed={RECORDED_SEED} cases/protocol={n}")


@cocotb.test()
async def test_uart_random_programs(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    failures = []
    for case in ft.generate(RECORDED_SEED, "uart", case_count()):
        _emit(case)
        CASES_RUN.append(case)
        tx = await run_uart(dut, case)
        ok, detail = grade_uart(case, tx)
        dut._log.info(f"{ident(case)} params={case.params} -> {ok} ({detail})")
        _record(case, ok, detail)
        if not ok:
            failures.append(f"{ident(case)}: {detail}")
    assert not failures, "UART random regression FAILED:\n" + "\n".join(failures)


# =======================================================================
# UART RX (issue #192)
# =======================================================================


def rx_frames(case):
    """Fresh `FrameSpec`s for a case (run_rx mutates them)."""
    p = case.params
    return [
        FrameSpec(f["data"], scale=p["scale"], jitter_frac=p["jitter_frac"],
                  gap_bits=f["gap_bits"], label=p["variation"])
        for f in p["frames"]
    ]


async def run_uart_rx(dut, case):
    """Load the case's receive program over the load-phase pins and play its
    seeded frames on `ui_in[1]`. Returns `(frames, results, line)`."""
    program = _assemble(case)  # the case's own assembly is what runs
    frames = rx_frames(case)
    results, line = await run_rx(
        dut, case.params["program"], frames, seed=case.params["stim_seed"],
        start_clock=False, words=program.words,
    )
    return frames, results, line


def grade_uart_rx(case, frames, results, line):
    """Returns (ok, detail, failures). Every verdict is the directed bench's:
    byte on `uo_out`, framing flag, cycle-exact sample spacing, sample
    position in the sender's bit; plus the independent model's opinion of
    the nominal (in-bound) stimulus."""
    period = case.params["period"]
    fails = []
    for n, (spec, res) in enumerate(zip(frames, results)):
        strict = spec.scale == 1.0 and not spec.jitter_frac
        fails += [f"frame {n} 0x{spec.data:02x}: {m}"
                  for m in frame_ok(spec, res, period, strict)]
    if case.params["variation"] == "nominal":
        # The model looks for a start edge with a 1e-9 ns look-back, which a
        # float64 absolute time past ~1e7 ns (late in a long run) cannot
        # resolve; hand it the same waveform rebased close to zero.
        off = frames[0].t_start - 1000.0
        near = Signal(line.initial, name=line.name)
        near.transitions = [(t - off, v) for t, v in line.transitions]
        rebased = []
        for f in frames:
            g = copy.copy(f)
            g.t_start, g.t_end = f.t_start - off, f.t_end - off
            rebased.append(g)
        for n, ok in enumerate(model_check_verdicts(near, period, rebased)):
            if not ok:
                fails.append(f"frame {n}: model rejects its own in-bound stimulus")
    if fails:
        return False, "; ".join(fails), fails
    got = [f"0x{r['got']:02x}" for r in results]
    return True, (
        f"{case.params['program']} @ {period} cycles/bit, {case.params['variation']}, "
        f"rx on {case.params['rx_pin']}, received {got}"
    ), []


# =======================================================================
# SPI
# =======================================================================

async def run_spi(dut, case):
    """Run a generated SPI program on the pad model's SPI board (the
    directed bench's `run_on_pads`, issue #155): the lines graded are CS,
    SCLK, MOSI and MISO as the pads resolve them, and the run must end
    with the design having driven exactly CS, SCLK and MOSI."""
    program = _assemble(case)
    mode = MODES[case.params["mode"]]
    run_cycles = program.total_cycles + SPI_CAPTURE_MARGIN
    caps, _pads = await run_spi_on_pads(
        dut, ident(case), program.words, mode, case.params["miso"], run_cycles,
    )
    return caps


def grade_spi(case, caps, wrong_mode_control=True):
    """Returns (ok, detail, wrong_mode_checked)."""
    mode = MODES[case.params["mode"]]
    half = case.params["half_period"]
    cs, sclk, mosi, miso = caps["cs"], caps["sclk"], caps["mosi"], caps["miso"]
    windows = burst_windows(cs)
    nb = len(case.params["mosi"])
    if len(windows) != nb:
        return False, f"{len(windows)} CS burst(s) captured, expected {nb}", 0
    checked = 0
    for b, (tf, tr, _cf, _cr) in enumerate(windows):
        try:
            report = check_burst(
                sclk.signal, mosi.signal, miso.signal, cs.signal, mode, F_CLK_HZ,
                t0=tf, t1=tr,
            )
        except ValueError as exc:
            return False, f"burst {b}: model rejected: {exc}", checked
        if not report.ok:
            return False, f"burst {b}: {report.violations}", checked
        if report.mosi_bytes != [case.params["mosi"][b]]:
            return False, f"burst {b}: MOSI {report.mosi_bytes}", checked
        if report.miso_bytes != [case.params["miso"][b]]:
            return False, f"burst {b}: MISO {report.miso_bytes}", checked
        if abs(report.sclk_period_ns - 2 * half * CLK_PERIOD_NS) > TIME_TOL_NS:
            return False, f"burst {b}: SCLK period {report.sclk_period_ns} ns", checked
        edge_cycles = cycles_between(sclk, tf, tr)
        gaps = [y - x for x, y in zip(edge_cycles, edge_cycles[1:])]
        if len(gaps) != 15 or any(g != half for g in gaps):
            return False, f"burst {b}: SCLK half-period gaps {gaps}", checked
        if wrong_mode_control and case.params["mosi"][b] != 0x00:
            for wrong in MODES:
                if wrong.number == mode.number:
                    continue
                try:
                    wr = check_burst(
                        sclk.signal, mosi.signal, miso.signal, cs.signal,
                        wrong, F_CLK_HZ, t0=tf, t1=tr,
                    )
                    survived = wr.ok and wr.mosi_bytes == report.mosi_bytes
                except ValueError:
                    survived = False
                if survived:
                    return (
                        False,
                        f"burst {b}: round-tripped under wrong mode "
                        f"{wrong.number} (negative control failed to fail)",
                        checked,
                    )
            checked += 1
    return True, f"{nb} burst(s), mode {mode.number}, {2 * half} cycles/bit", checked


@cocotb.test()
async def test_spi_random_programs(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    failures = []
    for case in ft.generate(RECORDED_SEED, "spi", case_count()):
        _emit(case)
        CASES_RUN.append(case)
        caps = await run_spi(dut, case)
        ok, detail, checked = grade_spi(case, caps)
        dut._log.info(f"{ident(case)} params={case.params} -> {ok} ({detail})")
        _record(case, ok, detail, wrong_mode_controls_failed_as_required=checked)
        if not ok:
            failures.append(f"{ident(case)}: {detail}")
    assert not failures, "SPI random regression FAILED:\n" + "\n".join(failures)


# =======================================================================
# I2C
# =======================================================================


async def run_i2c(dut, case, uio_od=True):
    """Run a generated I2C write on the pad model. `uio_od=False` is the
    negative control: the same words with `WCTL UIO_OD` turned into a
    reserved no-op, so no pad is ever enabled."""
    program = _assemble(case)
    mode = _GRADE[case.params["grade"]]
    run_cycles = program.total_cycles + I2C_CAPTURE_MARGIN
    ack_falls = {9} if case.params["ack_address"] else set()
    words = program.words if uio_od else without_uio_od(program.words)
    caps, pads = await run_i2c_on_pads(
        dut, ident(case), words, run_cycles, ack_falls,
        expect_open_drain=uio_od,
    )
    if not uio_od:
        assert pads.oe_seen == 0, f"{ident(case)}: pads enabled without UIO_OD"
    return mode, caps


def grade_i2c(dut, case, mode, caps):
    try:
        _scl, _sda, report = grade_transfer(caps, mode)
    except ValueError as exc:
        return False, f"model rejected: {exc}"
    if not report.ok:
        return False, f"violations {report.violations}"
    p = case.params
    want_data = [p["data"]] if p["ack_address"] else []
    want_acks = [True, False] if p["ack_address"] else [False]
    if (report.address, report.read_bit) != (p["address"], False):
        return False, f"decoded address 0x{report.address:02x} R={report.read_bit}"
    if report.data_bytes != want_data or report.acks != want_acks:
        return False, f"data {report.data_bytes} acks {report.acks}"
    # Budgets in ns, with an absolute tolerance: sim times are float ns,
    # so late in a long run an exact `==` can miss by ~1e-9 ns (seen at
    # index 56 of a 60-case opt-in sweep with the committed bench's exact
    # comparison). 1e-3 ns is 5e-5 of a cycle.
    m = report.measurements
    hd_key = next((k for k in m if k.startswith("t_HD;STA@")), None)
    wanted = {
        "t_LOW(min)": mode.low_ns,
        "t_HIGH(min)": mode.high_ns,
        hd_key: mode.t_hd_sta * CLK_PERIOD_NS,
        "t_SU;STO": mode.t_su_sto * CLK_PERIOD_NS,
    }
    for key, want in wanted.items():
        if key is None or key not in m or abs(m[key] - want) > TIME_TOL_NS:
            return False, f"budget: {key} measured {m.get(key)} ns, wanted {want} ns"
    return True, f"{mode.name} 0x{p['address']:02x} data={want_data}"


@cocotb.test()
async def test_i2c_random_programs(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    failures = []
    for case in ft.generate(RECORDED_SEED, "i2c", case_count()):
        _emit(case)
        CASES_RUN.append(case)
        mode, caps = await run_i2c(dut, case)
        ok, detail = grade_i2c(dut, case, mode, caps)
        dut._log.info(f"{ident(case)} params={case.params} -> {ok} ({detail})")
        _record(case, ok, detail)
        if not ok:
            failures.append(f"{ident(case)}: {detail}")
    assert not failures, "I2C random regression FAILED:\n" + "\n".join(failures)


# =======================================================================
# I2C write -> repeated START -> controller read, with peripheral clock
# stretching (issue #104)
# =======================================================================

I2C_RD_CAPTURE_CLOCKS = 40  # SCL clocks incl. margin (the directed bench's)
#: A poll pass is IN, AND, BZ: how late the firmware can notice SCL high.
POLL_PASS_CYCLES = 3
#: Tolerance on how long a stretched low lasts relative to the scheduled
#: hold (the peripheral samples the fall one edge late).
STRETCH_LOW_TOL = 3
_REF_INTERVALS = {}  # grade -> (SCL interval list in ns) of an unstretched run


def _rd_mode(case):
    return "fast" if case.params["grade"] == "i2c_fast" else "std"


def rd_budget(case):
    return gen_i2c_sr.MODES[_rd_mode(case)]


def rd_run_cycles(case):
    """Bounded capture: the full unstretched transfer plus every scheduled
    hold plus a margin. A program that has not finished by then is graded
    as incomplete, never waited for."""
    b = rd_budget(case)
    extra = 0 if not case.params.get("poll", True) else gen_i2c_sr.POLL_EXTRA
    holds = sum(st["hold_cycles"] for st in case.params["stretch"])
    return (
        I2C_RD_CAPTURE_CLOCKS * (b["L"] + b["H"] + extra + 8)
        + 2 * (b["SUSTA"] + b["HD"] + b["SUSTO"])
        + 700 + holds + I2C_CAPTURE_MARGIN
    )


def rd_driver_args(case, unstretched=False):
    sched = ft.i2c_rd_schedule(case)
    stretches = {} if unstretched else {int(k): v for k, v in sched["stretches"].items()}
    return (
        set(sched["ack_falls"]),
        {int(k): v for k, v in sched["read_bits"].items()},
        stretches,
    )


async def run_i2c_rd(dut, case, unstretched=False, cycles=None, uio_od=True):
    """Run a generated write/Sr/read program on the pad model, with the
    case's own peripheral schedule. `uio_od=False`: see `run_i2c`."""
    program = _assemble(case)
    ack, bits, stretches = rd_driver_args(case, unstretched)
    cycles = rd_run_cycles(case) if cycles is None else cycles
    words = program.words if uio_od else without_uio_od(program.words)
    caps, uo, pads = await run_i2c_rd_on_pads(
        dut, ident(case), words, cycles, ack, bits, stretches,
        expect_open_drain=uio_od,
    )
    if not uio_od:
        assert pads.oe_seen == 0, f"{ident(case)}: pads enabled without UIO_OD"
    return caps, uo  # uo: the DUT's observable result


def _scl_intervals(scl):
    ts = [t for (t, _v) in scl.transitions]
    return [round(b - a, 3) for a, b in zip(ts, ts[1:])]


def _rd_decode_ok(case, report, uo):
    """Model-decoded transfer vs. what the template transmits and what the
    peripheral drove; returns an error string or None."""
    p = case.params
    want = [p["pointer"], ((p["address"] << 1) | 1), p["read_byte"]]
    if (report.address, report.read_bit) != (p["address"], False):
        return f"decoded address 0x{report.address:02x} R={report.read_bit}"
    if report.data_bytes != want:
        return f"data {report.data_bytes} != {want}"
    if report.acks != [True, True, True, False]:
        return f"acks {report.acks} (last slot must be the controller NACK)"
    if not any(k.startswith("t_SU;STO") for k in report.measurements):
        return "no STOP measured: transfer incomplete within the bounded capture"
    if uo != p["read_byte"]:
        return f"uo_out 0x{uo:02x} != received byte 0x{p['read_byte']:02x}"
    return None


async def rd_reference(dut, case):
    """Unstretched SCL intervals for this grade (SCL timing never depends
    on the address/pointer/read data), measured on the DUT once per grade
    and itself graded cycle-exact (the polling program's budget + 2 on
    rise phases)."""
    grade = case.params["grade"]
    if grade not in _REF_INTERVALS:
        caps, uo = await run_i2c_rd(dut, case, unstretched=True)
        scl, sda = caps["scl"].signal, caps["sda"].signal
        mode = _GRADE[grade]
        rep = check_transfer(scl, sda, fast_mode=mode.fast_mode)
        err = _rd_decode_ok(case, rep, uo)
        assert rep.ok and err is None and rep.stretched_clocks == 0, (
            f"unstretched reference for {grade} failed: {rep} {err}"
        )
        b = rd_budget(case)
        e = gen_i2c_sr.POLL_EXTRA
        m = rep.measurements
        want = {"t_LOW(min)": b["L"], "t_HIGH(min)": b["H"] + e,
                "t_SU;STO": b["SUSTO"] + e}
        for key, cyc in want.items():
            assert abs(m[key] - cyc * CLK_PERIOD_NS) <= TIME_TOL_NS, (
                f"{grade} unstretched {key}={m[key]} ns, want {cyc} cycles"
            )
        _REF_INTERVALS[grade] = _scl_intervals(scl)
    return _REF_INTERVALS[grade]


def grade_i2c_rd(case, caps, uo, ref):
    """Returns (ok, detail). The model grades the transfer; non-stretched
    SCL phases must be byte-identical (to the picosecond) to the
    unstretched run's. Only the stretched low and its following high are
    exempt: how long a polling firmware takes to notice the release is a
    handshake interval, not a determinism claim."""
    mode = _GRADE[case.params["grade"]]
    scl, sda = caps["scl"].signal, caps["sda"].signal
    try:
        report = check_transfer(scl, sda, fast_mode=mode.fast_mode)
    except ValueError as exc:
        return False, f"model rejected: {exc}"
    if not report.ok:
        return False, f"violations {report.violations}"
    err = _rd_decode_ok(case, report, uo)
    if err:
        return False, err
    b = rd_budget(case)
    cyc = CLK_PERIOD_NS
    got = _scl_intervals(scl)
    if len(got) != len(ref):
        return False, f"{len(got)} SCL intervals, unstretched run has {len(ref)}"
    allowed, notes = set(), []
    # Intervals alternate; if the line's first recorded transition is a RISE
    # (SCL was low out of reset), interval 0 is that reset-low and the n-th
    # fall starts interval 2(n-1)+1.
    lead = 1 if scl.transitions[0][1] == 1 else 0
    for st in case.params["stretch"]:
        i = 2 * (st["fall"] - 1) + lead  # n-th fall starts a low interval
        low_cycles = got[i] / cyc
        if abs(low_cycles - st["hold_cycles"]) > STRETCH_LOW_TOL:
            return False, (
                f"stretch at fall {st['fall']}: SCL low lasted "
                f"{low_cycles:.1f} cycles, scheduled hold {st['hold_cycles']}"
            )
        allowed.add(i)
        if i + 1 < len(got):  # the STOP's high is the capture's last level
            high_cycles = got[i + 1] / cyc
            if not (b["H"] <= high_cycles <= ref[i + 1] / cyc + POLL_PASS_CYCLES):
                return False, (
                    f"high after the stretch at fall {st['fall']} lasted "
                    f"{high_cycles:.1f} cycles (budget {b['H']})"
                )
            allowed.add(i + 1)
        notes.append(f"{st['site']}:{st['duration_class']}={low_cycles:.0f}cy")
    bad = [i for i, (a, r_) in enumerate(zip(got, ref)) if a != r_ and i not in allowed]
    if bad:
        return False, f"non-stretched SCL intervals {bad} differ from the unstretched run"
    if abs(report.measurements["t_LOW(min)"] - b["L"] * cyc) > TIME_TOL_NS:
        return False, f"t_LOW(min) {report.measurements['t_LOW(min)']} ns"
    return True, (
        f"{mode.name} 0x{case.params['address']:02x} read "
        f"0x{case.params['read_byte']:02x}; stretches {notes}; "
        f"{len(got) - len(allowed)} of {len(got)} SCL intervals identical"
    )


@cocotb.test()
async def test_i2c_rd_random_programs(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    failures = []
    for case in ft.generate(RECORDED_SEED, "i2c_rd", case_count()):
        _emit(case)
        CASES_RUN.append(case)
        ref = await rd_reference(dut, case)
        caps, uo = await run_i2c_rd(dut, case)
        ok, detail = grade_i2c_rd(case, caps, uo, ref)
        dut._log.info(f"{ident(case)} params={case.params} -> {ok} ({detail})")
        _record(case, ok, detail)
        if not ok:
            failures.append(f"{ident(case)}: {detail}")
    assert not failures, "I2C read/stretch random regression FAILED:\n" + "\n".join(
        failures
    )


# =======================================================================
# Negative controls: mutated templates, run on the DUT, must FAIL
# =======================================================================

NEGATIVE_CONTROLS = []


@cocotb.test()
async def test_negative_controls_mutated_templates_fail(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    # UART: the bit period is 3 cycles short (a 3% timing error). The
    # payload is forced to 0x5A: the model measures drift on the frame's
    # last edge, so an all-ones/all-zeros frame has no late edge to
    # measure (recorded as a finding; the random cases' cycle-offset
    # check still covers those).
    case = ft.gen_uart(RECORDED_SEED, 1, mistime_delta=-3, force_payloads=[0x5A])
    tx = await run_uart(dut, case)
    ok, detail = grade_uart(case, tx)
    NEGATIVE_CONTROLS.append(
        {"name": "uart_bit_period_minus_3", "params": case.params,
         "model_verdict": "FAIL" if not ok else "PASS", "detail": detail}
    )
    dut._log.info(f"negative control UART mistimed: ok={ok} ({detail})")
    assert not ok, "NEGATIVE CONTROL FAILED TO FAIL: mistimed UART passed"

    # UART, issue #97: a back-to-back stream of 0xFF frames whose data-bit
    # periods are 3 cycles long / short. 0xFF has no in-frame edge after
    # bit 1 and the start and first data bit are nominal, so the last-edge
    # drift and the cycle edge offsets are blind to the slow stream; only
    # the frame-pitch check can fail it.
    for delta in (3, -3):
        case = ft.gen_uart(
            RECORDED_SEED, 1, mistime_delta=delta,
            force_payloads=[0xFF, 0xFF, 0xFF], back_to_back=True,
        )
        tx = await run_uart(dut, case)
        ok, detail = grade_uart(case, tx)
        baud = 1e9 / (case.params["period"] * CLK_PERIOD_NS)
        reports = UartDecoder(baud, back_to_back=True).decode(tx.signal)
        last_edge = [round(r.drift_pct, 3) for r in reports]
        pitch = [
            None if r.pitch_drift_pct is None else round(r.pitch_drift_pct, 3)
            for r in reports
        ]
        name = f"uart_0xff_stream_bit_period_{'plus' if delta > 0 else 'minus'}_3"
        NEGATIVE_CONTROLS.append(
            {"name": name, "params": case.params,
             "model_verdict": "FAIL" if not ok else "PASS", "detail": detail,
             "last_edge_drift_pct": last_edge, "pitch_drift_pct": pitch}
        )
        dut._log.info(
            f"negative control {name}: ok={ok} ({detail}); last-edge drift "
            f"{last_edge} %, pitch {pitch} %"
        )
        assert not ok and "pitch" in detail, (
            f"NEGATIVE CONTROL FAILED TO FAIL: {name} passed ({detail})"
        )
        assert [r.data for r in reports] == [0xFF, 0xFF, 0xFF], reports
        if delta > 0:
            # The pre-#97 measurement alone passes this stream.
            assert all(r.drift_pct <= MAX_FRAME_DRIFT_PCT for r in reports), (
                f"expected the last-edge drift to be blind: {last_edge}"
            )

    # SPI: drive the wrong CPOL idle level for the declared mode.
    case = ft.gen_spi(RECORDED_SEED, 0, flip_idle=1)
    caps = await run_spi(dut, case)
    ok, detail, _ = grade_spi(case, caps, wrong_mode_control=False)
    NEGATIVE_CONTROLS.append(
        {"name": "spi_wrong_cpol_idle", "params": case.params,
         "model_verdict": "FAIL" if not ok else "PASS", "detail": detail}
    )
    dut._log.info(f"negative control SPI wrong idle: ok={ok} ({detail})")
    assert not ok, "NEGATIVE CONTROL FAILED TO FAIL: wrong-CPOL SPI passed"

    # I2C: data-clock low phase 30 cycles shorter (under the Table 10 floor in
    # both grades: Fast 65 -> 35, Standard 258 -> 228 < 235), both grades (indices 0 / 1 are fast / std).
    for index in (0, 1):
        case = ft.gen_i2c(RECORDED_SEED, index, mistime_low_delta=-30)
        case.params["ack_address"] = True
        mode, caps = await run_i2c(dut, case)
        try:
            _s, _d, report = grade_transfer(caps, mode)
            low = [v for v in report.violations if v.startswith("t_LOW")]
            failed = (not report.ok) and bool(low)
            detail = f"violations {report.violations[:2]}"
        except ValueError as exc:
            failed, detail = True, f"model rejected: {exc}"
        NEGATIVE_CONTROLS.append(
            {"name": f"{mode.name}_low_phase_minus_30", "params": case.params,
             "model_verdict": "FAIL" if failed else "PASS", "detail": detail}
        )
        dut._log.info(f"negative control {mode.name} short t_LOW: {detail}")
        assert failed, (
            f"NEGATIVE CONTROL FAILED TO FAIL: {mode.name} program with "
            "short t_LOW passed the model"
        )

    # I2C on the pads (issue #136): a generated program whose UIO_OD is
    # left at reset enables no pad, so the lines never move and the model
    # must find no transfer. Both grades; the peripheral would ACK.
    for index in (0, 1):
        case = ft.gen_i2c(RECORDED_SEED, index)
        case.params["ack_address"] = True
        mode, caps = await run_i2c(dut, case, uio_od=False)
        ok, detail = grade_i2c(dut, case, mode, caps)
        NEGATIVE_CONTROLS.append(
            {"name": f"{mode.name}_uio_od_left_at_reset", "params": case.params,
             "model_verdict": "FAIL" if not ok else "PASS", "detail": detail}
        )
        dut._log.info(f"negative control {mode.name} UIO_OD at reset: {detail}")
        assert not ok, (
            f"NEGATIVE CONTROL FAILED TO FAIL: {mode.name} program passed "
            "with UIO_OD left at reset (no pad enabled)"
        )


@cocotb.test()
async def test_i2c_rd_negative_controls(dut):
    """(1) A selected stretch schedule applied to the NON-polling sibling
    of a generated program must not yield a conformant, correctly
    received transfer -- the polling is load-bearing and the driver
    bites. One schedule per grade: the first generated case with a
    medium or long stretch at the read clock. (2) An incomplete capture
    (cut short) must fail, naming the case."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    cases = ft.generate(RECORDED_SEED, "i2c_rd", ft.DEFAULT_CASES)
    for grade in ft.I2C_GRADES:
        pick = next(
            c for c in cases
            if c.params["grade"] == grade and any(
                st["site"] == "read_clock" and st["duration_class"] != "short"
                for st in c.params["stretch"]
            )
        )
        control = ft.gen_i2c_rd(RECORDED_SEED, pick.index, poll=False)
        assert control.params["stretch"] == pick.params["stretch"]
        ref = await rd_reference(dut, pick)
        caps, uo = await run_i2c_rd(dut, control)
        ok, detail = grade_i2c_rd(control, caps, uo, ref)
        NEGATIVE_CONTROLS.append(
            {"name": f"{grade}_non_polling_under_stretch", "params": control.params,
             "model_verdict": "FAIL" if not ok else "PASS", "detail": detail}
        )
        dut._log.info(f"negative control {ident(control)} non-polling: {ok} ({detail})")
        assert not ok, (
            f"NEGATIVE CONTROL FAILED TO FAIL: {ident(control)} non-polling "
            "program survived the stretch schedule"
        )

        # the same schedule on the polling program passes (the control is
        # the program, not a broken schedule)
        caps, uo = await run_i2c_rd(dut, pick)
        ok, detail = grade_i2c_rd(pick, caps, uo, ref)
        assert ok, f"{ident(pick)}: polling twin failed: {detail}"

        # incomplete capture: cut off mid-transfer -> must fail
        bud = rd_budget(pick)
        cut_cycles = 20 * (bud["L"] + bud["H"])
        caps, uo = await run_i2c_rd(dut, pick, cycles=cut_cycles)
        ok_cut, detail_cut = grade_i2c_rd(pick, caps, uo, ref)
        NEGATIVE_CONTROLS.append(
            {"name": f"{grade}_truncated_capture", "params": pick.params,
             "model_verdict": "FAIL" if not ok_cut else "PASS", "detail": detail_cut}
        )
        assert not ok_cut, (
            f"NEGATIVE CONTROL FAILED TO FAIL: {ident(pick)} truncated capture "
            "was graded complete"
        )

        # UIO_OD left at reset (issue #136): the polling program enables
        # no pad, reads the pulled-up SCL back as "released", and runs to
        # the end without having moved a line -> must fail.
        caps, uo = await run_i2c_rd(dut, pick, uio_od=False)
        ok_od, detail_od = grade_i2c_rd(pick, caps, uo, ref)
        NEGATIVE_CONTROLS.append(
            {"name": f"{grade}_rd_uio_od_left_at_reset", "params": pick.params,
             "model_verdict": "FAIL" if not ok_od else "PASS", "detail": detail_od}
        )
        dut._log.info(
            f"negative control {ident(pick)} UIO_OD at reset: {ok_od} ({detail_od})"
        )
        assert not ok_od, (
            f"NEGATIVE CONTROL FAILED TO FAIL: {ident(pick)} passed with "
            "UIO_OD left at reset (no pad enabled)"
        )


# =======================================================================
# UART RX legs (issue #192). They run LAST (before the report): the
# 5,208-cycle/bit profile advances simulated time by tens of milliseconds, and
# the SPI / UART models look for edges with a 1e-9 ns look-back that float64
# absolute times past ~1e7 ns cannot resolve. Ordering them after the
# existing legs leaves those legs' absolute times, and so their records,
# unchanged.
# =======================================================================


@cocotb.test()
async def test_uart_rx_random_programs(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    failures = []
    for case in ft.generate(RECORDED_SEED, "uart_rx", case_count()):
        _emit(case)
        CASES_RUN.append(case)
        frames, results, line = await run_uart_rx(dut, case)
        ok, detail, _fails = grade_uart_rx(case, frames, results, line)
        dut._log.info(f"{ident(case)} params={case.params} -> {ok} ({detail})")
        _record(case, ok, detail)
        if not ok:
            failures.append(f"{ident(case)}: {detail}")
    assert not failures, "UART RX random regression FAILED:\n" + "\n".join(failures)


@cocotb.test()
async def test_uart_rx_negative_controls(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    # UART RX (issue #192): (1) the committed 50-cycle receiver with its first
    # inter-sample WAIT stretched by 2 cycles must be rejected for sample
    # spacing; (2) a sender 10 % off per bit, both directions, must be
    # rejected for a wrong byte / out-of-bit sample (the receiver tolerates
    # +-2 %, not +-10 %).
    probes = [0x80, 0x40, 0x01, 0xA5]
    rx_controls = [
        ("uart_rx_wait_plus_2", ft.gen_uart_rx(RECORDED_SEED, 0, mistime_wait_delta=2),
         ("sample spacing",)),
        ("uart_rx_sender_rate_plus_10pct",
         ft.gen_uart_rx(RECORDED_SEED, 0, force_frames=probes, force_scale=1.10),
         ("received 0x", "of its bit")),
        ("uart_rx_sender_rate_minus_10pct",
         ft.gen_uart_rx(RECORDED_SEED, 0, force_frames=probes, force_scale=0.90),
         ("received 0x", "of its bit")),
    ]
    for name, case, reasons in rx_controls:
        assert case.params["rx_pin"] == "ui_in[1]"
        frames, results, line = await run_uart_rx(dut, case)
        ok, detail, fails = grade_uart_rx(case, frames, results, line)
        intended = [m for m in fails if any(r in m for r in reasons)]
        NEGATIVE_CONTROLS.append(
            {"name": name, "protocol": "uart_rx", "params": case.params,
             "model_verdict": "FAIL" if not ok else "PASS",
             "intended_reason": list(reasons),
             "intended_reason_seen": bool(intended), "detail": detail}
        )
        dut._log.info(f"negative control {name}: ok={ok} intended={bool(intended)} ({detail})")
        assert not ok, f"NEGATIVE CONTROL FAILED TO FAIL: {name} passed ({detail})"
        assert intended, (
            f"NEGATIVE CONTROL {name} was rejected, but not for the intended "
            f"reason {reasons}: {detail}"
        )


@cocotb.test()
async def test_zz_write_report(dut):
    """Write verdicts.json / coverage.json when an artifact dir is named,
    and log the cover-bin tables either way."""
    cov = ft.coverage(CASES_RUN)
    for table, bins in cov.items():
        unhit = sorted(b for b, n in bins.items() if n == 0)
        dut._log.info(
            f"COVER {table}: {sum(1 for n in bins.values() if n)}/{len(bins)} "
            f"hit; unhit={unhit}"
        )
    if _ARTIFACT_DIR:
        out = Path(_ARTIFACT_DIR)
        out.mkdir(parents=True, exist_ok=True)
        doc = {
            "seed": RECORDED_SEED,
            "cases_per_protocol": case_count(),
            "verdicts": VERDICTS,
            "negative_controls": NEGATIVE_CONTROLS,
        }
        (out / "verdicts.json").write_text(
            json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        (out / "coverage.json").write_text(
            json.dumps(cov, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    assert VERDICTS, "no programs were graded"
