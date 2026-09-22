<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

This is the ratified ISA's core datapath (issue #18, per
`spec/decision-records/0001-isa.md`): a tiny CPU whose instructions read
pins, write pins, count cycles, and hit timing precisely, so that a real
serial protocol (UART, SPI, I2C to start) is implemented in firmware
rather than as fixed logic. The top instantiates the core
(`rtl/protocol_core.v`) next to its 256x16-bit program memory
(`rtl/protocol_program_memory.v`): 16 opcodes, four 8-bit registers, a
zero flag and a carry flag, four addressable 8-bit pin ports (`ui_in`,
`uio_in` readable; `uo_out`, `uio_out` writable), and a timing model
where every instruction takes exactly one clock cycle except `WAIT`,
whose duration an immediate fixes -- so a program's cycle count is
computable from its instruction stream alone.

A program is loaded over two pins: hold `ui_in[7]` (MODE) high while
releasing `rst_n`, shift the program's 16-bit words MSB-first into
`ui_in[0]` one bit per clock edge, then drop MODE -- the core then
fetches and executes from address 0. `uio_out` direction
(`uio_oe`) is fixed at synthesis time and held as inputs in this
revision; no protocol pin roles are assigned yet (a later decision
record). See the root [README](../README.md) for the target
specification.

## How to test

`test/test.py` (run via the Tiny Tapeout `test`/`gds` GitHub Actions
workflows) loads a 3-instruction firmware echo over that serial load
phase -- read `ui_in`, write `uo_out`, jump back -- and checks the
echo runs. `verification/test_protocol_emulator.py` is this program's
own klt-driven cocotb bench, checking every instruction class
cycle-exactly via `klt functional-verification` against the same
sources (see `rtl/README.md` and `verification/README.md`).

## External hardware

None.
