# SPDX-FileCopyrightText: © 2026 2AMLogic
# SPDX-License-Identifier: Apache-2.0
#
# Tiny Tapeout gds/test-workflow harness for the harness-bootstrap stub top
# (issue #2). The ISA is not designed yet (spec/, issue #1); this only
# checks the stub's actual behavior: `ui_in` is registered onto `uo_out` on
# clk edges while `ena` is high, and cleared on reset. See
# `verification/test_protocol_emulator.py` for this program's own
# klt-driven cocotb bench, which checks the same behavior through the RTL
# flow directly.
#
# Checks settle over 2 clock cycles rather than asserting exact 1-cycle
# latency: this stub's only sequential element is a single register, but
# pinning the test to the tightest possible latency would make it needlessly
# brittle to simulator/testbench timing details that have nothing to do with
# the behavior being verified, and the ratified ISA (issue #1) may pipeline
# pin updates differently anyway.

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")

    # Set the clock period to 10 us (100 KHz)
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1

    # Reset clears the registered output
    await ClockCycles(dut.clk, 2)
    assert dut.uo_out.value == 0

    dut._log.info("Test pin-through behavior")

    # ui_in should appear on uo_out within a couple of clock cycles
    dut.ui_in.value = 0x5A
    await ClockCycles(dut.clk, 2)
    assert dut.uo_out.value == 0x5A

    dut.ui_in.value = 0xA3
    await ClockCycles(dut.clk, 2)
    assert dut.uo_out.value == 0xA3

    # The bidirectional pins are configured as inputs (uio_oe == 0): nothing
    # drives the bus yet.
    assert dut.uio_oe.value == 0

    dut._log.info("Test ena gating")

    # While ena is low, uo_out holds its last value regardless of ui_in.
    dut.ena.value = 0
    dut.ui_in.value = 0x00
    await ClockCycles(dut.clk, 3)
    assert dut.uo_out.value == 0xA3
    dut.ena.value = 1
