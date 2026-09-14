"""cocotb testbench for `tt_um_2amlogic_protocol_emulator` -- this
program's own klt-driven bench for the harness-bootstrap stub (issue #2).

The ratified ISA has not landed yet (see `spec/`, issue #1), so this stub
has no instructions, no program memory, and no protocol logic. It only
proves the fixed Tiny Tapeout pin budget, clock, and reset wiring a future
ISA gets built on top of: `ui_in` is registered onto `uo_out` on every `clk`
edge while `ena` is high, and the register clears on `rst_n` low. This is
the "First test: the stub top's reset and pin-through behavior" issue #2
calls for.

Driven by `klt functional-verification` (see
`request-protocol-emulator.json`), directly against
`src/tt_um_2amlogic_protocol_emulator.v` -- the same source file the Tiny
Tapeout template's own `test/test.py` exercises (see `rtl/README.md` for why
there is no separate `rtl/` copy). `test/test.py` is the template's own
harness (used by the `gds`/`test` GitHub Actions workflows); this file is
this program's own evidence-record entry point, per `CLAUDE.md`'s
"verification is the product" rule.

Checks settle over 2 clock cycles rather than asserting exact 1-cycle
latency: this stub's only sequential element is a single register, but
pinning the test to the tightest possible latency would make it needlessly
brittle to simulator/testbench timing details that have nothing to do with
the behavior being verified, and the ratified ISA may pipeline pin updates
differently anyway.

This file is *input* to `klt functional-verification` (the testbench module
named by `request.testbench.module`), not a pytest module -- pytest never
collects it, since it takes a cocotb-injected `dut` argument and only runs
inside a simulator process.
"""

import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dut import reset  # noqa: E402


@cocotb.test()
async def test_reset_clears_output(dut):
    """After reset, the registered output is zero."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    assert dut.uo_out.value == 0
    # Nothing drives the bidirectional pins yet.
    assert dut.uio_oe.value == 0


@cocotb.test()
async def test_pin_through(dut):
    """`ui_in` is registered onto `uo_out` while `ena` is high."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    for value in (0x5A, 0xA3, 0x00, 0xFF):
        dut.ui_in.value = value
        await ClockCycles(dut.clk, 2)
        assert dut.uo_out.value == value, (
            f"ui_in={value:#04x}: got uo_out={int(dut.uo_out.value):#04x}"
        )


@cocotb.test()
async def test_ena_gates_updates(dut):
    """While `ena` is low, `uo_out` holds its last value regardless of `ui_in`."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset(dut)

    dut.ui_in.value = 0x3C
    await ClockCycles(dut.clk, 2)
    assert dut.uo_out.value == 0x3C

    dut.ena.value = 0
    dut.ui_in.value = 0x00
    await ClockCycles(dut.clk, 3)
    assert dut.uo_out.value == 0x3C

    dut.ena.value = 1
    await ClockCycles(dut.clk, 2)
    assert dut.uo_out.value == 0x00
