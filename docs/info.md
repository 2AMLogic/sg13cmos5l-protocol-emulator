<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

This is a tiny CPU whose entire instruction set exists to read pins, write
pins, count cycles, and hit timing exactly — so that a serial protocol
(UART, SPI, I2C to start) is *firmware* rather than fixed logic. There is
deliberately **no** UART, SPI or I2C block on the die.

The core (`rtl/protocol_core.v`) has four 8-bit registers `R0`–`R3`, a 2-bit
`{Z, C}` flag register, and 16 opcodes in a fixed 16-bit word
(`[15:12]` opcode, `[11:10]` `Rd`, `[9:8]` `Rs`/port, `[7:0]` `imm8`):
`NOP LDI MOV ADD SUB AND OR XOR SHF IN OUT WAIT JMP BZ BNZ HALT`. Pins are
four addressable 8-bit ports — `ui_in` and `uio_in` readable by `IN`,
`uo_out` and `uio_out` writable by `OUT`. `uio_oe` is fixed at 0 (all
bidirectional pins are inputs) because no protocol pin plan has been
admitted yet.

**Timing is the product, so it is fixed by construction.** Every instruction
retires in exactly one cycle. The single exception, `WAIT imm8`, stalls
`imm8 + 1` cycles — a count that comes from the instruction word itself,
never from a register and never from a pin. A conditional branch costs the
same one cycle taken or not taken. So the exact clock cycle of any pin read
or pin write is computable from the instruction stream alone, without
simulating anything. An `IN` samples its port on the edge that retires it;
an `OUT`'s value appears on the pin exactly one cycle later, from a
register rather than a combinational path.

Programs live in a 256×16-bit SRAM macro and are loaded serially over two
pins. Hold `ui_in[7]` (MODE) high across the release of `rst_n` to enter
**load phase**: each clock edge shifts one bit from `ui_in[0]`, MSB first,
and every 16th bit commits one word at an auto-incrementing address from 0.
Drop MODE to enter **run phase**, which resets the program counter to 0 and
begins executing. MODE is latched only at reset release, so a running
program cannot be reprogrammed out from under itself — re-entering load
phase needs a fresh `rst_n` pulse with MODE high. All other pins are
untouched by loading.

`HALT` idles the core until the next reset. See the root
[README](../README.md) for the target specification, and
`spec/decision-records/0001-isa.md` for the full opcode table and the
per-protocol cycle budgets. Note that DR 0001 and DR 0005 (the SRAM-macro
program memory) are both `Proposed`, not ratified.

## How to test

Load a program over the two load-phase pins, then watch `uo_out`. The
shortest useful one is two instructions: `LDI R0, 0xA5` then
`OUT uo_out, R0` — encoded `0x10A5` and `0xA200`. Hold `ui_in[7]` high with
`rst_n` low, release `rst_n`, shift the 32 bits MSB-first on `ui_in[0]` (one
bit per clock), then drop `ui_in[7]`. `uo_out` reads `0xA5` three clocks
later (one for run-phase entry, one per instruction) and holds.

Two committed cocotb benches do exactly this, byte-for-byte:

- `test/test.py` — the Tiny Tapeout template's own harness, run by the
  `test` and `gds` workflows (the latter also re-runs it against the
  post-synthesis gate-level netlist). It loads an 8-instruction program and
  checks the reset state, the one-cycle `OUT` latency, `WAIT 3`'s four
  cycles, an `IN`+`ADD` round trip through a pin, `HALT`, and that a mid-run
  MODE-high reprogram attempt does nothing.
- `verification/test_protocol_emulator.py` — this program's own klt-driven
  bench (`klt functional-verification`), which exercises all 16 opcodes as
  loaded firmware and asserts each result on a *numbered* clock edge derived
  from the ISA's own cycle table, so a timing regression fails rather than
  merely shifting. See `verification/README.md`; the append-only evidence
  record is `verification/records/core-datapath/`.

## External hardware

None.
