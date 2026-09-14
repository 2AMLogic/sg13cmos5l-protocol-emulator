"""Shared DUT-driving helpers for `tt_um_2amlogic_protocol_emulator`
cocotb testbenches.

`reset()` centralizes the reset sequencing shared by
`test_protocol_emulator.py` and any future bench added under
`verification/` (e.g. once the ratified ISA lands, issue #1) -- a future
change to the reset pulse width only needs to happen once instead of being
replayed across files that could otherwise drift out of sync. Mirrors
`2AMLogic/sky130-modexp`'s `verification/_dut.py` (see `CLAUDE.md` §
"Harness bootstrap").

This module is a plain sibling import (`from _dut import reset`), not a
cocotb test module itself -- pytest and cocotb both leave it alone since it
defines no `@cocotb.test()` cases.
"""

from cocotb.triggers import ClockCycles


async def reset(dut):
    """Drive `rst_n` low for 10 cycles, then release it.

    10 cycles is a generous margin, not a timing requirement -- this stub
    has a single register with no reset-release timing to characterize yet.
    """
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    # Give the register two cycles to settle after reset release before a
    # caller starts driving new stimulus -- see test_protocol_emulator.py's
    # module docstring for why 2 cycles (not 1) is the margin used
    # throughout this bench.
    await ClockCycles(dut.clk, 2)
