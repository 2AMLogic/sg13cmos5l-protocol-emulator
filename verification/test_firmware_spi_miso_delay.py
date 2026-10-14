"""CPHA=1 functional-burst MISO delay bench (issue #309, DR 0021 open item 1).

In SPI modes 1 and 3 the leading edge is where the peripheral *launches*
MISO and the trailing edge is where it is sampled. `test_firmware_spi.py`'s
peripheral changes MISO 1 ns after the launch edge, so it cannot tell where
in the 10-cycle bit the controller's `IN` sits. This bench gives the
peripheral a clock-to-MISO delay, in whole core cycles, and asks whether the
committed functional burst still receives the byte (the echo on `uo_out`).

What is graded
--------------
* Committed `spi_mode1` / `spi_mode3` images (IN = instruction 5 of the
  bit, 4 core cycles after the launch edge, immediately before the trailing
  OUT): the byte is received exactly for delays of 0, 1, 2 and 3 cycles, for
  the bytes 0x5A, 0x00, 0xFF and 0xA5.
* The same images at a delay of 4 cycles must FAIL (the IN is 4 cycles after
  the launch edge, so a change landing 4 cycles + 1 ns after the edge is
  missed): the upper edge of the margin, so the sweep can fail on the new
  image.
* Negative control: the pre-#309 images, kept byte for byte as
  `verification/fixtures/spi_mode{1,3}_early_in.asm` (IN = instruction 2,
  1 cycle after the launch edge), must FAIL at delay >= 1 cycle for at least
  one byte pattern at every delay swept (they do on 0x5A, 0x00 and 0xA5).

Units. The delay is in core cycles; the ns figures (20 ns per cycle) are
arithmetic at the bench's nominal 50 MHz clock, i.e. target-spec row 4's
*unconfirmed* clock (see `test_firmware_spi.py`'s docstring). The change
lands 1 ns after the clock edge it is scheduled for, never at a sampling
instant, so the pass/fail boundary is known to cycle granularity only: the
new image tolerates a change <= 3 cycles + 1 ns (61 ns) after the launch
edge and misses one at 4 cycles + 1 ns (81 ns); the pre-#309 image tolerates
1 ns and misses 21 ns.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer

from reference_models.spi import MODES

from test_firmware_spi import (  # noqa: F401  (helpers, not tests)
    CAPTURE_MARGIN_CYCLES,
    CAPTURE_SPECS,
    CEIL_MISO,
    CLK_PERIOD_NS,
    CS_BIT,
    FUNC_MISO,
    REPO_ROOT,
    SCLK_BIT,
    _bit,
    asm,
    assert_spi_push_pull,
    burst_windows,
    capture_pin_bits,
    committed_total_cycles,
    load_hex,
    load_program,
    spi_pads,
    uo_byte_at,
    MISO_BIT,
)

#: Peripheral clock-to-MISO delays the committed images must tolerate.
TOLERATED_DELAYS_CYCLES = (0, 1, 2, 3)
#: The delay at which the committed images must fail.
FAILING_DELAY_CYCLES = 4
#: Received bytes: the bench default, all-zero, all-one, alternating.
BYTES = (FUNC_MISO, 0x00, 0xFF, 0xA5)

FIXTURE_DIR = REPO_ROOT / "verification" / "fixtures"


async def drive_miso_delayed(dut, pads, mode, miso_bytes, cycles: int, delay_cycles: int):
    """`test_firmware_spi.drive_miso` with the peripheral's clock-to-MISO
    delay: a change the peripheral would make 1 ns after a clock edge lands
    `delay_cycles` whole cycles later (still 1 ns after a clock edge)."""
    idle = mode.cpol
    burst, bit_k = -1, 0
    prev_sclk, prev_cs = idle, None
    pending = []  # (due cycle, level)
    for n in range(cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        cs = pads.level(CS_BIT)
        sclk = pads.level(SCLK_BIT)
        await Timer(1, unit="ns")
        write = None
        if prev_cs == 1 and cs == 0 and burst < len(miso_bytes) - 1:
            burst += 1
            bit_k = 0
            if mode.cpha == 0:
                write = _bit(miso_bytes[burst], 0)
                bit_k = 1
        elif burst >= 0 and prev_cs == 0 and cs == 0 and sclk != prev_sclk:
            if mode.cpha == 1 and sclk != idle and bit_k < 8:
                write = _bit(miso_bytes[burst], bit_k)  # after a leading edge
                bit_k += 1
        if write is not None:
            pending.append((n + delay_cycles, write))
        while pending and pending[0][0] <= n:
            pads.drive(MISO_BIT, pending.pop(0)[1])
        prev_sclk, prev_cs = sclk, cs


async def functional_echo(dut, tag, words, mode, byte, delay):
    """Load and run `words` on the SPI board with MISO delayed `delay`
    cycles on both bursts; return the byte echoed on uo_out at the end."""
    run_cycles = 198 + CAPTURE_MARGIN_CYCLES
    pads = spi_pads(dut).start()
    await load_program(dut, words)
    assert pads.resets == 1 and pads.oe_seen == 0, (
        f"{tag}: uio pads enabled before the end of the load phase"
    )
    driver = cocotb.start_soon(
        drive_miso_delayed(dut, pads, mode, [CEIL_MISO, byte], run_cycles, delay))
    caps = await capture_pin_bits(dut, CAPTURE_SPECS, run_cycles)
    await driver
    pads.stop()
    assert_spi_push_pull(pads, tag)
    windows = burst_windows(caps["cs"])
    assert len(windows) == 2, f"{tag}: {len(windows)} CS bursts, expected 2"
    return uo_byte_at(caps, run_cycles)


def fixture_words(mode_number: int) -> list:
    program = asm.assemble_file(FIXTURE_DIR / f"spi_mode{mode_number}_early_in.asm")
    assert program.warnings == []
    return program.words


@cocotb.test()
async def test_committed_cpha1_images_tolerate_miso_delay(dut):
    """The committed mode 1 / mode 3 functional bursts receive every byte
    pattern with the peripheral's MISO delayed by 0..3 core cycles, and
    miss it at 4 (the margin's upper edge)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    assert committed_total_cycles(1) == committed_total_cycles(3) == 198
    for mode_number in (1, 3):
        mode, words = MODES[mode_number], load_hex(mode_number)
        for delay in TOLERATED_DELAYS_CYCLES:
            for byte in BYTES:
                got = await functional_echo(
                    dut, f"mode {mode_number} d={delay} 0x{byte:02x}",
                    words, mode, byte, delay)
                assert got == byte, (
                    f"mode {mode_number}: MISO delayed {delay} cycles "
                    f"({delay * CLK_PERIOD_NS} ns at the nominal clock), byte "
                    f"0x{byte:02x} echoed as 0x{got:02x}"
                )
        past = await functional_echo(
            dut, f"mode {mode_number} d={FAILING_DELAY_CYCLES} 0x00",
            words, mode, 0x00, FAILING_DELAY_CYCLES)
        assert past != 0x00, (
            f"mode {mode_number}: a {FAILING_DELAY_CYCLES}-cycle MISO delay "
            "was still received; the sweep's upper edge no longer bites"
        )
        dut._log.info(
            f"mode {mode_number}: exact at delays {TOLERATED_DELAYS_CYCLES}, "
            f"missed at {FAILING_DELAY_CYCLES} (0x00 echoed as 0x{past:02x})"
        )


@cocotb.test()
async def test_pre_309_images_fail_miso_delay_negative_control(dut):
    """NEGATIVE CONTROL: the pre-#309 images (IN 1 cycle after the launch
    edge) receive the byte with the bench's original ~0 delay and fail once
    the peripheral's MISO is delayed by one core cycle or more."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    for mode_number in (1, 3):
        mode, words = MODES[mode_number], fixture_words(mode_number)
        for byte in BYTES:
            got = await functional_echo(
                dut, f"legacy mode {mode_number} d=0 0x{byte:02x}",
                words, mode, byte, 0)
            assert got == byte, (
                f"legacy mode {mode_number}: not received even at delay 0 "
                f"(0x{byte:02x} -> 0x{got:02x}); the fixture is not the old image"
            )
        for delay in (1, 2, 3):
            failures = []
            for byte in BYTES:
                got = await functional_echo(
                    dut, f"legacy mode {mode_number} d={delay} 0x{byte:02x}",
                    words, mode, byte, delay)
                if got != byte:
                    failures.append((byte, got))
            assert failures, (
                f"NEGATIVE CONTROL FAILED TO FAIL: the pre-#309 mode "
                f"{mode_number} image received every byte at delay {delay}"
            )
            dut._log.info(
                f"legacy mode {mode_number} d={delay}: missed "
                + ", ".join(f"0x{b:02x}->0x{g:02x}" for b, g in failures)
            )
