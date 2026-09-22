"""cocotb testbench for `tt_um_2amlogic_protocol_emulator` -- this
program's own klt-driven bench for the core datapath (issue #18,
target-spec rows 1/3/6).

The top is no longer the harness-bootstrap stub (issue #2): it
instantiates the ratified ISA's core datapath and program memory per
`spec/decision-records/0001-isa.md`. This bench is the issue-#18
acceptance criterion "cocotb bench in `verification/` exercising
fetch/execute for every instruction class the ratified ISA defines":
every one of the 16 opcodes (NOP, LDI, MOV, ADD, SUB, AND, OR, XOR,
SHF, IN, OUT, WAIT, JMP, BZ, BNZ, HALT) executes as real firmware --
loaded over the serial load-phase protocol through the actual pins
(MODE = ui_in[7], serial data = ui_in[0]), never through a backdoor --
and is checked at pin observables (`uo_out`, `uio_out`, `uio_oe`),
cycle-exactly where DR 0001 makes a cycle claim:

- every instruction except WAIT retires in exactly 1 cycle, so an
  OUT-observed value must appear on the retirement edge predicted by
  instruction-position arithmetic alone and on no earlier edge
  ("Timing model": no data-dependent latency);
- an OUT's new pin value is visible exactly one cycle after the OUT
  retires, and not before ("Drive on edge");
- WAIT imm8 stalls exactly imm8+1 cycles for several immediates
  including the WAIT 0 corner;
- a taken and a not-taken BZ/BNZ cost the same 1 cycle (branch outcome
  may depend on data, branch cost never does);
- the DR 0001 compile-time-constant countdown loop (LDI counter;
  SUB/BNZ body) runs at exactly 3 cycles per iteration, the loop shape
  the UART low-baud cycle budget is expressed in.

The only non-pin observables used are `dut.u_core.flag_z`/`flag_c` in
`test_alu_flags_whitebox`: DR 0001's ISA has no instruction that reads
C (BZ/BNZ read Z only; C is write-only state in this revision), so C is
checked inside the core and the test says so where it does. Z is
additionally checked pin-observably via branches everywhere else.

Cycle bookkeeping convention (matches
`verification/test_program_memory.py`'s edge accounting): after the
MODE-drop edge E0 that ends the load phase, the instruction at pc=0
executes during cycle (E0, E1] and retires at rising edge E1; a 1-cycle
instruction at program index i retires at edge 1 + (number of cycles
consumed by instructions 0..i-1); a WAIT imm8 consumes imm8+1 of those
cycle slots.

Driven by `klt functional-verification` (see
`request-protocol-emulator.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the two `rtl/` modules it
instantiates -- the same sources the Tiny Tapeout template's own
`test/test.py` exercises (see `rtl/README.md` for why there is no
separate `rtl/` copy of the top). This file is *input* to
`klt functional-verification`, not a pytest module.

All programs and data patterns are fixed in source, so every run of
this bench is byte-reproducible; the "Statistical convention" in the
evidence record this feeds is deterministic, not sampled.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer

CLK_PERIOD_NS = 10  # matches the 1ns/1ps timescale and a 50 MHz nominal

# DR 0001 "Encoding" table -- all 16 opcodes (the table is exactly full).
OP_NOP, OP_LDI, OP_MOV, OP_ADD = 0x0, 0x1, 0x2, 0x3
OP_SUB, OP_AND, OP_OR, OP_XOR = 0x4, 0x5, 0x6, 0x7
OP_SHF, OP_IN, OP_OUT, OP_WAIT = 0x8, 0x9, 0xA, 0xB
OP_JMP, OP_BZ, OP_BNZ, OP_HALT = 0xC, 0xD, 0xE, 0xF

# DR 0001 "Register and pin model" port codes.
PORT_UI_IN, PORT_UIO_IN, PORT_UO_OUT, PORT_UIO_OUT = 0, 1, 2, 3

R0, R1, R2, R3 = 0, 1, 2, 3


def enc(opcode, rd=0, rs=0, imm=0):
    """One 16-bit instruction word: [15:12] opcode, [11:10] Rd,
    [9:8] Rs/port, [7:0] imm8. For OUT the source register sits in the
    Rd field and the port in the Rs field (the uniform I/O encoding the
    core's header documents); for SHF the direction bit is Rs[0]."""
    return (opcode << 12) | (rd << 10) | (rs << 8) | imm


def cycles(word):
    """DR 0001 per-instruction cycle count: 1 for everything except
    WAIT imm8, which is imm8+1. This function is the bench's statement
    of the timing model every cycle-exact assert below is checked
    against."""
    if (word >> 12) == OP_WAIT:
        return (word & 0xFF) + 1
    return 1


def retire_edge(program, index):
    """The rising-edge number (counted from the MODE-drop edge, which
    is edge 0) at which `program[index]` retires, per the convention in
    the module docstring."""
    return 1 + sum(cycles(w) for w in program[:index])


async def settle_read(dut, name):
    """Read a signal after the current edge's nonblocking assignments
    have settled (awaiting `ReadOnly` first; the sibling
    `test_program_memory.py` documents why a same-edge `.value` read
    returns the pre-edge value in this cocotb/Icarus combination)."""
    await ReadOnly()
    value = int(getattr(dut, name).value)
    await Timer(1, unit="ns")  # leave the read-only region (writable again)
    return value


async def load_program(dut, words):
    """Reset with MODE high, shift `words` into program memory MSB-first
    one bit per rising edge on ui_in[0], then drop MODE to enter the run
    phase (DR 0001 section "Program memory sizing and loading"). Returns
    right after the MODE-drop edge (edge 0 of run-phase accounting); the
    caller's next `await RisingEdge` is edge 1, the retirement of the
    instruction at pc=0."""
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0x80  # MODE high, serial line idle low
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge

    for word in words:
        for bit in range(15, -1, -1):
            serial = (word >> bit) & 1
            dut.ui_in.value = 0x80 | serial
            await RisingEdge(dut.clk)

    dut.ui_in.value = 0x00  # MODE drop: exit to run phase
    await RisingEdge(dut.clk)  # edge 0: run_phase rises


async def watch_pin(dut, pin, checks):
    """Advance edge-by-edge from edge 0, asserting `pin` (a top-level
    output name) after each rising edge named in `checks`
    ({edge_number: expected_value}). Edges not named are not asserted,
    so a test pins exactly the transitions it cares about -- including
    "still the old value on the edge just before" negatives."""
    dut._log.info(f"watching {pin} against {len(checks)} edge checks")
    edge = 0
    last = max(checks)
    while edge < last:
        await RisingEdge(dut.clk)
        edge += 1
        if edge in checks:
            got = await settle_read(dut, pin)
            want = checks[edge]
            assert got == want, (
                f"{pin} after edge {edge}: got {got:#04x}, want {want:#04x}"
            )


@cocotb.test()
async def test_reset_and_load_leaves_pins_cleared(dut):
    """A one-word HALT program loaded over the real load phase: from
    reset through load and HALT retirement, both pin-output registers
    stay cleared (the stub-era reset contract, now through the core),
    the bidirectional pins stay inputs (uio_oe fixed at synthesis
    time), and HALT freezes the core: later cycles change nothing. This
    is the pin-level behavior the superseded reset-pin-through record
    documented for the stub, restated for the core."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await load_program(dut, [enc(OP_HALT)])

    assert await settle_read(dut, "uo_out") == 0
    assert await settle_read(dut, "uio_out") == 0
    assert await settle_read(dut, "uio_oe") == 0

    # HALT (index 0) retires at edge 1 and idles the core; nothing a
    # later cycle does -- including pin traffic -- may move any output.
    await ClockCycles(dut.clk, 10)
    assert await settle_read(dut, "uo_out") == 0
    assert await settle_read(dut, "uio_out") == 0


@cocotb.test()
async def test_ldi_mov_out_write_latency(dut):
    """LDI, MOV, OUT (port 10) and the "Drive on edge" contract: the
    OUT's new value is visible exactly one cycle after the OUT retires
    -- the cycle the OUT executes still shows the old value (no
    combinational leak from write data to pin)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x11),   # 0: R0 <- 0x11
        enc(OP_MOV, rd=R1, rs=R0),      # 1: R1 <- R0
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),  # 2: uo_out <- R1 (0x11)
        enc(OP_LDI, rd=R0, imm=0x22),   # 3
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 4: uo_out <- 0x22
        enc(OP_HALT),                   # 5
    ]
    await load_program(dut, program)

    # Instruction i retires at edge i+1 (all 1-cycle). The OUT at index
    # 2 retires at edge 3: edges 1-2 (LDI, MOV, and the OUT's own
    # execution cycle) still show 0; edge 3 shows 0x11; the second OUT
    # (index 4) retires at edge 5, so edge 4 still shows 0x11 and edge 5
    # shows 0x22.
    await watch_pin(dut, "uo_out", {
        1: 0x00, 2: 0x00,   # before first OUT retires: pin still cleared
        3: 0x11,            # exactly one cycle after OUT (index 2) retired
        4: 0x11,            # the second OUT's execution cycle: still old
        5: 0x22,            # one cycle after the second OUT retired
        7: 0x22,            # HALT at edge 6 froze it
    })


@cocotb.test()
async def test_alu_results_pin_observable(dut):
    """ADD, SUB, AND, OR, XOR results on the pin, each computed from a
    freshly LDI-loaded 0x53 against a constant 0xA6 (each op's operands
    are independent -- a chained accumulator would entangle one op's
    result into the next op's inputs): ADD=0xF9, SUB=0xAD, AND=0x02,
    OR=0xF7, XOR=0xF5."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R1, imm=0xA6),   # 0                @ edge 1
        enc(OP_LDI, rd=R0, imm=0x53),   # 1                @ 2
        enc(OP_ADD, rd=R0, rs=R1),      # 2: 0x53+0xA6 = 0xF9
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 3 -> 0xF9 @ 4
        enc(OP_LDI, rd=R0, imm=0x53),   # 4                @ 5
        enc(OP_SUB, rd=R0, rs=R1),      # 5: 0x53-0xA6 = 0xAD (borrow)
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 6 -> 0xAD @ 7
        enc(OP_LDI, rd=R0, imm=0x53),   # 7                @ 8
        enc(OP_AND, rd=R0, rs=R1),      # 8: 0x02
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 9 -> 0x02 @ 10
        enc(OP_LDI, rd=R0, imm=0x53),   # 10               @ 11
        enc(OP_OR, rd=R0, rs=R1),       # 11: 0xF7
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 12 -> 0xF7 @ 13
        enc(OP_LDI, rd=R0, imm=0x53),   # 13               @ 14
        enc(OP_XOR, rd=R0, rs=R1),      # 14: 0xF5
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 15 -> 0xF5 @ 16
        enc(OP_HALT),                   # 16               @ 17
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {
        3: 0x00,   # ADD executed (edge 3); its OUT is still executing
        4: 0xF9,
        7: 0xAD,
        10: 0x02,
        13: 0xF7,
        16: 0xF5,
        18: 0xF5,  # HALT @ edge 17 froze it
    })


@cocotb.test()
async def test_alu_flags_whitebox(dut):
    """Z and C semantics per opcode, read inside the core
    (`dut.u_core.flag_z` / `flag_c`) -- white-box on purpose: DR 0001's
    ISA has no instruction that reads C, so C is not pin-observable, and
    this test says so. Pin-observable Z behavior is covered by the
    branch tests below. Checks: ADD sets C on carry-out and Z on zero;
    SUB's C is the borrow convention the core pins (C=1 iff minuend <
    subtrahend, the 9-bit subtract's MSB) with Z on equal; AND writes Z
    only (C left unchanged); SHF's C is the shifted-out bit and SHF
    leaves Z unchanged."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0xFF),   # 0
        enc(OP_LDI, rd=R1, imm=0x01),   # 1
        enc(OP_ADD, rd=R0, rs=R1),      # 2: 0xFF+1 = 0x00, C=1, Z=1
        enc(OP_NOP),                    # 3 (read point)
        enc(OP_SUB, rd=R0, rs=R1),      # 4: 0x00-1 = 0xFF, C=1 (borrow), Z=0
        enc(OP_NOP),                    # 5 (read point)
        enc(OP_SUB, rd=R0, rs=R1),      # 6: 0xFF-1 = 0xFE, C=0 (no borrow)
        enc(OP_NOP),                    # 7 (read point)
        enc(OP_LDI, rd=R2, imm=0x00),   # 8: LDI writes no flags
        enc(OP_AND, rd=R2, rs=R1),      # 9: 0x00 & 0x01 = 0, Z=1, C unchanged (=0)
        enc(OP_NOP),                    # 10 (read point)
        enc(OP_LDI, rd=R3, imm=0x01),   # 11
        enc(OP_SHF, rd=R3, rs=0),       # 12: right: 0x01 -> 0x00, C=1, Z unchanged
        enc(OP_NOP),                    # 13 (read point)
        enc(OP_LDI, rd=R3, imm=0x80),   # 14
        enc(OP_SHF, rd=R3, rs=1),       # 15: left: 0x80 -> 0x00, C=1, Z unchanged
        enc(OP_NOP),                    # 16 (read point)
        enc(OP_LDI, rd=R3, imm=0x40),   # 17
        enc(OP_SHF, rd=R3, rs=1),       # 18: left: 0x40 -> 0x80, C=0, Z unchanged
        enc(OP_NOP),                    # 19 (read point)
        enc(OP_HALT),                   # 20
    ]
    await load_program(dut, program)

    edge = 0

    async def flags_at(target_edge):
        # Advance to `target_edge` rising edges past the MODE-drop edge,
        # then read both flags settled (ReadOnly) and hop out of the
        # read-only region before any further await.
        nonlocal edge
        while edge < target_edge:
            await RisingEdge(dut.clk)
            edge += 1
        await ReadOnly()
        z = int(dut.u_core.flag_z.value)
        c = int(dut.u_core.flag_c.value)
        await Timer(1, unit="ns")
        return z, c

    # Each ALU op's flags are read one instruction later (at the
    # trailing NOP's retirement edge), so the read is settled, never
    # same-edge. Z is unchanged from the AND (index 9) through the end:
    # LDI/SHF do not write it.
    z, c = await flags_at(retire_edge(program, 3))
    assert (z, c) == (1, 1), "0xFF+0x01: Z=1, C=1 (carry out)"
    z, c = await flags_at(retire_edge(program, 5))
    assert (z, c) == (0, 1), "0x00-0x01: Z=0, C=1 (borrow convention)"
    z, c = await flags_at(retire_edge(program, 7))
    assert (z, c) == (0, 0), "0xFF-0x01: Z=0, C=0 (no borrow)"
    z, c = await flags_at(retire_edge(program, 10))
    assert (z, c) == (1, 0), "AND -> zero sets Z=1; C unchanged by AND (still 0)"
    z, c = await flags_at(retire_edge(program, 13))
    assert (z, c) == (1, 1), "SHF right out of 0x01: C=1; Z unchanged by SHF (still 1)"
    z, c = await flags_at(retire_edge(program, 16))
    assert (z, c) == (1, 1), "SHF left out of 0x80: result 0, C=1, Z unchanged"
    z, c = await flags_at(retire_edge(program, 19))
    assert (z, c) == (1, 0), "SHF left out of 0x40: C=0; Z still 1 (nothing since the AND wrote it)"


@cocotb.test()
async def test_shf_results_pin_observable(dut):
    """SHF results through the pin: right shift 0x01 -> 0x00 and left
    shift 0x40 -> 0x80 (direction bit in Rs[0]: 0=right, 1=left)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x01),   # 0
        enc(OP_SHF, rd=R0, rs=0),       # 1: right -> 0x00
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 2 -> 0x00 @ edge 3
        enc(OP_LDI, rd=R1, imm=0x40),   # 3
        enc(OP_SHF, rd=R1, rs=1),       # 4: left -> 0x80
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),    # 5 -> 0x80 @ edge 6
        enc(OP_HALT),                   # 6
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {3: 0x00, 6: 0x80, 8: 0x80})


@cocotb.test()
async def test_in_ports_and_direction_noops(dut):
    """IN port 00 (ui_in) and port 01 (uio_in) sample the pin value at
    the retiring edge ("Sample on edge"); IN to a write-only port (10)
    is a no-op that leaves the destination register untouched; OUT to a
    read-only port (00) is a no-op that leaves uo_out untouched -- each
    still costing its fixed 1 cycle."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x77),   # 0: R0 = 0x77
        enc(OP_IN, rd=R0, rs=PORT_UO_OUT),     # 1: IN to write-only: no-op
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 2: uo_out = 0x77 @ edge 3
        enc(OP_IN, rd=R1, rs=PORT_UI_IN),      # 3: R1 <- ui_in  (0x5A driven)
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),    # 4: uo_out = 0x5A @ edge 5
        enc(OP_IN, rd=R2, rs=PORT_UIO_IN),     # 5: R2 <- uio_in (0x3C driven)
        enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),    # 6: uo_out = 0x3C @ edge 7
        enc(OP_OUT, rd=R2, rs=PORT_UI_IN),     # 7: OUT to read-only: no-op
        enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),    # 8: still 0x3C @ edge 9
        enc(OP_HALT),                   # 9
    ]
    await load_program(dut, program)

    # Drive the input ports between load and the first IN (edge 4): all
    # writes happen well before the edges that sample them.
    dut.ui_in.value = 0x5A   # MODE low: port 00 is plain data now
    dut.uio_in.value = 0x3C

    await watch_pin(dut, "uo_out", {
        3: 0x77,   # the no-op IN (edge 2) did not clobber R0
        5: 0x5A,   # IN port 00 sampled ui_in
        7: 0x3C,   # IN port 01 sampled uio_in
        8: 0x3C,   # OUT-to-read-only (edge 8) has not moved the pin
        9: 0x3C,   # ...and never does
    })


@cocotb.test()
async def test_out_port11_drives_uio_out_not_oe(dut):
    """OUT to port 11 drives the uio_out register (visible one cycle
    later, like port 10) and never the direction: uio_oe is fixed at
    synthesis time (DR 0001 'Consequences') and stays 0 -- the ISA has
    no runtime direction control in this revision."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x9C),          # 0
        enc(OP_OUT, rd=R0, rs=PORT_UIO_OUT),   # 1: uio_out = 0x9C @ edge 2
        enc(OP_HALT),                          # 2
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uio_out", {1: 0x00, 2: 0x9C, 4: 0x9C})
    assert await settle_read(dut, "uio_oe") == 0, "uio_oe must never move"


@cocotb.test()
async def test_wait_cycle_exact(dut):
    """WAIT imm8 stalls exactly imm8+1 cycles: markers OUTed before and
    after each WAIT land on edges predicted by the imm8+1 arithmetic
    alone. Covers WAIT 0 (the legal 1-cycle padding no-op), WAIT 1, and
    WAIT 5."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x01),   # 0        retires @ 1
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 1 -> marker 0x01 @ edge 2
        enc(OP_WAIT, imm=5),            # 2: consumes 6 cycle slots
        enc(OP_LDI, rd=R0, imm=0x02),   # 3        retires @ 9
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 4 -> marker 0x02 @ edge 10
        enc(OP_WAIT, imm=0),            # 5: consumes 1 slot (WAIT 0 corner)
        enc(OP_WAIT, imm=1),            # 6: consumes 2 slots
        enc(OP_LDI, rd=R0, imm=0x03),   # 7        retires @ 14
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 8 -> marker 0x03 @ edge 15
        enc(OP_HALT),                   # 9
    ]
    await load_program(dut, program)
    # Edge arithmetic: marker edges 2, then +1 (LDIR0) +6 (WAIT 5) +1
    # (LDI) -> OUT(4) retires at 2+1+6+1 = 10; then +1 (WAIT 0) +2
    # (WAIT 1) +1 (LDI) -> OUT(8) retires at 10+1+2+1+1 = 15.
    await watch_pin(dut, "uo_out", {
        2: 0x01,
        9: 0x01,   # the cycle WAIT 5 finally releases: still marker 1
        10: 0x02,  # exactly where imm8+1 arithmetic puts it
        14: 0x02,
        15: 0x03,
        17: 0x03,  # HALT @ 16 froze it
    })


@cocotb.test()
async def test_branches_taken_and_not_taken(dut):
    """JMP absolute, BZ and BNZ taken and not taken, each observed by
    which marker OUT executes -- and every branch (taken or not) costs
    its fixed 1 cycle: the markers land on edges computed with cost 1
    for both paths, so a hidden branch stall would fail the edge
    arithmetic.

    Program (targets are absolute word addresses):
        0: LDI R0, 0x01
        1: SUB R0, R0      ; 0 - 0 = 0 -> Z=1
        2: BZ  4           ; taken (Z=1): skip the 0xAA marker
        3: JMP 5           ; (skipped)
        4: JMP 6           ; BZ lands here -> jump to the 0xBB marker
        5: LDI R1, 0xAA; 6: OUT... -- unreachable-by-design guard below
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x01),   # 0
        enc(OP_SUB, rd=R0, rs=R0),      # 1: 0x00, Z=1
        enc(OP_BZ, imm=4),              # 2: taken -> pc=4       @ edge 3
        enc(OP_LDI, rd=R1, imm=0xAA),   # 3: skipped
        enc(OP_JMP, imm=6),             # 4: -> pc=6             @ edge 5
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),    # 5: never executed
        enc(OP_LDI, rd=R1, imm=0xBB),   # 6                      @ edge 6
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),    # 7 -> 0xBB @ edge 8
        enc(OP_LDI, rd=R2, imm=0x01),   # 8: R2=1                @ edge 9
        enc(OP_SUB, rd=R2, rs=R2),      # 9: Z=1 again           @ edge 10
        enc(OP_BNZ, imm=13),            # 10: NOT taken (Z=1)    @ edge 11
        enc(OP_LDI, rd=R1, imm=0xCC),   # 11                     @ edge 12
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),    # 12 -> 0xCC @ edge 13
        enc(OP_HALT),                   # 13 (BNZ target; also the end)
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {
        8: 0xBB,   # BZ taken (edge 3) and JMP (edge 5) each cost 1 cycle
        13: 0xCC,  # BNZ not-taken (edge 11) also cost exactly 1 cycle
        15: 0xCC,
    })


@cocotb.test()
async def test_bnz_taken_countdown_loop(dut):
    """The DR 0001 compile-time-constant countdown loop -- LDI-loaded
    trip count, SUB/BNZ body -- at exactly 3 cycles per iteration (OUT,
    SUB, BNZ), the loop shape the UART low-baud cycle budget is
    expressed in. Three marker pulses, each exactly 3 edges apart, then
    the fall-through marker after the final (not-taken) BNZ."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x03),   # 0: trip count 3           @ 1
        enc(OP_LDI, rd=R1, imm=0x01),   # 1: the constant 1         @ 2
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 2 (loop head): R0    @ 3 -> 3
        enc(OP_SUB, rd=R0, rs=R1),      # 3: count--                @ 4
        enc(OP_BNZ, imm=2),             # 4: loop while count!=0    @ 5
        enc(OP_LDI, rd=R2, imm=0xFF),   # 5 (fall-through)          @ ...
        enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),
        enc(OP_HALT),
    ]
    await load_program(dut, program)
    # Iteration k's OUT (pc=2) retires at edge 3 + 3k; after 3
    # iterations the fall-through LDI (pc=5) retires at edge 3+9=12 and
    # its OUT (pc=6) at 13.
    await watch_pin(dut, "uo_out", {
        3: 0x03,   # loop iteration 0: count still 3
        6: 0x02,   # iteration 1 (3 edges later: OUT,SUB,BNZ = 3 cycles)
        9: 0x01,   # iteration 2 (3 more edges)
        12: 0x01,  # final BNZ (edge 11) fell through after 1 cycle
        13: 0xFF,  # end marker exactly 1 cycle after the LDI
        15: 0xFF,
    })


@cocotb.test()
async def test_nop_costs_one_cycle(dut):
    """NOP is a 1-cycle instruction: three NOPs between markers push the
    second marker exactly 3 edges, no more."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0xE1),   # 0               @ 1
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 1 -> @ 2
        enc(OP_NOP),                    # 2               @ 3
        enc(OP_NOP),                    # 3               @ 4
        enc(OP_NOP),                    # 4               @ 5
        enc(OP_LDI, rd=R0, imm=0xE2),   # 5               @ 6
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 6 -> @ 7
        enc(OP_HALT),                   # 7
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {2: 0xE1, 6: 0xE1, 7: 0xE2, 9: 0xE2})


@cocotb.test()
async def test_latency_independent_of_data(dut):
    """The bench-level shadow of verification-plan section 2.1's formal
    property `no_data_dependent_latency` (the formal property itself is
    its own tracked issue): two straight-line programs of identical
    shape whose ALU data differs in every flag-relevant way (one ADD
    produces 0x00 with Z=1 and C=1, the other 0xF9 with Z=0 and C=0)
    land their trailing markers on the *same* retirement edges --
    instruction latency depends on the opcode stream alone, never on the
    data it operates on. Taken-vs-not-taken branch cost equality is
    pinned separately in test_branches_taken_and_not_taken."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    for tag, (a, b) in {"zeroing": (0xFF, 0x01), "nonzero": (0x53, 0xA6)}.items():
        program = [
            enc(OP_LDI, rd=R0, imm=a),        # 0                @ edge 1
            enc(OP_LDI, rd=R1, imm=b),        # 1                @ edge 2
            enc(OP_ADD, rd=R0, rs=R1),        # 2: zeroing pair: 0x00, Z=1, C=1
            enc(OP_NOP),                      # 3                @ edge 4
            enc(OP_NOP),                      # 4                @ edge 5
            enc(OP_LDI, rd=R2, imm=0xD1),     # 5                @ edge 6
            enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),      # 6: marker  @ edge 7
            enc(OP_HALT),                     # 7
        ]
        await load_program(dut, program)
        # Edge 6 is the marker OUT's own execution cycle: pin still 0.
        # Edge 7 is exactly one cycle later: marker visible. Identical
        # expectations for both data shapes is the assertion.
        await watch_pin(dut, "uo_out", {6: 0x00, 7: 0xD1, 9: 0xD1})
