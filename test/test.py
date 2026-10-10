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
# Issue #138 (DR 0013 layer 2) added `test_boot_rom` at the end: MODE low at
# reset no longer runs program memory, it runs the boot ROM. Issue #139 made
# strap 00 the UART load: TX (uo_out[0]) idles high and `test_boot_rom` loads
# a program over RX (ui_in[1]).
#
# The deep, cycle-exact per-opcode coverage lives in this program's own
# bench, verification/test_protocol_emulator.py (13 directed cases driven
# by `klt functional-verification`, with an append-only evidence record).
# This harness is the template's CI sign-off leg: enough to prove the
# loaded program really executes on the fabricated netlist, not a second
# copy of that suite.

import binascii

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
    # The bidirectional pins are inputs (uio_oe == 0): DR 0012's reset
    # state. Direction moves only through the UIO_DIR / UIO_OD control
    # registers, which this program never writes (test_control_space
    # below does).
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


# ---------------------------------------------------------------------------
# DR 0012 control space (issue #135), pin-only so it runs unchanged on the
# gate-level netlist. `WCTL k, Rs` is OUT (opcode 0xA) to port 00 with the
# control-register index k in imm8 and Rs in the [11:10] field; `RCTL Rd, k`
# is IN (opcode 0x9) from port 10 with k in imm8. The deep bench, with the
# cycle-exact stall checks and the reserved-index sweep, is
# verification/test_control_space.py; this is the sign-off-leg smoke of the
# same behaviour on whatever netlist the gds workflow just built.
PORT_UIO_OUT = 3
R2, R3 = 2, 3
K_UIO_DIR, K_UIO_OD, K_PM_ADDR, K_PM_DATA_HI, K_PM_DATA_LO = 0, 1, 2, 3, 4
K_RUN, K_PM_CRC_LO, K_PM_CRC_HI, K_BOOT_STATUS, K_HW_ID = 5, 6, 7, 8, 9


def wctl(k, rs):
    return enc(OP_OUT, rd=rs, rs=0, imm=k)


def rctl(rd, k):
    return enc(OP_IN, rd=rd, rs=2, imm=k)


def ctl_cycles(word):
    """DR 0001 / DR 0012 latency table, restated here for the edge
    arithmetic: WAIT imm8+1; WCTL PM_DATA_LO, WCTL RUN and RCTL PM_DATA_HI
    a fixed 2; everything else 1."""
    op, port, k = word >> 12, (word >> 8) & 3, word & 0xFF
    if op == OP_WAIT:
        return k + 1
    if op == OP_OUT and port == 0 and k in (K_PM_DATA_LO, K_RUN):
        return 2
    if op == OP_IN and port == 2 and k == K_PM_DATA_HI:
        return 2
    return 1


@cocotb.test()
async def test_control_space(dut):
    dut._log.info("Start (DR 0012 control space)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="us").start())

    program = []
    checks = []  # (instruction index, signal name, expected value, what)

    def emit(word):
        program.append(word)
        return len(program) - 1

    def show(k, want, what):
        """LDI R0, 0xEE; RCTL R0, k; OUT uo_out, R0 -> uo_out must read `want`."""
        emit(enc(OP_LDI, rd=R0, imm=0xEE))
        emit(rctl(R0, k))
        checks.append((emit(enc(OP_OUT, rd=R0, rs=PORT_UO_OUT)), "uo_out", want, what))

    # 1. Identity and reset state, read by firmware.
    show(K_UIO_DIR, 0x00, "UIO_DIR resets to 0")
    show(K_UIO_OD, 0x00, "UIO_OD resets to 0")
    show(K_BOOT_STATUS, 0x01, "BOOT_STATUS: serial-loaded, no boot ROM")
    show(K_HW_ID, 0x01, "HW_ID")
    crc_lo_at = len(program)
    show(K_PM_CRC_LO, None, "PM_CRC_LO over the serial load")
    show(K_PM_CRC_HI, None, "PM_CRC_HI over the serial load")

    # 2. Pin mode: push-pull on uio[3:0], then open-drain on uio[7] and
    #    uio[0] (the I2C images' SDA / SCL), which wins over push-pull.
    emit(enc(OP_LDI, rd=R1, imm=0x0F))
    checks.append((emit(wctl(K_UIO_DIR, R1)), "uio_oe", 0x0F, "UIO_DIR=0x0F: push-pull enables"))
    show(K_UIO_DIR, 0x0F, "UIO_DIR readback")
    emit(enc(OP_LDI, rd=R1, imm=0x81))
    checks.append((emit(enc(OP_OUT, rd=R1, rs=PORT_UIO_OUT)), "uio_oe", 0x0F,
                   "uio_out=0x81 does not move push-pull enables"))
    checks.append((emit(wctl(K_UIO_OD, R1)), "uio_oe", 0x0E,
                   "UIO_OD=0x81: OD wins on uio[0], released pins are not driven"))
    emit(enc(OP_LDI, rd=R1, imm=0x01))
    checks.append((emit(enc(OP_OUT, rd=R1, rs=PORT_UIO_OUT)), "uio_oe", 0x8E,
                   "uio_out=0x01: SDA (uio[7]) pulled low, SCL released"))
    emit(enc(OP_LDI, rd=R1, imm=0x00))
    emit(wctl(K_UIO_OD, R1))
    checks.append((emit(wctl(K_UIO_DIR, R1)), "uio_oe", 0x00, "all uio pins back to inputs"))

    # 3. Program memory: write a 3-word routine at 0xC0 through the control
    #    space, read word 0 back, check PM_ADDR and the CRC, then RUN it.
    routine = [
        enc(OP_LDI, rd=R2, imm=0xC3),
        enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),
        enc(OP_HALT),
    ]
    emit(enc(OP_LDI, rd=R1, imm=0xC0))
    emit(wctl(K_PM_ADDR, R1))
    emit(wctl(K_PM_CRC_LO, R1))  # clear: the CRC below covers the routine only
    for word in routine:
        emit(enc(OP_LDI, rd=R0, imm=word >> 8))
        emit(wctl(K_PM_DATA_HI, R0))
        emit(enc(OP_LDI, rd=R0, imm=word & 0xFF))
        emit(wctl(K_PM_DATA_LO, R0))   # 2 cycles
    show(K_PM_ADDR, 0xC3, "PM_ADDR auto-incremented over 3 writes")
    crc = binascii.crc_hqx(b"".join(bytes((w >> 8, w & 0xFF)) for w in routine), 0)
    show(K_PM_CRC_LO, crc & 0xFF, "PM_CRC_LO over the PM_DATA_LO writes (binascii.crc_hqx)")
    show(K_PM_CRC_HI, crc >> 8, "PM_CRC_HI over the PM_DATA_LO writes (binascii.crc_hqx)")
    # Read back routine word 1 (the OUT, 0xAA00): its low byte, 0x00, is
    # the last value on uo_out before the routine runs and shows 0xC3.
    emit(enc(OP_LDI, rd=R3, imm=0xC1))
    emit(wctl(K_PM_ADDR, R3))
    emit(rctl(R0, K_PM_DATA_HI))       # 2 cycles
    checks.append((emit(enc(OP_OUT, rd=R0, rs=PORT_UO_OUT)), "uo_out", routine[1] >> 8,
                   "PM_DATA_HI readback"))
    emit(rctl(R0, K_PM_DATA_LO))
    checks.append((emit(enc(OP_OUT, rd=R0, rs=PORT_UO_OUT)), "uo_out", routine[1] & 0xFF,
                   "PM_DATA_LO readback"))
    run_at = emit(wctl(K_RUN, R1))     # 2 cycles, PC <- 0xC0
    emit(enc(OP_LDI, rd=R3, imm=0xBD))  # must never execute
    emit(enc(OP_OUT, rd=R3, rs=PORT_UO_OUT))
    emit(enc(OP_HALT))

    # The serial-load CRC is over the image itself, so it is known only now.
    image_crc = binascii.crc_hqx(b"".join(bytes((w >> 8, w & 0xFF)) for w in program), 0)
    checks = [
        (i, sig, (image_crc & 0xFF if "PM_CRC_LO over the serial" in what else image_crc >> 8)
         if want is None else want, what)
        for i, sig, want, what in checks
    ]
    assert program[crc_lo_at + 1] == rctl(R0, K_PM_CRC_LO)

    def retire_edge(index):
        return 2 + sum(ctl_cycles(w) for w in program[:index])

    await load_program(dut, program)
    assert dut.uio_oe.value == 0, "nothing may drive a uio pin before a program asks"

    edge = 0
    for index, sig, want, what in sorted(checks):
        target = retire_edge(index)
        await step(dut, target - edge)
        edge = target
        got = int(getattr(dut, sig).value)
        assert got == want, f"{what}: {sig} after edge {edge} is {got:#04x}, want {want:#04x}"

    dut._log.info("Test RUN jumps into the routine written through PM_DATA")
    # RUN occupies edges run and run+1; the routine's LDI retires at run+2
    # and its OUT at run+3.
    target = retire_edge(run_at) + 3
    await step(dut, target - 1 - edge)
    assert dut.uo_out.value == (routine[1] & 0xFF), "the routine's OUT arrived early"
    await step(dut, 1)
    assert dut.uo_out.value == 0xC3, (
        f"routine written through the control space did not run: uo_out "
        f"{int(dut.uo_out.value):#04x}"
    )
    await step(dut, 10)
    assert dut.uo_out.value == 0xC3, "RUN fell through, or the routine's HALT did not hold"
    assert dut.uio_oe.value == 0


# ---------------------------------------------------------------------------
# DR 0013 layer 2 (issue #138): the boot ROM, pin-only so it runs unchanged
# on the gate-level netlist. With MODE (ui_in[7]) low at reset the core
# fetches from an on-chip ROM whose program reads the straps ui_in[6:5];
# strap 10 is the warm start (run program memory only if word 255 is the
# CRC-16/XMODEM of words 0..254). The deep bench -- unwritten and random
# memory, every strap, the corrupted-image set, the exact entry edge
# against an independent model of the boot program -- is
# verification/test_boot_rom.py; this is the sign-off-leg smoke of the same
# behaviour on whatever netlist the gds workflow just built.
STRAP_UART, STRAP_WARM = 0b00, 0b10
# firmware/asm/boot/boot_rom.asm: word 0 of a verified image executes this
# many cycles after the boot program's first instruction.
WARM_START_CYCLES = 2325


async def boot_reset(dut, straps):
    """Reset with MODE low and `straps` on ui_in[6:5]. Returns just after
    the mode-sampling edge, which starts the run phase (edge 0)."""
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = (straps << 5) | UART_RX  # the UART line idles high
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


# DR 0013 UART load (issue #139): RX ui_in[1], TX uo_out[0], 434 cycles per
# bit, 8N1; the frame is 0xA5, N-1, 2N bytes high first, CRC-16/XMODEM.
UART_RX = 0x02
UART_BIT = 434


async def uart_send(dut, data):
    """Play `data` as 8N1 frames on ui_in[1], back to back, leaving the
    other ui_in bits as they are."""
    base = int(dut.ui_in.value) & ~UART_RX
    for byte in data:
        for level in [0] + [(byte >> bit) & 1 for bit in range(8)] + [1]:
            dut.ui_in.value = base | (UART_RX if level else 0)
            await ClockCycles(dut.clk, UART_BIT)


async def uart_recv(dut, count, what):
    """Read `count` 8N1 bytes from uo_out[0]: wait for each start edge, then
    sample at the middle of every bit."""
    out = []
    for _ in range(count):
        for _ in range(60 * 10 * UART_BIT):
            await step(dut, 1)
            if int(dut.uo_out.value) & 1 == 0:
                break
        else:
            raise AssertionError(f"{what}: no start bit")
        await step(dut, UART_BIT // 2)
        value = 0
        for bit in range(8):
            await step(dut, UART_BIT)
            value |= (int(dut.uo_out.value) & 1) << bit
        await step(dut, UART_BIT)
        assert int(dut.uo_out.value) & 1 == 1, f"{what}: framing error"
        out.append(value)
    return bytes(out)


async def expect_uart_idle(dut, edges, what):
    """The UART loader is waiting: TX high, no uio pin driven, and nothing
    but TX on uo_out. (uio_out is its 0xFF guard, not a driven value.)"""
    for _ in range(edges):
        await step(dut, 1)
        assert dut.uo_out.value in (0, 1), f"{what}: uo_out moved off TX"
        assert dut.uio_oe.value == 0, f"{what}: a uio pin is driven"
    assert dut.uo_out.value == 1, f"{what}: TX is not idling high"


async def expect_quiet(dut, edges, what):
    """Every pin holds its reset value for `edges` more edges."""
    for _ in range(edges):
        await step(dut, 1)
        assert dut.uo_out.value == 0, f"{what}: uo_out moved"
        assert dut.uio_out.value == 0, f"{what}: uio_out moved"
        assert dut.uio_oe.value == 0, f"{what}: a uio pin is driven"


@cocotb.test()
async def test_boot_rom(dut):
    dut._log.info("Start (DR 0013 boot ROM and warm start)")
    cocotb.start_soon(Clock(dut.clk, 10, unit="us").start())

    program = [
        enc(OP_LDI, rd=R0, imm=0xEE),
        rctl(R0, K_BOOT_STATUS),
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),   # 0x01 serial-loaded / 0x00 warm-started
        enc(OP_LDI, rd=R0, imm=0xA5),
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),   # the marker
        enc(OP_HALT),
    ]
    body = program + [0x0000] * (255 - len(program))
    signature = binascii.crc_hqx(b"".join(bytes((w >> 8, w & 0xFF)) for w in body), 0)
    image = body + [signature]

    dut._log.info("Serial load (layer 1) runs the image and reads BOOT_STATUS = 0x01")
    await load_program(dut, image)
    await step(dut, 4)  # edge 4: the first OUT (index 2) has retired
    assert dut.uo_out.value == 0x01, (
        f"BOOT_STATUS after a serial load: uo_out {int(dut.uo_out.value):#04x}, want 0x01"
    )
    await step(dut, 2)  # edge 6: the marker
    assert dut.uo_out.value == 0xA5

    dut._log.info("MODE low, straps 00: the UART loader idles with TX high, the image is not run")
    await boot_reset(dut, STRAP_UART)
    await expect_uart_idle(dut, 64, "straps 00")

    dut._log.info("MODE low, straps 10: the verified image is warm-started")
    await boot_reset(dut, STRAP_WARM)
    # Word 0 retires at edge 2 + WARM_START_CYCLES; the marker (index 4) four
    # edges later. Until the edge before it, nothing moves: BOOT_STATUS is
    # 0x00 after a warm start, so the first OUT writes the reset value.
    marker_edge = 2 + WARM_START_CYCLES + 4
    await expect_quiet(dut, marker_edge - 1, "warm start, before the marker")
    await step(dut, 1)
    assert dut.uo_out.value == 0xA5, (
        f"warm start did not run the verified image on edge {marker_edge}: "
        f"uo_out {int(dut.uo_out.value):#04x}"
    )

    dut._log.info("MODE low, straps 10, one flipped bit: the image is never run")
    corrupted = list(image)
    corrupted[100] ^= 0x0010
    await load_program(dut, corrupted)
    await boot_reset(dut, STRAP_WARM)
    await expect_uart_idle(dut, marker_edge + 64, "corrupted image")

    dut._log.info("...the failed warm start fell through to the UART loader: it loads a program sent over RX, answering 0x06 + its CRC, then runs it")
    uart_image = [enc(OP_LDI, rd=R0, imm=0x3C), enc(OP_OUT, rd=R0, rs=PORT_UO_OUT), enc(OP_HALT)]
    body = b"".join(bytes((w >> 8, w & 0xFF)) for w in uart_image)
    crc = binascii.crc_hqx(body, 0)
    frame = bytes((0xA5, len(uart_image) - 1)) + body + bytes((crc >> 8, crc & 0xFF))
    reply = cocotb.start_soon(uart_recv(dut, 3, "UART reply"))
    await uart_send(dut, frame)
    got = await reply
    assert got == bytes((0x06, crc >> 8, crc & 0xFF)), f"UART reply {got.hex()}"
    await step(dut, UART_BIT)  # the rest of the stop bit, then the hand-over and two instructions
    assert dut.uo_out.value == 0x3C, f"the UART-loaded image did not run: {int(dut.uo_out.value):#04x}"
    assert dut.uio_oe.value == 0
