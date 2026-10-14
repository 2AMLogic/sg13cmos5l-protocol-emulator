"""Issue #305, target-spec row 14(a)/(b): `rst_n` released at offsets from
the nominal release, graded with the same per-cycle pin assertions as
`test_protocol_emulator.py::test_reset_and_load_leaves_pins_cleared`, on the
RTL (zero delay) and on the routed netlist with SDF back-annotation.

Why this is its own module
--------------------------
`verification/test_protocol_emulator.py`, `verification/sdf_alignment.py`
and `flow/run-post-layout-sdf.sh` are provenance inputs of live evidence
records (`verification/check_records.py` fails a live record whose cited
input changed), so this issue leaves all three byte-identical. The cost is
that the per-cycle assertions of the reset test are restated here (the
bench's test releases `rst_n` inline, so it cannot be called with a
different release point); the bench's helpers, edge waits and the
SDF alignment are reused, not copied.

Nominal release and offsets
---------------------------
With the SDF alignment enabled (the `PE_ALIGN_*` variables the runner
exports from the gds run's own SDC; `sdf_alignment` is imported below for
its effect on the bench), the nominal release is the bench's drive point:
the SDC input delay (4 ns) after a clock pin edge, at the SDC period (20
ns). An offset is added to that: -3 ns releases 1 ns after the pin edge, +3
ns releases 7 ns after it. A negative offset is only legal while it stays
after the edge (offset >= -drive); a release before the edge is a
different cycle, not an offset, and raises. Without the alignment (the RTL
run) there is no SDC input delay to be early or late against; the release
is at the edge's zero-delay drive point whatever the offset (the offset is
a no-op, logged as such).

Every offset is attempted and logged (`rst_n release offset ...`) even
after an earlier one fails; the test fails at the end listing the failing
offsets. A failing offset is a finding to record (and, if the STA recovery
/ removal window says the offset is illegal, an expected-violation
observation), never a harness bug to tune away.

Note: Icarus implements SDF IOPATH/INTERCONNECT but drops SDF TIMINGCHECK
sections, so this module can show what the pins do through the real
post-route delays of the reset tree; it cannot observe a recovery/removal
violation.
"""

import binascii

import cocotb
from cocotb.clock import Clock
from cocotb.simtime import get_sim_time
from cocotb.triggers import Timer

import sdf_alignment as align  # rebinds the bench's helpers when PE_ALIGN_* are set
import test_protocol_emulator as bench

RELEASE_OFFSETS_NS = (-3, -1, 0, 1, 3)


async def release_rst_n(dut, offset_ns):
    """Wait for the next rising edge, then set `rst_n` high at the nominal
    release point plus `offset_ns` (see the module docstring)."""
    if align.ALIGNMENT is None:
        await bench.RisingEdge(dut.clk)
        dut.rst_n.value = 1
        dut._log.info("rst_n released at %d ps (no SDF alignment: offset %+g ns is a no-op)",
                      get_sim_time("ps"), offset_ns)
        return
    drive = align.ALIGNMENT[1]
    await align._RisingEdge(dut.clk)
    align._last_edge_ps = get_sim_time("ps")  # the aligned reads count from this edge
    delay = drive + round(offset_ns * 1000)
    if delay < 0:
        raise RuntimeError(f"rst_n release offset {offset_ns} ns lands {-delay} ps before the clock edge")
    if delay:
        await Timer(delay, unit="ps")
    dut.rst_n.value = 1
    dut._log.info("rst_n released at %d ps = edge %d ps + %d ps (nominal drive %d ps, offset %+g ns)",
                  get_sim_time("ps"), align._last_edge_ps, delay, drive, offset_ns)


async def reset_and_load_pins_cleared(dut, offset_ns):
    """`test_reset_and_load_leaves_pins_cleared`'s sequence and assertions
    (the clock must be running), with `rst_n` released by `release_rst_n`."""
    program = [bench.enc(bench.OP_HALT)]
    cycle = 0

    async def expect_cycle(base, sel, uo_want, what):
        nonlocal cycle
        dut.ui_in.value = base | (sel << 1)
        got = await bench.settle_read(dut, "uo_out")
        assert got == uo_want, (
            f"{what}, cycle {cycle}, ui_in[1]={sel}: uo_out {got:#04x}, want {uo_want:#04x}"
        )
        assert await bench.settle_read(dut, "uio_out") == 0, f"{what}, cycle {cycle}: uio_out moved"
        assert await bench.settle_read(dut, "uio_oe") == 0, f"{what}, cycle {cycle}: a uio pin is driven"
        cycle += 1

    def crc_byte(words, sel):
        crc = binascii.crc_hqx(b"".join(bytes((w >> 8, w & 0xFF)) for w in words), 0)
        return (crc >> 8) if sel else (crc & 0xFF)

    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0x80  # MODE high, serial line idle low
    dut.rst_n.value = 0
    await bench.ClockCycles(dut.clk, 2)
    for i in range(8):
        await expect_cycle(0x80, i & 1, 0x00, "in reset")
        if i < 7:
            await bench.RisingEdge(dut.clk)
    await release_rst_n(dut, offset_ns)
    await expect_cycle(0x80, 1, 0x00, "reset released, before the mode-sampling edge")
    await bench.RisingEdge(dut.clk)  # the mode-sampling edge: load phase

    committed = []
    for word in program:
        for bit in range(15, -1, -1):
            sel = cycle & 1
            await expect_cycle(0x80 | ((word >> bit) & 1), sel, crc_byte(committed, sel), "load phase")
            await bench.RisingEdge(dut.clk)  # the 16th of these commits the word
        committed.append(word)
    assert crc_byte(committed, 0) != 0 or crc_byte(committed, 1) != 0, "test premise"

    await expect_cycle(0x80, 0, crc_byte(committed, 0), "load phase, after the last word")
    await bench.RisingEdge(dut.clk)
    await expect_cycle(0x00, 1, crc_byte(committed, 1), "load phase, MODE low before its edge")
    await bench.RisingEdge(dut.clk)  # edge 0: run phase begins

    for i in range(12):
        await expect_cycle(0x00, i & 1, 0x00, f"run phase, edge {i}")
        await bench.RisingEdge(dut.clk)


@cocotb.test()
async def test_reset_release_offsets(dut):
    """Row 14(a)/(b) outcomes (`uio_out`/`uio_oe` 0, `uo_out` the documented
    reset value or the PM_CRC readout in the load phase, no X/Z -- an X/Z
    read raises) do not depend on where `rst_n` is released, over
    -3/-1/0/+1/+3 ns around the nominal release. One reset-and-load pass per
    offset, in one simulation."""
    cocotb.start_soon(Clock(dut.clk, bench.CLK_PERIOD_NS, unit="ns").start())
    failures = []
    for offset in RELEASE_OFFSETS_NS:
        try:
            await reset_and_load_pins_cleared(dut, offset)
        except (AssertionError, ValueError) as exc:
            dut._log.error("rst_n release offset %+d ns: FAIL: %s", offset, exc)
            failures.append((offset, str(exc)))
        else:
            dut._log.info("rst_n release offset %+d ns: PASS", offset)
    assert not failures, f"rst_n release offsets that failed: {failures}"
