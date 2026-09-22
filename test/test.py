# SPDX-FileCopyrightText: © 2026 2AMLogic
# SPDX-License-Identifier: Apache-2.0
#
# Tiny Tapeout gds/test-workflow harness for the protocol-emulator top
# (issues #2, #18). The top is no longer the registered-pin-through stub:
# it is the ratified ISA's core datapath (DR 0001,
# spec/decision-records/0001-isa.md) wired to its program memory. This
# harness therefore loads a real firmware program over the serial
# load-phase protocol (MODE = ui_in[7], serial data = ui_in[0]) and checks
# the program executing on the core through the pins -- the same
# load-then-run path every real firmware for this chip uses.
#
# The committed firmware is a 3-instruction pin echo:
#
#     0: IN  R0, port 00   (read ui_in)
#     1: OUT port 10, R0   (drive uo_out; visible one cycle later)
#     2: JMP 0             (repeat forever)
#
# so `uo_out` tracks `ui_in` one loop iteration (3 cycles) behind -- the
# firmware equivalent of the stub's registered pin-through, which keeps
# this CI leg a meaningful end-to-end check (load phase, fetch/execute,
# pin ports, and jump) without duplicating the per-instruction,
# cycle-exact coverage of `verification/test_protocol_emulator.py`
# (this program's own klt-driven bench; see `verification/README.md`).
#
# `ena` is not exercised on purpose: the Tiny Tapeout template documents
# it as "always 1 when the design is powered, so you can ignore it", and
# DR 0001's load protocol is reset-gated, not power-gated.
#
# Checks settle over whole loop iterations rather than asserting exact
# 1-cycle latencies: this harness runs in the template's CI toolchain
# (see test/requirements.txt), and the cycle-exact timing claims live in
# the verification/ bench where the evidence-record convention can cite
# them.

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly

# DR 0001 opcode table (spec/decision-records/0001-isa.md, "Encoding").
OP_IN, OP_OUT, OP_JMP = 0x9, 0xA, 0xC


def enc(opcode, rd=0, rs=0, imm=0):
    """One 16-bit instruction word: [15:12] opcode, [11:10] Rd,
    [9:8] Rs/port, [7:0] imm8. For OUT the source register sits in the
    Rd field and the port in the Rs field (the uniform I/O encoding the
    core's header documents)."""
    return (opcode << 12) | (rd << 10) | (rs << 8) | imm


ECHO_PROGRAM = [
    enc(OP_IN, rd=0, rs=0),    # R0 <- ui_in        (port 00)
    enc(OP_OUT, rd=0, rs=2),   # uo_out <- R0       (port 10)
    enc(OP_JMP, imm=0),        # repeat
]


async def load_and_run(dut, words):
    """Reset with MODE high, shift `words` in MSB-first one bit per clock
    on ui_in[0], then drop MODE to enter the run phase (DR 0001 section
    "Program memory sizing and loading")."""
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0x80  # MODE high, serial line idle low
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 1)  # the mode-sampling edge

    for word in words:
        for bit in range(15, -1, -1):
            serial = (word >> bit) & 1
            dut.ui_in.value = 0x80 | serial
            await ClockCycles(dut.clk, 1)

    dut.ui_in.value = 0x00  # MODE drop: exit to run phase
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_project(dut):
    dut._log.info("Start")

    # Set the clock period to 10 us (100 KHz)
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())

    dut._log.info("Reset clears the pin-output registers")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    assert dut.uo_out.value == 0
    assert dut.uio_out.value == 0

    # The bidirectional pins are configured as inputs (uio_oe == 0): the
    # direction is fixed at synthesis time (DR 0001 "Consequences") and no
    # admitted protocol pin plan drives it yet.
    assert dut.uio_oe.value == 0

    dut._log.info("Load the echo firmware over the serial load phase")
    await load_and_run(dut, ECHO_PROGRAM)

    dut._log.info("Firmware echo: ui_in appears on uo_out one loop later")
    # Loop period is 3 cycles (IN, OUT, JMP); allow one full extra
    # iteration for the new value to lap the pipeline of echoes.
    for value in (0x00, 0x5A, 0xA3, 0xFF, 0x00):
        dut.ui_in.value = value  # MODE stays low: ui_in is port 00 now
        await ClockCycles(dut.clk, 6)
        seen = int(dut.uo_out.value)
        assert seen == value, f"ui_in={value:#04x}: got uo_out={seen:#04x}"

    dut._log.info("Done")
