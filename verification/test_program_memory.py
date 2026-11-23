"""cocotb testbench for `protocol_program_memory` -- the program-storage and
serial load-phase module (target-spec row 6, issue #19).

This is the row 6 "Checked by" artifact `spec/target-spec.md` names: a
cocotb load-phase test that loads a known program serially and confirms
the bits landed where DR 0001 says they should. DR 0001 defines no
program-readback instruction (its 16-opcode table is exactly full), so the
read-back here is the fetch port itself -- the same instruction path the
core datapath will execute from -- exercised out-of-band by the testbench.

Re-verified against the SRAM-macro-backed module (issue #18)
------------------------------------------------------------
`spec/decision-records/0005-program-memory-implementation.md` replaced the
flip-flop storage array with the PDK's
`RM_IHPSG13_1P_256x16_c2_bm_bist` macro and flagged this bench explicitly:
*"`verification/test_program_memory.py` must be re-verified against the
macro-backed module, not assumed to carry over. Its readback assertions
are written against an asynchronous fetch port; under fetch-ahead the
fetched word arrives one cycle later."*

That re-verification is what this file now is. **Every load-protocol
contract below is unchanged** -- MSB-first shift, commit on the 16th
bit's own edge, mid-word discard, 256-word saturation, no mid-run
re-entry, and the cycle-exact 1 + 16*N + 1 edge accounting. The single
change is in `fetch_word()`: the macro's read is synchronous, so
presenting an address now costs one clock edge before `instr_word`
carries that word. Nothing else in this bench moved, and that is the
point -- if a contract had shifted, it would have shifted here.

Every contract checked is DR 0001 section "Program memory sizing and loading",
restated next to each test. Sub-cycle contracts DR 0001 leaves implicit are
pinned deliberately and named in the test that pins them:

- The first clock edge after `rst_n` release is the one **mode-sampling**
  edge; it does not shift a data bit. Shifting starts on the next edge.
  Total edge count for an N-word load is therefore
  1 (sampling) + 16*N (bits) + 1 (MODE-drop exit).
- The 16th bit of a word commits that word **on its own clock edge**, so a
  host holding MODE high for exactly 16*N bit cycles and dropping it loads
  exactly N words with no boundary ambiguity.
- A MODE drop mid-word discards the partial word (only complete 16-bit
  groups commit) and a fresh `rst_n` pulse realigns the word writer to
  address 0.
- Mode is latched at reset release and never re-sampled during run: a
  MODE-high reprogram attempt during run phase writes nothing.
- Load phase saturates at 256 words without wrapping over the program
  already loaded; MODE dropping low remains the only exit.

Driven by `klt functional-verification` (see
`verification/request-program-memory.json`) against
`rtl/protocol_program_memory.v`. This file is *input* to
`klt functional-verification` (the testbench module named by
`request.testbench.module`), not a pytest module -- pytest never collects
it, since it takes a cocotb-injected `dut` argument and only runs inside a
simulator process.

The pin-driving helpers this bench uses (`reset_release`,
`shift_one_bit`, `load_words`, `fetch_word`, `read_reg`) live in
`verification/program_memory_driver.py`, shared with the assembler
round-trip bench (issue #486); the contracts restated below are this
bench's to assert and are unchanged by the sharing.

The program patterns are deterministic (a fixed-seed LCG plus fixed
constants) so every run of this bench is byte-reproducible; the
"Statistical convention" in the evidence record this feeds is
deterministic, not sampled.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb.utils import get_sim_time

try:
    from program_memory_driver import (
        fetch_word,
        load_words,
        read_reg,
        reset_release,
        shift_one_bit,
    )
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from program_memory_driver import (
        fetch_word,
        load_words,
        read_reg,
        reset_release,
        shift_one_bit,
    )

CLK_PERIOD_NS = 10  # matches the 1ns/1ps timescale and a 50 MHz nominal


def lcg_words(count, seed=0x1359):
    """A deterministic, fixed-in-source program pattern. A plain 16-bit
    LCG keeps the pattern legible and reproducible without depending on a
    PRNG implementation; degenerate low bits do not matter because the
    tests check a position-to-content mapping, not the statistical quality
    of the values."""
    words = []
    state = seed
    for _ in range(count):
        state = (state * 251 + 0x4F) & 0xFFFF
        words.append(state)
    return words


@cocotb.test()
async def test_mode_low_at_release_enters_immediate_run(dut):
    """MODE low at reset release: load phase never entered; run phase
    begins at the mode-sampling edge itself (DR 0001: "MODE dropping low
    ... begins run phase" -- and MODE low at release means load phase is
    skipped entirely)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_release(dut, 0)
    assert await read_reg(dut, "run_phase") == 1, (
        "run_phase must rise at the mode-sampling edge when MODE is low"
    )
    await RisingEdge(dut.clk)  # leave the read-only region before writing

    # Serial traffic during a never-loaded run phase must not disturb the
    # phase line for 40 edges (2.5 words worth of bits).
    dut.serial_in.value = 1
    await ClockCycles(dut.clk, 40)
    assert await read_reg(dut, "run_phase") == 1


@cocotb.test()
async def test_single_word_bit_order_and_boundary_commit(dut):
    """One word, 0x1234, loaded MSB-first (an LSB-first or mis-assembled
    shifter would store something else -- 0x2C48 is the bit-reversal of
    0001_0010_0011_0100). MODE is dropped on the edge immediately after
    the 16th bit's edge, pinning the commit-on-16th-edge contract: the
    word must survive, because its commit happened on its own final bit's
    edge, not on a later edge the MODE drop could have pre-empted."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_release(dut, 1)
    assert await read_reg(dut, "run_phase") == 0, (
        "load phase entered; run must not be up"
    )
    # Exit the read-only region with a mid-period timer hop -- an extra
    # clock edge here would itself shift a data bit (the RTL shifts one
    # bit on EVERY load-phase edge, by contract), and a stray bit is
    # exactly the misalignment this test exists to catch.
    await Timer(1, unit="ns")

    for b in range(15, -1, -1):
        await shift_one_bit(dut, (0x1234 >> b) & 1)  # exactly 16 bit edges

    dut.mode_pin.value = 0
    await RisingEdge(dut.clk)  # MODE-drop edge (17th bit would go here)
    assert await read_reg(dut, "run_phase") == 1, "MODE drop must begin run phase"
    await Timer(1, unit="ns")  # writable again; fetch port settled

    got = await fetch_word(dut, 0)
    assert got == 0x1234, f"mem[0] = {got:#06x}, want 0x1234"


@cocotb.test()
async def test_full_program_load_and_fetch(dut):
    """A full 256-word program loads at the auto-incrementing address
    sequence starting at 0, one bit per rising edge, and reads back
    exactly through the fetch port at every address (DR 0001 row 6: 256
    x 16-bit words, addressed by an 8-bit PC). Also fixes the total load
    timing in simulated cycles: 1 sampling + 4096 bit + 1 exit edge --
    the cycle-exact number the evidence record cites."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    words = lcg_words(256)

    await reset_release(dut, 1)
    t_sampled_ns = get_sim_time("ns")  # right after the mode-sampling edge

    await load_words(dut, words)
    t_exit_ns = get_sim_time("ns")  # right after the MODE-drop exit edge

    # t_sampled is right after the sampling edge and t_exit right after
    # the drop edge, so the span is exactly 4096 bit edges + 1 drop edge.
    want_edges = 16 * 256 + 1
    assert t_exit_ns - t_sampled_ns == want_edges * CLK_PERIOD_NS, (
        f"load span {t_exit_ns - t_sampled_ns} ns, "
        f"want {want_edges} edges = {want_edges * CLK_PERIOD_NS} ns"
    )
    assert await read_reg(dut, "run_phase") == 1
    await RisingEdge(dut.clk)  # leave the read-only region before writing

    for addr in range(256):
        got = await fetch_word(dut, addr)
        assert got == words[addr], (
            f"mem[{addr}] = {got:#06x}, want {words[addr]:#06x}"
        )


@cocotb.test()
async def test_partial_word_discarded_and_writer_realigns(dut):
    """A MODE drop mid-word discards the partial word: only complete
    16-bit groups commit. Pass A seeds an observable canary at mem[1];
    pass B loads one word and then abandons 7 bits of a second word; the
    canary at mem[1] survives, and pass B's word lands at mem[0] -- so the
    partial bits neither committed anywhere nor misaligned the writer."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    # Pass A: two known words.
    await reset_release(dut, 1)
    await load_words(dut, [0xA5A5, 0x3C3C])
    assert await fetch_word(dut, 0) == 0xA5A5
    assert await fetch_word(dut, 1) == 0x3C3C

    # Pass B: one full word, then 7 bits of a second word, then MODE drop.
    await reset_release(dut, 1)
    dut.mode_pin.value = 1
    for b in range(15, -1, -1):
        await shift_one_bit(dut, (0x5A5A >> b) & 1)
    for b in range(14, 7, -1):  # 7 bits of 0x7E7E, MSB-first, then abandon
        await shift_one_bit(dut, (0x7E7E >> b) & 1)
    dut.mode_pin.value = 0
    await RisingEdge(dut.clk)

    assert await fetch_word(dut, 0) == 0x5A5A, "full word must commit"
    assert await fetch_word(dut, 1) == 0x3C3C, (
        "abandoned 7-bit partial must commit nowhere (canary word intact)"
    )


@cocotb.test()
async def test_no_midrun_reentry_without_reset(dut):
    """Mode is latched only at reset release, never sampled mid-run
    (DR 0001's no-race rule): once in run phase, driving MODE high again
    and streaming a full word's bits writes nothing -- only a fresh
    `rst_n` pulse with MODE high re-enters the load phase."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    await reset_release(dut, 1)
    await load_words(dut, [0xA5A5, 0x3C3C])  # canaries at mem[0], mem[1]
    assert await read_reg(dut, "run_phase") == 1

    # Reprogram attempt without reset: MODE high + a full word streamed.
    await RisingEdge(dut.clk)  # leave the read-only region before writing
    dut.mode_pin.value = 1
    for b in range(15, -1, -1):
        await shift_one_bit(dut, (0x0F0F >> b) & 1)
    dut.mode_pin.value = 0
    await RisingEdge(dut.clk)
    await ClockCycles(dut.clk, 5)

    assert await fetch_word(dut, 0) == 0xA5A5, (
        "mid-run MODE-high reprogram attempt must not touch memory"
    )
    assert await fetch_word(dut, 1) == 0x3C3C

    # The fresh-reset path does re-enter load (regression check that the
    # re-entry *mechanism* is intact, not merely suppressed forever).
    await reset_release(dut, 1)
    await load_words(dut, [0x0F0F])
    assert await fetch_word(dut, 0) == 0x0F0F


@cocotb.test()
async def test_saturation_at_256_words_no_wraparound(dut):
    """Streaming more than a full memory's worth of words with MODE held
    high saturates at 256 words: the last words shifted never wrap around
    over the program already loaded (destructive wrap would leave word
    300's tail over mem[0..43]). Then MODE drops and all 256 words read
    back exactly."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    words = lcg_words(300)

    await reset_release(dut, 1)
    await load_words(dut, words)  # 300 words' bits streamed in one pass
    assert await read_reg(dut, "run_phase") == 1
    await RisingEdge(dut.clk)  # leave the read-only region before writing

    for addr in range(256):
        got = await fetch_word(dut, addr)
        assert got == words[addr], (
            f"mem[{addr}] = {got:#06x}, want {words[addr]:#06x} "
            f"(wrapped/overwritten words would appear here)"
        )
