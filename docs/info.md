<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

This is the harness-bootstrap stub (issue #2), not the final design. The
ratified instruction set has not landed yet (see `spec/`, issue #1), so
`tt_um_2amlogic_protocol_emulator` has no instructions, no program memory,
and no protocol logic. It only proves the fixed Tiny Tapeout pin budget and
clock/reset wiring the ISA will be built on: every clock edge, while `ena`
is high, `ui_in` is registered onto `uo_out`; a low `rst_n` clears the
registered output to zero. `uio_out`/`uio_oe` are held at zero, so the
bidirectional pins are configured as inputs.

Once the ISA is ratified, this repo's project will be a tiny CPU whose
instructions read pins, write pins, count cycles, and hit timing precisely,
so that a real serial protocol (UART, SPI, I2C to start) is implemented in
firmware rather than as fixed logic in this file. See the root
[README](../README.md) for the target specification.

## How to test

`test/test.py` (this file, run via the Tiny Tapeout `test`/`gds` GitHub
Actions workflows) exercises reset and the registered pin-through behavior
above. `verification/test_protocol_emulator.py` is this program's own
klt-driven cocotb bench, checking the same behavior via `klt
functional-verification` against this same `src/` source file directly (no
separate copy under `rtl/`; see `rtl/README.md`); see `verification/README.md`.

## External hardware

None.
