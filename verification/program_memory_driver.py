"""Shared pin driver for the module-level `protocol_program_memory` benches.

`verification/test_program_memory.py` (the DR 0001 load-phase bench) and
`verification/test_firmware_roundtrip.py` (the DR 0003 assembler
round-trip bench) drive the same stand-alone DUT with the same
pin-sequencing decisions: reset release with MODE pre-driven and the
run-phase ports tied idle, the MSB-first one-bit-per-edge serial shift
with the MODE drop on its own edge, the synchronous fetch read, and the
post-NBA registered-output read. Those routines live here once (issue
#486) so the next port or timing change has one place to update; each
bench imports what it uses and keeps its own assertions -- the boundary,
saturation, image-freshness and cycle-count checks are the benches', not
this module's. Every contract the helpers embody is DR 0001's load
protocol as pinned by the load-phase bench; the move changed no edge.

`verification/test_loadseq.py` (the host-loader replay) deliberately
drives its own clock and pins, so it imports nothing from here: it
checks the host-generated load sequence independently.

This is not a cocotb testbench module (no `@cocotb.test()` lives here)
and not a pytest module: `klt functional-verification` never names it.
The two benches import it, and the evidence records hash it as a
provenance input.
"""

from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer


async def reset_release(dut, mode, settle_cycles=0):
    """Async-reset release with `mode` pre-driven, per DR 0001: "on release
    of rst_n, the core samples ui_in[7] (MODE)". The next rising edge after
    release is the mode-sampling edge; `settle_cycles` adds idle edges
    after it before the caller starts doing anything else.

    Lives here rather than in `_dut.py` (which drives the Tiny Tapeout
    top's pin names -- `ui_in`, `ena` -- that this module-level DUT does
    not have); the two reset helpers check different interfaces on
    purpose.
    """
    dut.mode_pin.value = mode
    dut.serial_in.value = 0
    # DR 0012's run-phase data-access port (issue #135) is the core's to
    # drive; this module-level bench has no core, so tie it idle.
    dut.pm_we.value = 0
    dut.pm_re.value = 0
    dut.pm_addr.value = 0
    dut.pm_wdata.value = 0
    dut.pm_crc_clr.value = 0
    dut.fetch_addr.value = 0
    # DR 0013 (issue #138): the core lowers `fetch_en` while it fetches from
    # the boot ROM. The benches read the array through the fetch port, so
    # they hold the port enabled, as the core does once it runs from memory.
    dut.fetch_en.value = 1
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge
    if settle_cycles:
        await ClockCycles(dut.clk, settle_cycles)


async def shift_one_bit(dut, bit):
    """Present one serial bit and advance exactly one rising edge."""
    dut.serial_in.value = bit
    await RisingEdge(dut.clk)


async def load_words(dut, words):
    """Shift `words` into the DUT, MSB-first, one bit per rising edge with
    MODE held high, then drop MODE on its own edge to exit the load phase.

    The caller must have just finished `reset_release(dut, 1, ...)`; MODE
    is left low and the DUT in run phase on return."""
    dut.mode_pin.value = 1
    for word in words:
        for b in range(15, -1, -1):
            await shift_one_bit(dut, (word >> b) & 1)
    dut.mode_pin.value = 0
    await RisingEdge(dut.clk)  # the MODE-drop edge: exit to run phase


async def fetch_word(dut, addr):
    """Synchronous fetch read -- the same instruction path the core's
    fetch-and-execute uses at addresses it will run from.

    DR 0005's one behavioural change: the SRAM macro captures `A_ADDR`
    at a clock edge and presents the word on `A_DOUT` for the whole
    following cycle, so a read costs one edge. (The superseded
    flip-flop array answered combinationally, and this helper's old body
    was a bare `Timer(1, "ns")` settle.) Awaiting `ReadOnly` after the
    capturing edge reads the post-NBA `A_DOUT` -- same reason
    `read_reg()` below documents.

    This is the fetch-ahead contract from the *memory's* side: the
    address presented during cycle N is the word available in cycle
    N+1, which is exactly what `rtl/protocol_core.v` exploits by driving
    the next instruction's address rather than the current one's."""
    dut.fetch_addr.value = addr
    await RisingEdge(dut.clk)  # the macro captures A_ADDR on this edge
    await ReadOnly()           # ...and A_DOUT settles just after it
    value = int(dut.instr_word.value)
    await Timer(1, unit="ns")  # leave the read-only region (writable again)
    return value


async def read_reg(dut, name):
    """Read a registered output (e.g. `run_phase`) after the edge that
    updates it has fully settled.

    Resuming from `await RisingEdge(dut.clk)` lands this cocotb/Icarus
    combination in a region where the edge's nonblocking assignments have
    NOT yet propagated -- an immediate `.value` read returns the pre-edge
    value, not the post-edge one (observed empirically: every settled read
    sees the new value, every same-edge read sees the old one). Awaiting
    `ReadOnly` first reads the post-NBA state. The caller must await some
    other trigger before its next write (reads are legal, writes are not,
    in the read-only region).
    """
    await ReadOnly()
    return int(getattr(dut, name).value)
