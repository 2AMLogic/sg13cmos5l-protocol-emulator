"""Routed-delay alignment for the protocol firmware benches (issue #217).

`flow/run-post-layout-sdf.sh --suite protocols` runs the committed UART TX,
SPI (modes 0-3) and I2C (write / repeated START / read / clock stretch)
benches, byte-unchanged, against the routed netlist with SDF back-annotated
delays. Each bench is reached through a thin wrapper module
(`sdf_protocol_uart_tx`, `sdf_protocol_spi`, `sdf_protocol_i2c_sr`) that
calls `install()` and `register()` from here. Nothing in this module runs
unless such a wrapper is the testbench module a request names, and no RTL
request names one.

What the benches do at zero delay, and why that is a race once delay exists
--------------------------------------------------------------------------
Every protocol bench reaches the clock through the name `RisingEdge` in its
own module namespace, in exactly two kinds of place:

- the per-cycle pin capture (`test_firmware_uart.capture_pin_bits`, which
  the SPI and I2C benches import): edge, `ReadOnly`, read every graded pin,
  `Timer(1 ns)`;
- the reactive peripherals (`drive_miso` in the SPI bench,
  `drive_peripheral_sr` in the I2C bench): edge, `ReadOnly`, read the bus
  lines, `Timer(1 ns)`, drive.

The serial load (`test_protocol_emulator.load_program`) reaches it through
that module's `RisingEdge` / `ClockCycles`. At zero delay all three read the
value the edge just launched and drive what the next edge captures. Against
the routed netlist an output reaches its pin some hundreds of ps after the
`clk` pin edge, so a read *at* the edge sees the previous cycle, and an input
changed at the edge can race the clock tree.

The alignment, and where each number comes from
-----------------------------------------------
The three `PE_ALIGN_*` numbers are the ones `flow/run-post-layout-sdf.sh`
reads from the gds run's own SDC (see `sdf_alignment.py`, whose
`read_alignment()` this module reuses rather than re-deriving):

- the **load** is aligned by importing `sdf_alignment`, which rebinds
  `test_protocol_emulator`'s `RisingEdge` / `ClockCycles` so every load-phase
  stimulus is applied the SDC input delay (the *drive offset*) after the
  pin edge -- the same alignment the core suite runs under;
- the **peripherals** drive at that same drive offset: their module's
  `RisingEdge` is rebound to "edge, then wait `drive - 1 ns`", so the
  bench's own `Timer(1 ns)` lands each drive exactly on the drive offset;
- the **capture** samples at that same *observe point* (`drive - 1 ns`
  after the edge), i.e. where the peripherals read the bus. It keeps the
  zero-delay bench's within-cycle order: a peripheral drive made in cycle k
  is seen by the capture of cycle k+1, exactly as at zero delay.

The observe point is EARLIER than the SDC sample point (`period - output
delay`). That is deliberate and it is the strict direction: the benches'
peripherals are same-cycle reactive (a zero-latency partner), which no SDC
output delay describes, so instead of assuming outputs are valid there, the
harness *checks* it. While every capture runs, a monitor timestamps every
change of `uo_out`, `uio_out` and `uio_oe` against the last `clk` pin edge;
any change that is not strictly before the observe point fails the capture
(and the bench test with it), and the measured per-pin delays are written
to the per-run protocol report. An output that settles before the observe
point is settled at the later SDC sample point too, so a pass here is never
weaker than one sampled at the SDC point.

Cycle accounting versus pin delay
---------------------------------
Every captured transition is timestamped at the observe point of the cycle
it was seen in, i.e. one fixed offset after its launching edge. The
benches' timing assertions (bit periods, SCLK half-periods, I2C Table 10
phases, frame pitch) are therefore graded on instruction-cycle determinism
at the pins, exactly as at zero delay, and the reference models grade that
waveform independently. The post-route pin delay -- how long after the edge
each transition actually reached the pin -- is a separate measurement in
the report (`pin_events`), bounded by the observe point as above. The two
are never folded together.

Timing negative controls under routed delay
-------------------------------------------
Each bench's own controls run on the routed capture unchanged: UART
re-grades its captured waveform stretched 1.025x (row-10 drift must fail);
I2C re-grades its capture compressed 0.9x (t_LOW / f_SCL / t_SU;STA must
fail) and runs firmware with the repeated-START setup one cycle short on
the routed netlist (t_SU;STA must be the only violation). The SPI bench's
controls on the DUT capture are mode-based, and its only timing control is
synthetic, so this module adds one for SPI: every grading of a
DUT-captured burst that the model calls conformant is repeated with the
four lines compressed until the SCLK period is 0.9x the f_clk/4 ceiling,
and the model must name the ceiling violation (`SPI_CEILING_CONTROL`).
That covers both bursts of every mode (and any wrong-mode re-grading the
model happens to call conformant); the count is in the report and the
runner requires at least the eight golden bursts' worth, all failed.

Limits stated, not hidden
-------------------------
The SRAM macro still runs as the zero-delay FUNCTIONAL model (see
`flow/run-post-layout-sdf.sh`), and the uio pad model is zero-delay
(`verification/uio_pads.py`); this module changes neither.

Opt-in
------
With none of the `PE_ALIGN_*` variables set the wrappers register the bench
tests and patch nothing (the benches then run exactly as their RTL
requests do). With all three set, `install()` requires the drive offset to
be a whole number of ns and at least 2 ns (the benches timestamp in float
ns and drive 1 ns after their read), and every bench's own
`CLK_PERIOD_NS` to equal the SDC period: the benches grade nanoseconds at
that nominal, so a different period would re-grade, not re-time, them.

Environment: `PE_SDF_PROTOCOL_REPORT` names the JSON file the report is
written to (after import, after every capture, after every control); unset,
no report is written.
"""

from __future__ import annotations

import json
import os

from cocotb._decorators import Test, TestGenerator
from cocotb.simtime import get_sim_time
from cocotb.triggers import First, ReadOnly, Timer, ValueChange
from cocotb.triggers import RisingEdge as _RisingEdge

import sdf_alignment  # noqa: F401  (aligns test_protocol_emulator's load phase)

ENV_REPORT = "PE_SDF_PROTOCOL_REPORT"

#: The benches read in `ReadOnly`, then `await Timer(1, unit="ns")`, then
#: drive. The observe point is this much before the drive offset.
BENCH_READ_TO_DRIVE_PS = 1000

#: Top-level design outputs whose pin delay is measured and bounded.
MONITORED_OUTPUTS = ("uo_out", "uio_out", "uio_oe")

#: The SPI control's target: SCLK period at this fraction of the ceiling.
SPI_CEILING_CONTROL_FRACTION = 0.9
SPI_CEILING_CONTROL = "spi_ceiling_compressed"

#: At most this many contract violations are listed in the report.
MAX_LISTED_VIOLATIONS = 20

ALIGNMENT = sdf_alignment.ALIGNMENT


def _quiet_kill_warning() -> None:
    """Silence cocotb 2.1's "`task.kill()` is deprecated" warning, which
    the pad model (`uio_pads.UioPads.stop`) and the I2C bench emit.

    Why it matters under SDF only: klt's annotation gate scans the Icarus
    transcript for `SDF WARNING: <file>:<line>:` lines, and Icarus's buffered
    stdout can be spliced mid-line with cocotb's log output. A Python
    warning line carries its own `<path>:<line>:`, so a benign TIMINGCHECK
    warning spliced with it still has the diagnostic shape and is reported
    as a failed annotation (observed on the first routed SPI run of this
    harness; klayout-tools#2996). The warning is a deprecation notice about
    the bench's own stop call, not a simulation event; silencing it changes
    no behaviour.
    """
    import warnings

    warnings.filterwarnings(
        "ignore", message=r"`task\.kill\(\)` is deprecated", category=DeprecationWarning
    )


def observe_offset_ps(alignment) -> int:
    """The observe point after each pin edge, in ps, for an
    `(period, drive, sample)` alignment (all ps). Raises if the drive
    offset cannot carry the benches' 1 ns read-to-drive step."""
    period, drive, sample = alignment
    if drive % 1000:
        raise RuntimeError(
            f"sdf_protocol_alignment: drive offset {drive} ps is not a whole ns; "
            "the protocol benches timestamp in float ns and would re-grade rounding"
        )
    observe = drive - BENCH_READ_TO_DRIVE_PS
    if observe < 1000:
        raise RuntimeError(
            f"sdf_protocol_alignment: drive offset {drive} ps leaves no observe point "
            f"before the benches' {BENCH_READ_TO_DRIVE_PS} ps read-to-drive step"
        )
    if not observe < sample < period:
        raise RuntimeError(
            f"sdf_protocol_alignment: need observe < sample < period, got "
            f"{observe}/{sample}/{period} ps"
        )
    return observe


class ProtocolReport:
    """What one protocol run measured, written as JSON to `ENV_REPORT`."""

    def __init__(self, protocol: str, bench: str, alignment, observe_ps):
        self.doc = {
            "schema": "pe.sdf_protocol_report/1",
            "protocol": protocol,
            "bench_module": bench,
            "alignment_ps": None if alignment is None else {
                "clock_period": alignment[0],
                "drive_offset": alignment[1],
                "sample_offset": alignment[2],
                "observe_offset": observe_ps,
            },
            "captures": 0,
            "captured_cycles": 0,
            "pin_events": {
                name: {"count": 0, "zero_delay": 0, "min_delay_ps": None, "max_delay_ps": None}
                for name in MONITORED_OUTPUTS
            },
            "contract_violation_count": 0,
            "contract_violations": [],
            "timing_controls": {},
        }
        self.path = os.environ.get(ENV_REPORT) or None

    def add_capture(self, cycles: int, monitor: "PinDelayMonitor") -> None:
        self.doc["captures"] += 1
        self.doc["captured_cycles"] += cycles
        for name, (count, zero, lo, hi) in monitor.stats.items():
            entry = self.doc["pin_events"][name]
            entry["count"] += count
            entry["zero_delay"] += zero
            if lo is not None:
                entry["min_delay_ps"] = lo if entry["min_delay_ps"] is None else min(entry["min_delay_ps"], lo)
                entry["max_delay_ps"] = hi if entry["max_delay_ps"] is None else max(entry["max_delay_ps"], hi)
        self.doc["contract_violation_count"] += len(monitor.violations)
        room = MAX_LISTED_VIOLATIONS - len(self.doc["contract_violations"])
        if room > 0:
            self.doc["contract_violations"].extend(monitor.violations[:room])
        self.write()

    def add_control(self, name: str, failed_as_required: bool, detail: str) -> None:
        entry = self.doc["timing_controls"].setdefault(
            name, {"run": 0, "failed_as_required": 0, "last": None}
        )
        entry["run"] += 1
        entry["failed_as_required"] += int(failed_as_required)
        entry["last"] = detail
        self.write()

    def write(self) -> None:
        if not self.path:
            return
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.doc, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, self.path)


class PinDelayMonitor:
    """Timestamps every change of the monitored outputs against the last
    `clk` pin edge while it runs. A change that is not strictly before the
    observe point -- or that has no observed edge before it -- is a
    contract violation."""

    def __init__(self, dut, observe_ps: int, sample_ps: int):
        self.dut = dut
        self.observe_ps = observe_ps
        self.sample_ps = sample_ps
        self.last_edge_ps = None
        #: name -> (count, zero-delay count, min delay ps, max delay ps)
        self.stats = {name: (0, 0, None, None) for name in MONITORED_OUTPUTS}
        self.violations = []
        self._tasks = []
        self._stopped = False

    def start(self):
        import cocotb

        self._tasks = [
            cocotb.start_soon(self._edges()),
            cocotb.start_soon(self._watch()),
        ]
        return self

    def stop(self) -> None:
        # A flag, not `task.kill()`: kill is deprecated in cocotb 2.1 and its
        # warning must not reach the transcript (see `_quiet_kill_warning`).
        # A stopped task records nothing and returns at its next wake-up;
        # cocotb ends any still parked when the test ends.
        self._stopped = True
        self._tasks = []

    async def _edges(self):
        while True:
            await _RisingEdge(self.dut.clk)
            if self._stopped:
                return
            self.last_edge_ps = round(get_sim_time("ps"))

    def _record(self, name: str, now_ps: int) -> None:
        count, zero, lo, hi = self.stats[name]
        if self.last_edge_ps is None:
            self.violations.append(
                f"{name} changed at {now_ps} ps with no clk edge observed before it in this capture"
            )
            self.stats[name] = (count + 1, zero, lo, hi)
            return
        delay = now_ps - self.last_edge_ps
        lo = delay if lo is None else min(lo, delay)
        hi = delay if hi is None else max(hi, delay)
        self.stats[name] = (count + 1, zero + (delay == 0), lo, hi)
        if delay >= self.observe_ps:
            where = "after the SDC sample point" if delay >= self.sample_ps else "before the SDC sample point"
            self.violations.append(
                f"{name} changed {delay} ps after the clk edge at {self.last_edge_ps} ps: "
                f"not before the observe point ({self.observe_ps} ps; {where})"
            )

    async def _watch(self):
        dut = self.dut
        previous = {name: str(getattr(dut, name).value) for name in MONITORED_OUTPUTS}
        while True:
            await First(*(ValueChange(getattr(dut, name)) for name in MONITORED_OUTPUTS))
            # End of this time step: every delta has run, and a clk edge in
            # the same step has already been recorded by `_edges`.
            await ReadOnly()
            if self._stopped:
                return
            now = round(get_sim_time("ps"))
            for name in MONITORED_OUTPUTS:
                value = str(getattr(dut, name).value)
                if value != previous[name]:
                    previous[name] = value
                    self._record(name, now)


def _scaled(signal, factor):
    from reference_models.waveform import Signal

    clone = Signal(signal.initial, name=f"{signal.name}*{factor:.6g}")
    clone.transitions = [(t * factor, v) for (t, v) in signal.transitions]
    return clone


def install(protocol: str, bench, edge_modules, capture_modules, capture_source,
            period_modules, spi_check_burst: bool = False) -> ProtocolReport:
    """Patch the named bench modules for routed-delay alignment.

    `edge_modules`: modules whose `RisingEdge` is rebound to the observe
    point (the capture's home module and the bench with a reactive
    peripheral). `capture_modules`: modules whose `capture_pin_bits` name
    is rebound to the monitored capture. `capture_source`: the module that
    defines the original `capture_pin_bits`. `period_modules`: modules whose
    `CLK_PERIOD_NS` must equal the SDC period. `spi_check_burst`: add the
    SPI ceiling control to `bench.check_burst`.

    Returns the run's report. With alignment off nothing is patched."""
    if ALIGNMENT is None:
        return ProtocolReport(protocol, bench.__name__, None, None)
    _quiet_kill_warning()
    period, _drive, sample = ALIGNMENT
    observe = observe_offset_ps(ALIGNMENT)
    for module in period_modules:
        bench_period = round(float(module.CLK_PERIOD_NS) * 1000)
        if bench_period != period:
            raise RuntimeError(
                f"sdf_protocol_alignment: {module.__name__}.CLK_PERIOD_NS is {bench_period} ps "
                f"but the SDC period is {period} ps; the bench grades ns at its own nominal"
            )
    report = ProtocolReport(protocol, bench.__name__, ALIGNMENT, observe)

    async def observe_edge(signal):
        await _RisingEdge(signal)
        await Timer(observe, unit="ps")

    for module in edge_modules:
        module.RisingEdge = observe_edge

    original_capture = capture_source.capture_pin_bits
    # Signals the DUT captures produced (the SPI control applies to these
    # only, never to the bench's synthetic model-only waveforms).
    captured = set()

    async def monitored_capture(dut, specs, cycles):
        monitor = PinDelayMonitor(dut, observe, sample).start()
        try:
            caps = await original_capture(dut, specs, cycles)
        finally:
            monitor.stop()
            report.add_capture(cycles, monitor)
        captured.update(id(pin.signal) for pin in caps.values())
        assert not monitor.violations, (
            f"{len(monitor.violations)} output transition(s) did not reach the pin before the "
            f"observe point ({observe} ps after the clk edge): {monitor.violations[:5]}"
        )
        return caps

    for module in capture_modules:
        module.capture_pin_bits = monitored_capture

    if spi_check_burst:
        original_check = bench.check_burst

        def check_burst_with_ceiling_control(sclk, mosi, miso, cs, mode, f_clk_hz,
                                             t0=0.0, t1=float("inf")):
            result = original_check(sclk, mosi, miso, cs, mode, f_clk_hz, t0=t0, t1=t1)
            if result.ok and id(sclk) in captured:
                ceiling_ns = 4e9 / float(f_clk_hz)
                factor = SPI_CEILING_CONTROL_FRACTION * ceiling_ns / result.sclk_period_ns
                control = original_check(
                    _scaled(sclk, factor), _scaled(mosi, factor), _scaled(miso, factor),
                    _scaled(cs, factor), mode, f_clk_hz, t0=t0 * factor, t1=t1 * factor,
                )
                caught = any("f_clk/4 ceiling" in v for v in control.violations)
                detail = (
                    f"mode {mode.number}: burst at {result.sclk_period_ns:.3f} ns compressed "
                    f"x{factor:.4f} -> {control.sclk_period_ns:.3f} ns, violations {control.violations}"
                )
                report.add_control(SPI_CEILING_CONTROL, caught, detail)
                assert caught, (
                    f"NEGATIVE CONTROL FAILED TO FAIL: {detail} -- the model did not "
                    "name the f_clk/4 ceiling"
                )
            return result

        bench.check_burst = check_burst_with_ceiling_control

    report.write()
    return report


def register(bench, namespace: dict) -> list:
    """Register the bench's own `@cocotb.test` objects in the wrapper's
    namespace (cocotb discovers tests in the named module only). They keep
    `module=<bench>`, so results name them as the bench's tests."""
    names = []
    for name, obj in list(vars(bench).items()):
        if isinstance(obj, (Test, TestGenerator)) and getattr(obj, "module", None) == bench.__name__:
            namespace[name] = obj
            names.append(name)
    if not names:
        raise RuntimeError(f"sdf_protocol_alignment: no cocotb tests found in {bench.__name__}")
    return names
