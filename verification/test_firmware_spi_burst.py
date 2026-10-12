"""DUT-facing multi-byte SPI burst bench (issue #286; target-spec row 11's
"multi-byte bursts under one CS are untested" caveat).

Every program `test_firmware_spi.py` grades clocks one byte per CS-low
window. This bench grades the committed `firmware/asm/spi_mode0_burst3.asm`
(image `firmware/build/spi_mode0_burst3.hex`): THREE bytes clocked at the
4-cycles/bit ceiling (SCLK = f_clk/4) under a SINGLE chip-select
assertion, mode 0, loaded over the real serial load-phase pins onto the
real top and executed by the ISA core. The SCLK/MOSI/CS lines the program
drives and the MISO line an independent peripheral coroutine drives back
are captured and judged by the independent reference model
(`verification/reference_models/spi.py`, `check_burst`), which re-derives
every byte of both streams from the waveform.

It is its own module (not another test in `test_firmware_spi.py`) so that
`test_firmware_spi.py`, which four other experiments' records hash as an
input, stays byte-unchanged; the capture, pad and loader helpers are
imported from it, not re-derived. The only thing re-written here is the
peripheral's MISO driver, which `test_firmware_spi.drive_miso` limits to
one byte per CS fall.

What is measured, not assumed: the SCLK gap at each byte boundary (last
trailing edge of one byte to first leading edge of the next), in core
cycles, logged and bounded by `BURST3_MAX_BOUNDARY_GAP_CYCLES`. If a
program ever exceeds the bound, the right response is a recorded finding,
not a raised bound: row 11 is not relaxed.

Flow: cocotb + Icarus RTL simulation driven by `klt functional-verification`
(`verification/request-firmware-spi-burst.json`). No synthesis, timing or
gate-level number is claimed here; the cycle counts are cycles of the
core clock, whose Hz mapping (row 4) is unconfirmed.
"""

import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer

from reference_models.spi import MODES, check_burst
from firmware_artifacts import parse_cycle_sections, parse_hex_image, total_cycles
from repo_root import find_repo_root
from test_firmware_spi import (
    CAPTURE_MARGIN_CYCLES,
    CAPTURE_SPECS,
    CEIL_CYCLES_PER_BIT,
    CLK_PERIOD_NS,
    CS_BIT,
    F_CLK_HZ,
    MISO_BIT,
    SCLK_BIT,
    _bit,
    burst_windows,
    cycles_between,
    spi_pads,
)
from test_firmware_uart import capture_pin_bits
from test_protocol_emulator import load_program
from uio_pads import assert_spi_push_pull

REPO_ROOT = find_repo_root(globals().get("__file__"))
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

#: `spi_mode0_burst3.asm`: N bytes under ONE CS assertion at the ceiling
#: rate (mode 0 only). Distinct MOSI bytes (the program's committed
#: payload) and distinct MISO bytes (what the bench peripheral drives).
BURST3_NAME = "spi_mode0_burst3"
BURST3_TX = [0xA5, 0x3C, 0xD2]
BURST3_MISO = [0xC3, 0x5A, 0x96]
BURST3_N = len(BURST3_TX)
#: The asserted bound on the SCLK gap at a byte boundary: last trailing
#: edge of one byte to the first leading edge of the next, in core cycles.
#: Within a byte that gap is the half-period (2 cycles at 4 cycles/bit).
#: The bound is "no cycle beyond the half period": the f_clk/4 cadence is
#: unbroken across the boundary. Measured and logged either way.
BURST3_MAX_BOUNDARY_GAP_CYCLES = CEIL_CYCLES_PER_BIT // 2

SRC = REPO_ROOT / "firmware" / "asm" / f"{BURST3_NAME}.asm"
HEX = REPO_ROOT / "firmware" / "build" / f"{BURST3_NAME}.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / f"{BURST3_NAME}.cycles.txt"


async def drive_miso_stream(dut, pads, mode, miso_bytes, cycles: int):
    """Reactive peripheral-side MISO driver for ONE CS assertion carrying
    `len(miso_bytes)` bytes back to back (mode 0 / CPHA=0 and CPHA=1 as in
    `test_firmware_spi.drive_miso`, which this generalises from one byte to
    many): CPHA=0 presents bit 0 at CS fall and bit k after each trailing
    edge; CPHA=1 presents bit k after each leading edge. Reads the pad
    lines in the read-only region after each clock edge and drives MISO
    1 ns later, never at a sampling instant."""
    idle = mode.cpol
    nbits = 8 * len(miso_bytes)

    def stream_bit(k):
        return _bit(miso_bytes[k // 8], k % 8)

    started = False
    bit_k = 0
    prev_sclk, prev_cs = idle, None
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        cs = pads.level(CS_BIT)
        sclk = pads.level(SCLK_BIT)
        await Timer(1, unit="ns")
        write = None
        if prev_cs == 1 and cs == 0 and not started:
            started = True
            bit_k = 0
            if mode.cpha == 0:
                write = stream_bit(0)
                bit_k = 1
        elif started and prev_cs == 0 and cs == 0 and sclk != prev_sclk:
            if mode.cpha == 0 and sclk == idle and bit_k < nbits:
                write = stream_bit(bit_k)
                bit_k += 1
            elif mode.cpha == 1 and sclk != idle and bit_k < nbits:
                write = stream_bit(bit_k)
                bit_k += 1
        if write is not None:
            pads.drive(MISO_BIT, write)
        prev_sclk, prev_cs = sclk, cs


async def run_burst3(dut, words, mode, run_cycles: int):
    """Load `words`, run them on the SPI board with the multi-byte
    peripheral, capturing `CAPTURE_SPECS` every clock edge."""
    assert len(words) <= 256, "program exceeds DR 0001's 256-word memory"
    pads = spi_pads(dut).start()
    await load_program(dut, words)
    assert pads.resets == 1 and pads.oe_seen == 0, (
        f"{BURST3_NAME}: uio pads 0x{pads.oe_seen:02x} were enabled between "
        "reset release and the end of the load phase (DR 0012)"
    )
    driver = cocotb.start_soon(drive_miso_stream(dut, pads, mode, BURST3_MISO, run_cycles))
    caps = await capture_pin_bits(dut, CAPTURE_SPECS, run_cycles)
    await driver
    pads.stop()
    assert_spi_push_pull(pads, BURST3_NAME)
    return caps


@cocotb.test()
async def test_burst3_image_is_fresh(dut):
    """The committed hex and cycle report match the committed source, the
    program is lint-clean and fits program memory, and its single cycle
    section is the 3 x 8 bits x 4 cycles this bench grades, straight-line
    (DR 0003: committed artifacts are the evidence)."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    assert program.warnings == [], f"{BURST3_NAME} must be lint-clean"
    assert len(program.instructions) <= 256, "exceeds DR 0001's 256 words"
    report = CYCLES.read_text(encoding="utf-8")
    sections = parse_cycle_sections(report)
    assert BURST3_NAME in sections, f"committed report is missing {BURST3_NAME!r}"
    _start, _end, cycles, branches = sections[BURST3_NAME]
    assert cycles == 8 * BURST3_N * CEIL_CYCLES_PER_BIT, (
        f"section {BURST3_NAME} claims {cycles} cycles, this bench grades "
        f"{BURST3_N} bytes x 8 bits x {CEIL_CYCLES_PER_BIT} cycles"
    )
    assert branches == "false", f"section {BURST3_NAME} should be straight-line"
    dut._log.info(
        f"{BURST3_NAME}: {len(program.instructions)} words, "
        f"{total_cycles(report)} cycles to execute"
    )


@cocotb.test()
async def test_mode0_three_byte_burst_under_one_cs(dut):
    """Issue #286 (target-spec row 11's multi-byte caveat): the committed
    `spi_mode0_burst3` program clocks N=3 bytes in ONE CS-low window; the
    independent `check_burst` grades the whole window.

    Asserted: exactly one CS window; the model decodes every bit of every
    byte (MOSI = the committed payload, MISO = what the bench peripheral
    drove) across the byte boundaries, with the byte count equal to N; the
    SCLK period is exactly 4 cycles (f_clk/4) with no ceiling violation;
    within a byte every SCLK half-period is 2 cycles; and the SCLK gap at
    each byte boundary is MEASURED from the captured edges, logged, and
    bounded by `BURST3_MAX_BOUNDARY_GAP_CYCLES` (a finding is recorded,
    never a loosened bound, if it ever exceeds that).
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    mode = MODES[0]
    words = parse_hex_image(HEX)
    run_cycles = total_cycles(CYCLES.read_text(encoding="utf-8")) + CAPTURE_MARGIN_CYCLES
    caps = await run_burst3(dut, words, mode, run_cycles)
    cs, sclk, mosi, miso = caps["cs"], caps["sclk"], caps["mosi"], caps["miso"]

    windows = burst_windows(cs)
    assert len(windows) == 1, (
        f"expected exactly 1 CS-low window (all {BURST3_N} bytes under one "
        f"assertion), captured {len(windows)}"
    )
    tf, tr, cf, cr = windows[0]
    report = check_burst(
        sclk.signal, mosi.signal, miso.signal, cs.signal, mode, F_CLK_HZ,
        t0=tf, t1=tr,
    )
    dut._log.info(f"{BURST3_NAME} burst: {report}")
    assert report.ok, f"{BURST3_NAME} violated the model: {report.violations}"
    assert len(report.mosi_bytes) == BURST3_N and len(report.miso_bytes) == BURST3_N, (
        f"model decoded {len(report.mosi_bytes)} MOSI / {len(report.miso_bytes)} "
        f"MISO bytes, expected N={BURST3_N}"
    )
    assert report.mosi_bytes == BURST3_TX, (
        f"model decoded MOSI {[hex(b) for b in report.mosi_bytes]}, the committed "
        f"program transmits {[hex(b) for b in BURST3_TX]}"
    )
    assert report.miso_bytes == BURST3_MISO, (
        f"model decoded MISO {[hex(b) for b in report.miso_bytes]}, the bench "
        f"peripheral drove {[hex(b) for b in BURST3_MISO]}"
    )
    assert report.sclk_period_ns == CEIL_CYCLES_PER_BIT * CLK_PERIOD_NS, (
        f"SCLK period measures {report.sclk_period_ns:.3f} ns, expected exactly "
        f"{CEIL_CYCLES_PER_BIT} x {CLK_PERIOD_NS} ns"
    )

    # Cycle-domain measurement of every SCLK edge in the window.
    edge_cycles = cycles_between(sclk, tf, tr)
    n_edges = 2 * 8 * BURST3_N
    assert len(edge_cycles) == n_edges, (
        f"{len(edge_cycles)} SCLK edges in the window, expected {n_edges}"
    )
    gaps = [b - a for a, b in zip(edge_cycles, edge_cycles[1:])]
    half = CEIL_CYCLES_PER_BIT // 2
    # gap i joins edge i to edge i+1; edges 2k / 2k+1 are bit k's leading /
    # trailing edges, so gaps at odd i are trailing -> next leading. A byte
    # boundary is after bit 8*j - 1, i.e. gap index 16*j - 1.
    boundary_idx = [16 * j - 1 for j in range(1, BURST3_N)]
    boundary_gaps = [gaps[i] for i in boundary_idx]
    within = [g for i, g in enumerate(gaps) if i not in boundary_idx]
    assert all(g == half for g in within), (
        f"within-byte SCLK half-periods {within} cycles, expected uniform {half}"
    )
    # Leading-to-leading period across each boundary.
    boundary_periods = [edge_cycles[i + 1] - edge_cycles[i - 1] for i in boundary_idx]
    dut._log.info(
        f"{BURST3_NAME}: inter-byte SCLK gap (last trailing edge -> next "
        f"leading edge) = {boundary_gaps} cycles at the {len(boundary_gaps)} "
        f"byte boundaries; within-byte half-period = {half}; "
        f"across-boundary leading-to-leading periods = {boundary_periods}; "
        f"asserted bound <= {BURST3_MAX_BOUNDARY_GAP_CYCLES} cycles"
    )
    assert all(g <= BURST3_MAX_BOUNDARY_GAP_CYCLES for g in boundary_gaps), (
        f"FINDING: inter-byte SCLK gap {boundary_gaps} cycles exceeds the "
        f"{BURST3_MAX_BOUNDARY_GAP_CYCLES}-cycle bound (the f_clk/4 cadence "
        f"is broken at the byte boundary); record it, do not relax the bound"
    )
    assert all(p == CEIL_CYCLES_PER_BIT for p in boundary_periods), (
        f"leading-to-leading SCLK period across a byte boundary "
        f"{boundary_periods} cycles, expected {CEIL_CYCLES_PER_BIT}"
    )
    assert all(g >= half for g in boundary_gaps), (
        f"inter-byte gap {boundary_gaps} below the {half}-cycle half-period "
        "(the 4-cycle ceiling is broken at the byte boundary)"
    )

    # Negative control on the DUT's own capture: the burst is mode 0 only.
    for wrong in MODES[1:]:
        wrong_report = check_burst(
            sclk.signal, mosi.signal, miso.signal, cs.signal, wrong, F_CLK_HZ,
            t0=tf, t1=tr,
        )
        assert (not wrong_report.ok) or wrong_report.mosi_bytes != BURST3_TX, (
            f"NEGATIVE CONTROL FAILED TO FAIL: captured burst round-tripped "
            f"under wrong mode {wrong.number}: {wrong_report}"
        )
