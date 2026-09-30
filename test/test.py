# SPDX-FileCopyrightText: © 2026 2AMLogic
# SPDX-License-Identifier: Apache-2.0
#
# Tiny Tapeout gds/test-workflow harness for the ISA core top (issue #18).
#
# The top is no longer the harness-bootstrap stub (issue #2): it is the
# core datapath of spec/decision-records/0001-isa.md wired to its
# SRAM-macro-backed program memory (DR 0005). So this harness no longer
# checks "ui_in registered onto uo_out" -- it loads a real program over
# DR 0001's serial load phase (MODE = ui_in[7], data = ui_in[0]) and
# checks what that firmware drives onto the pins.
#
# This file runs in BOTH legs of the gds workflow: RTL (`make`) and
# gate-level (`make GATES=yes`, the `gl_test` job, against the
# post-synthesis netlist plus the PDK cell models and the SRAM macro's
# behavioural model). It is therefore deliberately kept to behaviour both
# legs share: pin observables only, no hierarchical peeks, and checks
# spaced by whole clock cycles.
#
# The deep, cycle-exact per-opcode coverage lives in this program's own
# bench, verification/test_protocol_emulator.py (13 directed cases driven
# by `klt functional-verification`, with an append-only evidence record).
# This harness is the template's CI sign-off leg: enough to prove the
# loaded program really executes on the fabricated netlist, not a second
# copy of that suite.

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

# DR 0001 "Encoding": [15:12] opcode, [11:10] Rd, [9:8] Rs/port, [7:0] imm8.
OP_LDI, OP_OUT, OP_WAIT, OP_HALT = 0x1, 0xA, 0xB, 0xF
OP_IN, OP_ADD = 0x9, 0x3
PORT_UI_IN, PORT_UO_OUT = 0, 2
R0, R1 = 0, 1


def enc(opcode, rd=0, rs=0, imm=0):
    return (opcode << 12) | (rd << 10) | (rs << 8) | imm


async def load_program(dut, words):
    """Reset with MODE high, shift `words` in MSB-first (one bit per
    clock on ui_in[0]), then drop MODE to enter the run phase.

    Returns just after the MODE-drop edge. Under DR 0005's fetch-ahead
    amendment the next edge primes the fetch (address 0 is captured) and
    the edge after that retires the instruction at pc=0 -- a fixed,
    one-time +1 cycle at run-phase entry.
    """
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0x80  # MODE high, serial line idle low
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge latches MODE high

    for word in words:
        for bit in range(15, -1, -1):
            dut.ui_in.value = 0x80 | ((word >> bit) & 1)
            await RisingEdge(dut.clk)

    dut.ui_in.value = 0x00  # MODE drop: exit to run phase
    await RisingEdge(dut.clk)


async def step(dut, edges):
    """Advance `edges` rising edges and let the edge's nonblocking
    assignments settle before the caller reads a pin."""
    await ClockCycles(dut.clk, edges)
    await Timer(1, unit="ns")


@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")

    # Set the clock period to 10 us (100 KHz)
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())

    # A program that exercises a load, an ALU op, both pin directions and
    # a stall -- one of each instruction class the pins can observe.
    #
    #   idx  instruction                 executes at edge   effect
    #    0   LDI R0, 0x5A                       2
    #    1   OUT uo_out, R0                     3           uo_out <- 0x5A
    #    2   WAIT 3                           4..7          4 cycles
    #    3   IN  R1, ui_in                      8           R1 <- ui_in (0x21)
    #    4   LDI R0, 0x01                       9
    #    5   ADD R1, R0                        10           R1 <- 0x22
    #    6   OUT uo_out, R1                    11           uo_out <- 0x22
    #    7   HALT                              12           idle until reset
    program = [
        enc(OP_LDI, rd=R0, imm=0x5A),
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),
        enc(OP_WAIT, imm=3),
        enc(OP_IN, rd=R1, rs=PORT_UI_IN),
        enc(OP_LDI, rd=R0, imm=0x01),
        enc(OP_ADD, rd=R1, rs=R0),
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),
        enc(OP_HALT),
    ]

    dut._log.info("Reset and serial program load (DR 0001 load phase)")
    await load_program(dut, program)

    # Reset left both pin-output registers cleared, and the load phase
    # changed nothing: the first instruction has not executed yet.
    await step(dut, 1)  # edge 1: the fetch-ahead priming edge
    assert dut.uo_out.value == 0, "reset/load must leave uo_out cleared"
    # The bidirectional pins are configured as inputs (uio_oe == 0):
    # DR 0001 fixes direction at synthesis time, so nothing the firmware
    # does may ever move it.
    assert dut.uio_oe.value == 0

    dut._log.info("Test the loaded firmware drives uo_out")

    # Edge 2 retires the LDI; the OUT at index 1 retires at edge 3, so
    # 0x5A appears then and not before.
    await step(dut, 1)  # edge 2
    assert dut.uo_out.value == 0, "OUT has not executed yet"
    await step(dut, 1)  # edge 3
    assert dut.uo_out.value == 0x5A, (
        f"firmware OUT: got {int(dut.uo_out.value):#04x}, want 0x5a"
    )

    dut._log.info("Test WAIT stalls, IN samples a pin, ADD runs")

    # Present the value the IN at index 3 will sample at edge 8. MODE
    # (ui_in[7]) stays low: mode is latched only at reset release, so
    # ui_in is now an ordinary ISA input port.
    dut.ui_in.value = 0x21

    # WAIT 3 consumes edges 4..7 (imm8 + 1 = 4 cycles), so uo_out still
    # reads 0x5A at edge 7 -- a WAIT that stalled the wrong number of
    # cycles would move every check after it.
    await step(dut, 4)  # edges 4..7
    assert dut.uo_out.value == 0x5A, "WAIT must not disturb the pin register"

    # IN (8), LDI (9), ADD (10), OUT (11): 0x21 + 0x01 = 0x22.
    await step(dut, 4)  # edges 8..11
    assert dut.uo_out.value == 0x22, (
        f"IN+ADD+OUT: got {int(dut.uo_out.value):#04x}, want 0x22"
    )

    dut._log.info("Test HALT freezes the core")

    # HALT retires at edge 12 and the core idles until reset: no later
    # cycle, and no pin traffic, may move an output again.
    await step(dut, 1)  # edge 12
    dut.ui_in.value = 0xFF
    dut.uio_in.value = 0xFF
    await step(dut, 20)
    assert dut.uo_out.value == 0x22, "HALT must freeze the pin registers"
    assert dut.uio_out.value == 0, "no OUT to port 11 ever ran"
    assert dut.uio_oe.value == 0
