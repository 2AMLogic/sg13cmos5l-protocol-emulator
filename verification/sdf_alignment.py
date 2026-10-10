"""Post-layout entry point for the core bench (issue #106): the unmodified
`test_protocol_emulator.py` tests, run with SDF-aware drive/sample alignment.

Why this module exists
----------------------
`test_protocol_emulator.py` drives `ui_in`/`rst_n` in the same time step as
the clock edge it follows and reads the output pins in that same step
(`settle_read` awaits `ReadOnly` at the edge). At zero delay that is exact:
every flop updates in zero time at the edge. Against the routed netlist with
back-annotated SDF it is a race the design was never signed off against:

- the clock reaches the flops 0.65-0.79 ns after the `clk` pin edge
  (slow-corner network latency in LibreLane STA `clock.rpt` at the time
  of issue #106), so an input
  changed *at* the pin edge can be captured by that same edge (a hold race
  the testbench creates, not the design);
- an output register's new value reaches its pin 0.43-1.53 ns after the pin
  edge (min/max output-path arrival across the three corners), so a read at
  the pin edge sees the previous cycle's value.

LibreLane's STA does not check that environment. Its SDC
(`final/sdc/<top>.sdc` of the `gds` run) says the inputs change
`set_input_delay` after the clock edge, and that the outputs are captured
`set_output_delay` before the next edge, at a clock of `create_clock -period`.
Every corner closes setup and hold with positive slack under exactly that
environment. This module makes the bench present that environment and no
other:

- **clock period** = the SDC `create_clock -period` (20 ns today; the RTL
  bench's own `CLK_PERIOD_NS` is 10 ns, which no STA run signs off);
- **drive offset** = the SDC input delay (4 ns today): every stimulus the
  bench applies after a clock edge is applied that long after the pin edge;
- **sample offset** = period minus the SDC output delay (16 ns today): every
  pin read happens at the latest instant the constraint promises the output
  is valid, i.e. where an external receiver with that output delay samples.

None of the three is tuned to make a test pass: all three are read from the
SDC by `flow/run-post-layout-sdf.sh` and handed over in environment
variables, and the evidence record cites the STA numbers that bound them.

How it is applied, and why the bench file is untouched
------------------------------------------------------
The bench's tests reach the clock and the pins only through three module
globals: `RisingEdge`/`ClockCycles` (every edge it waits for) and
`settle_read` (every pin read; `watch_pin` calls it too), plus
`CLK_PERIOD_NS` (every `Clock` it starts). When the alignment is enabled
this module rebinds those four names *inside the imported bench module*:

- `RisingEdge(sig)` / `ClockCycles(sig, n)` wait for the real edge(s),
  record the edge time, then wait the drive offset before returning. Edge
  counts are unchanged; only the stimulus point inside the cycle moves.
- `settle_read(dut, name)` waits until `last edge + sample offset`
  (immediately if a read in the same cycle already passed that point),
  reads in `ReadOnly`, and leaves the read-only region with a 1 ps step
  instead of the bench's 1 ns, so consecutive reads stay in the same cycle.
  A read with no edge seen yet, or a full period or more after the last
  edge, fails loudly rather than sampling the wrong cycle.

So every test body, every expected value and every edge number is the
bench's own bytes (the file's hash is unchanged by this issue), and a test
that adds a new raw drive or read bypasses the alignment and runs at the
pin edge: it can fail spuriously, but it cannot pass because of this module.

`test_alu_flags_whitebox` reads `dut.u_core.flag_z`/`flag_c`; the routed
netlist is flattened and has no `u_core` scope. It is registered here as a
*skipped* copy (cocotb `skip=True`, reported in results.xml and as
`skipped_count` in the klt envelope), never as a pass. The bench file's own
test object is not modified; the RTL run still executes it.

Opt-in, default off
-------------------
Nothing in this module runs unless a testbench request names
`sdf_alignment` as its module; no RTL request does. With all three
variables unset the bench's helpers are left exactly as they are (only the
white-box skip applies); setting some but not all is an error. The
variables, all in nanoseconds:

    PE_ALIGN_CLK_PERIOD_NS     clock period the tests start
    PE_ALIGN_DRIVE_OFFSET_NS   stimulus point after each pin edge
    PE_ALIGN_SAMPLE_OFFSET_NS  sample point after each pin edge

with 0 <= drive < sample < period required.
"""

import copy
import os

from cocotb._decorators import Test, TestGenerator
from cocotb.simtime import get_sim_time
from cocotb.triggers import ClockCycles as _ClockCycles
from cocotb.triggers import ReadOnly, Timer
from cocotb.triggers import RisingEdge as _RisingEdge

import test_protocol_emulator as bench

ENV_PERIOD = "PE_ALIGN_CLK_PERIOD_NS"
ENV_DRIVE = "PE_ALIGN_DRIVE_OFFSET_NS"
ENV_SAMPLE = "PE_ALIGN_SAMPLE_OFFSET_NS"

WHITEBOX_TESTS = ("test_alu_flags_whitebox",)


def _ps(name):
    raw = os.environ[name]
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name}={raw!r} is not a number of nanoseconds") from exc
    ps = round(value * 1000)
    if abs(ps - value * 1000) > 1e-6:
        raise RuntimeError(f"{name}={raw!r} is finer than the 1 ps simulator precision")
    return ps


def read_alignment():
    """(period_ps, drive_ps, sample_ps), or None when alignment is off."""
    present = [n for n in (ENV_PERIOD, ENV_DRIVE, ENV_SAMPLE) if os.environ.get(n, "") != ""]
    if not present:
        return None
    if len(present) != 3:
        raise RuntimeError(
            f"sdf_alignment: set all of {ENV_PERIOD}, {ENV_DRIVE}, {ENV_SAMPLE} or none (got {present})"
        )
    period, drive, sample = _ps(ENV_PERIOD), _ps(ENV_DRIVE), _ps(ENV_SAMPLE)
    if not 0 <= drive < sample < period:
        raise RuntimeError(
            f"sdf_alignment: need 0 <= drive < sample < period, got drive={drive} ps, "
            f"sample={sample} ps, period={period} ps"
        )
    return period, drive, sample


ALIGNMENT = read_alignment()

# The time of the last clock pin edge the bench waited for, in ps.
_last_edge_ps = None


async def _drive_point():
    global _last_edge_ps
    _last_edge_ps = get_sim_time("ps")
    if ALIGNMENT[1]:
        await Timer(ALIGNMENT[1], unit="ps")


async def aligned_rising_edge(signal):
    await _RisingEdge(signal)
    await _drive_point()


async def aligned_clock_cycles(signal, num_cycles):
    await _ClockCycles(signal, num_cycles)
    await _drive_point()


async def aligned_settle_read(dut, name):
    period, _, sample = ALIGNMENT
    if _last_edge_ps is None:
        raise RuntimeError(f"sdf_alignment: read of {name} before any clock edge was observed")
    now = get_sim_time("ps")
    elapsed = now - _last_edge_ps
    if elapsed >= period:
        raise RuntimeError(
            f"sdf_alignment: read of {name} {elapsed} ps after the last observed edge "
            f"(period {period} ps): it would sample the wrong cycle"
        )
    if elapsed < sample:
        await Timer(sample - elapsed, unit="ps")
    await ReadOnly()
    value = int(getattr(dut, name).value)
    await Timer(1, unit="ps")  # leave the read-only region, stay in this cycle
    return value


if ALIGNMENT is not None:
    bench.CLK_PERIOD_NS = ALIGNMENT[0] / 1000
    bench.RisingEdge = aligned_rising_edge
    bench.ClockCycles = aligned_clock_cycles
    bench.settle_read = aligned_settle_read

# Register the bench's tests under this module: cocotb discovers every
# `@cocotb.test` object (a TestGenerator in cocotb 2.x; a Test is accepted
# too) in the named module's namespace. They keep
# module="test_protocol_emulator", so results.xml names them as the bench's.
for _name, _obj in list(vars(bench).items()):
    if isinstance(_obj, (Test, TestGenerator)):
        if _name in WHITEBOX_TESTS:
            _obj = copy.copy(_obj)  # the bench module's own object is untouched
            _obj.skip = True  # flattened netlist: no u_core scope to read
        globals()[_name] = _obj
_missing = [n for n in WHITEBOX_TESTS if n not in globals()]
if _missing:
    raise RuntimeError(f"sdf_alignment: white-box test(s) {_missing} not found in the bench")
del _name, _obj, _missing
