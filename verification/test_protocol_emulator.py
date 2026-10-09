"""cocotb testbench for `tt_um_2amlogic_protocol_emulator` -- this
program's own klt-driven bench for the ISA core datapath (issue #18,
target-spec rows 1/3/6).

The top is no longer the harness-bootstrap stub (issue #2): it
instantiates the ISA's core datapath and its SRAM-macro-backed program
memory per `spec/decision-records/0001-isa.md`, with the fetch-ahead
amendment of
`spec/decision-records/0005-program-memory-implementation.md`. This bench
is the issue-#18 acceptance criterion "cocotb bench in `verification/`
exercising fetch/execute for every instruction class the ISA defines":
every one of the 16 opcodes (NOP, LDI, MOV, ADD, SUB, AND, OR, XOR, SHF,
IN, OUT, WAIT, JMP, BZ, BNZ, HALT) executes as real firmware -- loaded
over the serial load-phase protocol through the actual pins (MODE =
ui_in[7], serial data = ui_in[0]), never through a backdoor -- and is
checked at pin observables (`uo_out`, `uio_out`, `uio_oe`), cycle-exactly
where DR 0001 makes a cycle claim:

- every instruction except WAIT retires in exactly 1 cycle, so an
  OUT-observed value must appear on the retirement edge predicted by
  instruction-position arithmetic alone and on no earlier edge
  ("Timing model": no data-dependent latency);
- an OUT's new pin value is visible exactly one cycle after the OUT
  executes, and not before ("Drive on edge");
- WAIT imm8 stalls exactly imm8+1 cycles for several immediates
  including the WAIT 0 corner;
- a taken and a not-taken BZ/BNZ cost the same 1 cycle, and neither
  costs a fetch bubble under fetch-ahead (branch outcome may depend on
  data, branch cost never does);
- the DR 0001 compile-time-constant countdown loop (LDI counter;
  SUB/BNZ body) runs at exactly 3 cycles per iteration, the loop shape
  the UART low-baud cycle budget is expressed in.

Fetch-ahead cycle bookkeeping (DR 0005, "Amendment to DR 0001")
---------------------------------------------------------------
The program memory is the PDK's `RM_IHPSG13_1P_256x16_c2_bm_bist` macro,
whose read is synchronous with one-cycle data access, so the core
presents the *next* instruction's address one cycle ahead. That costs
zero cycles per instruction but a fixed **+1 cycle at run-phase entry**:
the first run-phase cycle presents address 0 without executing, and the
instruction at address 0 executes in the second.

Numbering edges from the MODE-drop edge E0 (which raises `run_phase`):

    E0  -- MODE drops, run phase begins
    E1  -- fetch-ahead priming edge: address 0 is captured, nothing executes
    E2  -- the instruction at pc=0 retires
    ...

so a 1-cycle instruction at program index i retires at edge
`2 + (cycles consumed by instructions 0..i-1)`, and a WAIT imm8 consumes
imm8+1 of those cycle slots. `RUN_ENTRY_EDGES` below is that leading `2`,
and it is the single place the +1 is expressed --
`test_run_entry_fetch_ahead_costs_exactly_one_cycle` pins it directly, so
a regression to a same-cycle-fetch model (or to a *two*-cycle entry)
fails there first rather than shifting every other test silently.

The only non-pin observables used are `dut.u_core.flag_z`/`flag_c` in
`test_alu_flags_whitebox`: DR 0001's ISA has no instruction that reads
C (BZ/BNZ read Z only; C is write-only state in this revision), so C is
checked inside the core and the test says so where it does. Z is
additionally checked pin-observably via branches everywhere else.

Driven by `klt functional-verification` (see
`request-protocol-emulator.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the two `rtl/` modules it
instantiates and the vendored PDK macro model (`rtl/vendor/`, see its
README) -- the same sources the Tiny Tapeout template's own `test/test.py`
exercises. This file is *input* to `klt functional-verification`, not a
pytest module.

All programs and data patterns are fixed in source, so every run of this
bench is byte-reproducible; the "Statistical convention" in the evidence
record this feeds is deterministic, not sampled.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer

CLK_PERIOD_NS = 10  # matches the 1ns/1ps timescale and a 50 MHz nominal

# DR 0005's fetch-ahead run-phase entry cost, in rising edges counted from
# the MODE-drop edge, to the retirement of the instruction at pc=0. See the
# module docstring: E1 primes the fetch, E2 retires instruction 0.
RUN_ENTRY_EDGES = 2

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
    against. DR 0005 changed no entry in that table."""
    if (word >> 12) == OP_WAIT:
        return (word & 0xFF) + 1
    return 1


def retire_edge(program, index):
    """The rising-edge number (counted from the MODE-drop edge, which is
    edge 0) at which `program[index]`'s execute cycle ends, per the
    fetch-ahead convention in the module docstring. For every 1-cycle
    instruction that is its retirement edge; for a WAIT it is the edge
    ending the WAIT's own execute cycle, with its imm8 stall cycles
    following."""
    return RUN_ENTRY_EDGES + sum(cycles(w) for w in program[:index])


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
    caller's next `await RisingEdge` is edge 1, the fetch-ahead priming
    edge, and the one after that is edge 2, the retirement of the
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
async def test_run_entry_fetch_ahead_costs_exactly_one_cycle(dut):
    """DR 0005's one spec-visible timing consequence, pinned on its own:
    run-phase entry costs a fixed +1 cycle, and exactly one.

    The OUT at program index 1 retires at edge 3, not edge 2. Edge 2 is
    the retirement of the LDI at index 0 -- under the superseded
    same-cycle-fetch model of DR 0001 as authored, the OUT would have
    retired there and `uo_out` would already read 0xA5. Asserting 0x00 at
    edge 2 and 0xA5 at edge 3 therefore fails in both directions: a
    regression to same-cycle fetch fails the edge-2 check, and a
    two-cycle (or bubbled) entry fails the edge-3 check."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0xA5),        # 0: retires @ edge 2
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 1: retires @ edge 3 -> pin 0xA5
        enc(OP_HALT),                        # 2: @ edge 4
    ]
    assert retire_edge(program, 0) == 2
    assert retire_edge(program, 1) == 3
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {1: 0x00, 2: 0x00, 3: 0xA5, 5: 0xA5})


@cocotb.test()
async def test_reset_and_load_leaves_pins_cleared(dut):
    """A one-word HALT program loaded over the real load phase: from
    reset through load and HALT retirement, both pin-output registers
    stay cleared (the stub-era reset contract, now through the core),
    the bidirectional pins stay inputs (uio_oe = 0, DR 0012's reset
    state, which this program never changes), and HALT freezes the core: later cycles change nothing. This
    is the pin-level behavior the superseded reset-pin-through record
    documented for the stub, restated for the core."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await load_program(dut, [enc(OP_HALT)])

    assert await settle_read(dut, "uo_out") == 0
    assert await settle_read(dut, "uio_out") == 0
    assert await settle_read(dut, "uio_oe") == 0

    # HALT (index 0) retires at edge 2 and idles the core; nothing a
    # later cycle does -- including pin traffic -- may move any output.
    await ClockCycles(dut.clk, 10)
    assert await settle_read(dut, "uo_out") == 0
    assert await settle_read(dut, "uio_out") == 0
    assert await settle_read(dut, "uio_oe") == 0


@cocotb.test()
async def test_ldi_mov_out_write_latency(dut):
    """LDI, MOV, OUT (port 10) and the "Drive on edge" contract: the
    OUT's new value is visible exactly one cycle after the OUT executes
    -- the cycle the OUT executes still shows the old value (no
    combinational leak from write data to pin)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x11),        # 0: R0 <- 0x11        @ edge 2
        enc(OP_MOV, rd=R1, rs=R0),           # 1: R1 <- R0          @ 3
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),  # 2: uo_out <- 0x11    @ 4
        enc(OP_LDI, rd=R0, imm=0x22),        # 3                    @ 5
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 4: uo_out <- 0x22    @ 6
        enc(OP_HALT),                        # 5                    @ 7
    ]
    await load_program(dut, program)

    # Instruction i retires at edge i+2 (all 1-cycle). Edges 1-3 (the
    # priming edge, the LDI, the MOV) still show 0; edge 4 shows 0x11 --
    # one cycle after the OUT at index 2 executed; edge 5 is the second
    # OUT's own execution cycle, so still 0x11; edge 6 shows 0x22.
    await watch_pin(dut, "uo_out", {
        1: 0x00, 2: 0x00, 3: 0x00,
        4: 0x11,
        5: 0x11,
        6: 0x22,
        8: 0x22,   # HALT at edge 7 froze it
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
        enc(OP_LDI, rd=R1, imm=0xA6),          # 0                   @ edge 2
        enc(OP_LDI, rd=R0, imm=0x53),          # 1                   @ 3
        enc(OP_ADD, rd=R0, rs=R1),             # 2: 0x53+0xA6 = 0xF9 @ 4
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 3 -> 0xF9           @ 5
        enc(OP_LDI, rd=R0, imm=0x53),          # 4                   @ 6
        enc(OP_SUB, rd=R0, rs=R1),             # 5: 0x53-0xA6 = 0xAD @ 7
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 6 -> 0xAD           @ 8
        enc(OP_LDI, rd=R0, imm=0x53),          # 7                   @ 9
        enc(OP_AND, rd=R0, rs=R1),             # 8: 0x02             @ 10
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 9 -> 0x02           @ 11
        enc(OP_LDI, rd=R0, imm=0x53),          # 10                  @ 12
        enc(OP_OR, rd=R0, rs=R1),              # 11: 0xF7            @ 13
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 12 -> 0xF7          @ 14
        enc(OP_LDI, rd=R0, imm=0x53),          # 13                  @ 15
        enc(OP_XOR, rd=R0, rs=R1),             # 14: 0xF5            @ 16
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),    # 15 -> 0xF5          @ 17
        enc(OP_HALT),                          # 16                  @ 18
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {
        4: 0x00,   # ADD executed (edge 4); its OUT has not run yet
        5: 0xF9,
        8: 0xAD,
        11: 0x02,
        14: 0xF7,
        17: 0xF5,
        19: 0xF5,  # HALT @ edge 18 froze it
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
        enc(OP_LDI, rd=R0, imm=0x01),        # 0                @ edge 2
        enc(OP_SHF, rd=R0, rs=0),            # 1: right -> 0x00 @ 3
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 2 -> 0x00        @ 4
        enc(OP_LDI, rd=R1, imm=0x40),        # 3                @ 5
        enc(OP_SHF, rd=R1, rs=1),            # 4: left -> 0x80  @ 6
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),  # 5 -> 0x80        @ 7
        enc(OP_HALT),                        # 6                @ 8
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {4: 0x00, 7: 0x80, 9: 0x80})


@cocotb.test()
async def test_in_ports_and_direction_noops(dut):
    """IN port 00 (ui_in) and port 01 (uio_in) sample the pin value at
    the retiring edge ("Sample on edge"); IN from the reserved write-only
    port (11) is a no-op that leaves the destination register untouched;
    OUT to the reserved read-only port (01) is a no-op that leaves uo_out
    untouched -- each still costing its fixed 1 cycle.

    Issue #135 / DR 0012: before the control space existed this test used
    the *other* two no-op encodings (IN port 10, OUT port 00). DR 0012
    gives those a meaning (RCTL / WCTL -- `IN R0, port 10, imm 0` is now
    `RCTL R0, UIO_DIR` and would load 0x00), so the no-op claim moved to
    the two encodings DR 0012 keeps reserved. The control space itself is
    `test_control_space.py`'s subject."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x77),        # 0: R0 = 0x77           @ edge 2
        enc(OP_IN, rd=R0, rs=PORT_UIO_OUT),  # 1: IN from port 11     @ 3
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 2: uo_out = 0x77       @ 4
        enc(OP_IN, rd=R1, rs=PORT_UI_IN),    # 3: R1 <- ui_in  (0x5A) @ 5
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),  # 4: uo_out = 0x5A       @ 6
        enc(OP_IN, rd=R2, rs=PORT_UIO_IN),   # 5: R2 <- uio_in (0x3C) @ 7
        enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),  # 6: uo_out = 0x3C       @ 8
        enc(OP_OUT, rd=R2, rs=PORT_UIO_IN),  # 7: OUT to port 01      @ 9
        enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),  # 8: still 0x3C          @ 10
        enc(OP_HALT),                        # 9                      @ 11
    ]
    await load_program(dut, program)

    # Drive the input ports between load and the first IN (edge 5): all
    # writes happen well before the edges that sample them. ui_in[7]
    # (MODE) stays low in both patterns, so no reprogram is attempted.
    dut.ui_in.value = 0x5A   # MODE low: port 00 is plain data now
    dut.uio_in.value = 0x3C

    await watch_pin(dut, "uo_out", {
        4: 0x77,   # the no-op IN (edge 3) did not clobber R0
        6: 0x5A,   # IN port 00 sampled ui_in
        8: 0x3C,   # IN port 01 sampled uio_in
        9: 0x3C,   # OUT-to-read-only (edge 9) has not moved the pin
        10: 0x3C,  # ...and never does
    })


@cocotb.test()
async def test_out_port11_drives_uio_out_not_oe(dut):
    """OUT to port 11 drives the uio_out register (visible one cycle
    later, like port 10) and never the direction: uio_oe moves only
    through DR 0012's UIO_DIR / UIO_OD control registers (issue #135),
    which reset to 0 and which this program never writes, so uio_oe
    stays 0 here. `test_control_space.py` covers the pin-mode logic."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x9C),          # 0                  @ edge 2
        enc(OP_OUT, rd=R0, rs=PORT_UIO_OUT),   # 1: uio_out = 0x9C  @ 3
        enc(OP_HALT),                          # 2                  @ 4
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uio_out", {2: 0x00, 3: 0x9C, 5: 0x9C})
    assert await settle_read(dut, "uio_oe") == 0, "uio_oe must never move"


@cocotb.test()
async def test_wait_cycle_exact(dut):
    """WAIT imm8 stalls exactly imm8+1 cycles: markers OUTed before and
    after each WAIT land on edges predicted by the imm8+1 arithmetic
    alone. Covers WAIT 0 (the legal 1-cycle padding no-op), WAIT 1, and
    WAIT 5. Under fetch-ahead the WAIT holds the fetch address for the
    stall, so the instruction after it executes in the cycle
    immediately following the last stall cycle -- no bubble."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x01),        # 0                      @ edge 2
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 1 -> marker 0x01       @ 3
        enc(OP_WAIT, imm=5),                 # 2: consumes 6 slots    @ 4..9
        enc(OP_LDI, rd=R0, imm=0x02),        # 3                      @ 10
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 4 -> marker 0x02       @ 11
        enc(OP_WAIT, imm=0),                 # 5: consumes 1 slot     @ 12
        enc(OP_WAIT, imm=1),                 # 6: consumes 2 slots    @ 13..14
        enc(OP_LDI, rd=R0, imm=0x03),        # 7                      @ 15
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 8 -> marker 0x03       @ 16
        enc(OP_HALT),                        # 9                      @ 17
    ]
    assert retire_edge(program, 4) == 11
    assert retire_edge(program, 8) == 16
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {
        3: 0x01,
        10: 0x01,  # the cycle WAIT 5 finally releases into: still marker 1
        11: 0x02,  # exactly where imm8+1 arithmetic puts it
        15: 0x02,
        16: 0x03,
        18: 0x03,  # HALT @ 17 froze it
    })


@cocotb.test()
async def test_branches_taken_and_not_taken(dut):
    """JMP absolute, BZ and BNZ taken and not taken, each observed by
    which marker OUT executes -- and every branch (taken or not) costs
    its fixed 1 cycle with no fetch bubble: the markers land on edges
    computed with cost 1 for both paths, so a branch stall introduced by
    the fetch-ahead rework would fail the edge arithmetic here first.

    Execution order (absolute word addresses):
        pc=0 LDI R0,1     | pc=1 SUB R0,R0 (Z=1)  | pc=2 BZ 4 (taken)
        pc=4 JMP 6        | pc=6 LDI R1,0xBB      | pc=7 OUT -> 0xBB
        pc=8 LDI R2,1     | pc=9 SUB R2,R2 (Z=1)  | pc=10 BNZ 13 (not taken)
        pc=11 LDI R1,0xCC | pc=12 OUT -> 0xCC     | pc=13 HALT
    pc=3 and pc=5 are skipped by construction; if either ever executed,
    0xAA would reach the pin instead of 0xBB.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x01),        # 0                    @ edge 2
        enc(OP_SUB, rd=R0, rs=R0),           # 1: 0x00, Z=1         @ 3
        enc(OP_BZ, imm=4),                   # 2: taken -> pc=4     @ 4
        enc(OP_LDI, rd=R1, imm=0xAA),        # 3: skipped
        enc(OP_JMP, imm=6),                  # 4: -> pc=6           @ 5
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),  # 5: never executed
        enc(OP_LDI, rd=R1, imm=0xBB),        # 6                    @ 6
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),  # 7 -> 0xBB            @ 7
        enc(OP_LDI, rd=R2, imm=0x01),        # 8                    @ 8
        enc(OP_SUB, rd=R2, rs=R2),           # 9: Z=1 again         @ 9
        enc(OP_BNZ, imm=13),                 # 10: NOT taken        @ 10
        enc(OP_LDI, rd=R1, imm=0xCC),        # 11                   @ 11
        enc(OP_OUT, rd=R1, rs=PORT_UO_OUT),  # 12 -> 0xCC           @ 12
        enc(OP_HALT),                        # 13 (BNZ target, end) @ 13
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {
        6: 0x00,   # BZ taken (edge 4) and JMP (edge 5) each cost exactly 1 cycle
        7: 0xBB,
        11: 0xBB,  # BNZ not-taken (edge 10) also cost exactly 1 cycle
        12: 0xCC,
        14: 0xCC,  # HALT @ 13 froze it
    })


@cocotb.test()
async def test_bnz_taken_countdown_loop(dut):
    """The DR 0001 compile-time-constant countdown loop -- LDI-loaded
    trip count, SUB/BNZ body -- at exactly 3 cycles per iteration (OUT,
    SUB, BNZ), the loop shape the UART low-baud cycle budget is
    expressed in. Three marker pulses, each exactly 3 edges apart, then
    the fall-through marker after the final (not-taken) BNZ. A
    fetch-ahead bubble on the taken branch would stretch the loop to 4
    cycles per iteration and fail every marker after the first."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0x03),        # 0: trip count 3        @ edge 2
        enc(OP_LDI, rd=R1, imm=0x01),        # 1: the constant 1      @ 3
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 2 (loop head)          @ 4, 7, 10
        enc(OP_SUB, rd=R0, rs=R1),           # 3: count--             @ 5, 8, 11
        enc(OP_BNZ, imm=2),                  # 4: loop while count!=0 @ 6, 9, 12
        enc(OP_LDI, rd=R2, imm=0xFF),        # 5 (fall-through)       @ 13
        enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),  # 6                      @ 14
        enc(OP_HALT),                        # 7                      @ 15
    ]
    await load_program(dut, program)
    # Iteration k's OUT (pc=2) retires at edge 4 + 3k; after 3
    # iterations the fall-through LDI (pc=5) retires at edge 13 and its
    # OUT (pc=6) at edge 14.
    await watch_pin(dut, "uo_out", {
        4: 0x03,   # loop iteration 0: count still 3
        7: 0x02,   # iteration 1 (3 edges later: OUT,SUB,BNZ = 3 cycles)
        10: 0x01,  # iteration 2 (3 more edges)
        13: 0x01,  # final BNZ (edge 12) fell through after 1 cycle
        14: 0xFF,  # end marker exactly 1 cycle after the LDI
        16: 0xFF,
    })


@cocotb.test()
async def test_nop_costs_one_cycle(dut):
    """NOP is a 1-cycle instruction: three NOPs between markers push the
    second marker exactly 3 edges, no more."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    program = [
        enc(OP_LDI, rd=R0, imm=0xE1),        # 0    @ edge 2
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 1    @ 3
        enc(OP_NOP),                         # 2    @ 4
        enc(OP_NOP),                         # 3    @ 5
        enc(OP_NOP),                         # 4    @ 6
        enc(OP_LDI, rd=R0, imm=0xE2),        # 5    @ 7
        enc(OP_OUT, rd=R0, rs=PORT_UO_OUT),  # 6    @ 8
        enc(OP_HALT),                        # 7    @ 9
    ]
    await load_program(dut, program)
    await watch_pin(dut, "uo_out", {3: 0xE1, 7: 0xE1, 8: 0xE2, 10: 0xE2})


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
        dut._log.info(f"latency-independence pass: {tag}")
        program = [
            enc(OP_LDI, rd=R0, imm=a),           # 0                @ edge 2
            enc(OP_LDI, rd=R1, imm=b),           # 1                @ 3
            enc(OP_ADD, rd=R0, rs=R1),           # 2                @ 4
            enc(OP_NOP),                         # 3                @ 5
            enc(OP_NOP),                         # 4                @ 6
            enc(OP_LDI, rd=R2, imm=0xD1),        # 5                @ 7
            enc(OP_OUT, rd=R2, rs=PORT_UO_OUT),  # 6: marker        @ 8
            enc(OP_HALT),                        # 7                @ 9
        ]
        await load_program(dut, program)
        # Edge 7 is the marker OUT's own execution cycle: pin still 0.
        # Edge 8 is exactly one cycle later: marker visible. Identical
        # expectations for both data shapes is the assertion.
        await watch_pin(dut, "uo_out", {7: 0x00, 8: 0xD1, 10: 0xD1})
