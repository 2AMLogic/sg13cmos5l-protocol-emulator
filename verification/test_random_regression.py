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
program whose bit period is 3 cycles short, an SPI program driving the
wrong CPOL idle level, and I2C programs whose data-clock low phase is 10
cycles under the Table 10 floor -- must each be FAILED by the model; and
every SPI burst with a non-zero MOSI byte is re-graded under the three
wrong modes and must fail.

Like its siblings this file is *input* to `klt functional-verification`,
not a pytest module. Directions not covered: UART RX and I2C read (no
firmware exists for them yet; deferred, not implied).
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock

_HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()


def _find_repo_root() -> Path:
    candidates = [_HERE, Path.cwd()]
    for start in candidates:
        for probe in [start, *start.parents]:
            if (probe / "firmware" / "tools" / "asm.py").exists() and (
                probe / "spec" / "target-spec.md"
            ).exists():
                return probe
    raise RuntimeError("cannot locate the repo root (needed for firmware/)")


REPO_ROOT = _find_repo_root()
sys.path.insert(0, str(REPO_ROOT / "verification"))
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402
import firmware_templates as ft  # noqa: E402

# Reused (functions only; importing registers no sibling tests).
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart import (  # noqa: E402
    capture_pin_bits,
    cycle_at_time,
    expected_edge_offsets,
)
from test_firmware_spi import burst_windows, cycles_between, drive_miso  # noqa: E402
from test_firmware_i2c import (  # noqa: E402
    FAST,
    STD,
    SCL_BIT,
    SCL_PIN,
    SDA_BIT,
    SDA_PIN,
    drive_peripheral,
    grade_transfer,
)
from reference_models.spi import MODES, check_burst  # noqa: E402
from reference_models.uart import UartDecoder  # noqa: E402

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
    decoder = UartDecoder(baud)
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
            return False, f"frame {n}: row-10 drift {report.drift_pct:.3f}%"
        start = cycle_at_time(tx, report.t_start)
        edges = [
            c
            for c in tx.transition_cycles
            if start <= c <= start + 10 * period
        ]
        offsets = [c - start for c in edges]
        wanted = [k * period for k in expected_edge_offsets(payload)]
        if offsets != wanted:
            return False, f"frame {n}: edge offsets {offsets} != {wanted} cycles"
    return True, f"{len(want)} frame(s) @ {period} cycles/bit"


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
# SPI
# =======================================================================

SPI_PINS = {"cs": ("uo_out", 0), "sclk": ("uo_out", 1), "mosi": ("uo_out", 2),
            "miso": ("uio_in", 0)}


async def run_spi(dut, case):
    program = _assemble(case)
    mode = MODES[case.params["mode"]]
    await load_program(dut, program.words)
    run_cycles = program.total_cycles + SPI_CAPTURE_MARGIN
    driver = cocotb.start_soon(drive_miso(dut, mode, case.params["miso"], run_cycles))
    caps = await capture_pin_bits(dut, SPI_PINS, run_cycles)
    await driver
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


async def run_i2c(dut, case):
    program = _assemble(case)
    mode = _GRADE[case.params["grade"]]
    await load_program(dut, program.words)
    run_cycles = program.total_cycles + I2C_CAPTURE_MARGIN
    ack_falls = {9} if case.params["ack_address"] else set()
    driver = cocotb.start_soon(drive_peripheral(dut, ack_falls))
    caps = await capture_pin_bits(
        dut,
        {
            "ctl_scl": (SCL_PIN, SCL_BIT),
            "ctl_sda": (SDA_PIN, SDA_BIT),
            "per_scl": ("uio_in", SCL_BIT),
            "per_sda": ("uio_in", 7),
        },
        run_cycles,
    )
    driver.kill()
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

    # I2C: data-clock low phase 10 cycles under the Table 10 floor, both
    # grades (indices 0 / 1 are fast / std).
    for index in (0, 1):
        case = ft.gen_i2c(RECORDED_SEED, index, mistime_low_delta=-10)
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
            {"name": f"{mode.name}_low_phase_minus_10", "params": case.params,
             "model_verdict": "FAIL" if failed else "PASS", "detail": detail}
        )
        dut._log.info(f"negative control {mode.name} short t_LOW: {detail}")
        assert failed, (
            f"NEGATIVE CONTROL FAILED TO FAIL: {mode.name} program with "
            "short t_LOW passed the model"
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
