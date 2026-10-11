# Architecture and instruction set

Status: **provisional draft**, written 2026-10-11 for issue #230 against
`main` @ `16c0b2a`. It describes the ISA frozen by
[DR 0017](../../spec/decision-records/0017-submission-isa-freeze.md) as the
RTL builds it. Of the decision records it draws on, **DR 0001** (the ISA) is
**Ratified**, by the two-key act on PR #242 (merged 2026-10-11, issue #44
closed; recorded in
[DR 0009](../../spec/decision-records/0009-two-key-ratification-act.md)).
DR 0005, 0012, 0013, 0015, 0016 and 0017 are still **Proposed**: the control
space, the load path, the primitives, the flag and shift details and the
freeze itself are not bound. Status claims in this document were refreshed
on 2026-10-11 for issue #238, against `main` as of `a9ac6940` (after the
merge of PR #242). This document ratifies nothing and makes no target-spec
row met. Where it and a decision record disagree, the record wins and this
document is wrong.

The tables marked as checked below are compared with the assembler
([`firmware/tools/asm.py`](../../firmware/tools/asm.py)) and the independent
ISA model ([`verification/reference_models/isa.py`](../../verification/reference_models/isa.py))
by `python3 scripts/check_architecture.py`, which `npm run lint` and CI run.
See [the table contract](#the-table-contract) at the end.

## What the design is

A tiny CPU whose instructions read pins, write pins, count cycles and hit
timing, so that UART, SPI and I2C are **firmware**. There is no UART, SPI or
I2C block on the die. The one guarantee everything rests on: **no
instruction's cycle count depends on data.** Every cost is fixed by the
instruction word itself (an opcode, a `WAIT` immediate, or a control-register
index), so the clock cycle of every pin read and pin write can be computed
from the program text alone, without simulating anything.

- Four 8-bit registers `R0`–`R3`, two flags `Z` and `C`, an 8-bit PC.
- 16 opcodes in a fixed 16-bit word. The opcode table is full.
- Four 8-bit pin ports, addressed by a 2-bit field: two readable, two
  writable.
- A control space of named registers, reached through two operand
  combinations that were 1-cycle no-ops in the original ISA (`WCTL`, `RCTL`).
  It holds the runtime `uio` direction, program-memory access, a load CRC,
  status and two protocol-neutral primitives.
- 256 × 16-bit program memory (an SRAM macro), loaded by a serial path that
  needs no firmware, by a boot ROM written in this ISA, or by any running
  program through the control space.
- No data memory, no stack, no calls, no interrupts.

## Block diagram

```
          ui_in[7:0]                                   uio_in[7:0]
              |                                             |
  rst_n ----->+  MODE = ui_in[7], latched at rst_n release  |
              |                                             |
   +----------v---------------------------------------------v-----------+
   |                                                                    |
   |  serial load (MODE high): ui_in[0] -> 16-bit shift -> commit word  |
   |        |                                                           |
   |        v             fetch address (one cycle ahead)               |
   |  +--------------------------+        +-------------------------+   |
   |  | program memory           |<---+---| boot ROM (logic, a      |   |
   |  | 256 x 16 SRAM, 1 port    |    |   | program in this ISA)    |   |
   |  | PM_CRC over every commit |    |   +------------+------------+   |
   |  +------------+-------------+    |                |                |
   |               | word             |                | word           |
   |               +-----------+------+----------------+                |
   |                           v      |                                 |
   |   next-PC mux: PC+1 / imm8 / Rs (RUN)                              |
   |                           |                                        |
   |   decode + execute, 1 cycle (WAIT n: n+1, control access: table)   |
   |   R0..R3 (8 bit)   {Z, C}   WAIT counter                           |
   |        |                                                           |
   |        +--> control space, k = imm8 (WCTL k, Rs / RCTL Rd, k)      |
   |        |    UIO_DIR UIO_OD | PM_ADDR PM_DATA_HI/LO | RUN           |
   |        |    PM_CRC BOOT_STATUS HW_ID | P1 CRC/LFSR | P2 NRZI+stuff |
   |        |                                                           |
   |        +--> OUT: uo_out register      OUT: uio_out register        |
   |                   |                        |    UIO_DIR, UIO_OD    |
   |  load phase: PM_CRC byte on uo_out         |         |             |
   |                   |                        |   pin-mode logic      |
   +-------------------|------------------------|---------|-------------+
                       v                        v         v
                   uo_out[7:0]            uio_out[7:0]  uio_oe[7:0]
```

The RTL is [`rtl/protocol_core.v`](../../rtl/protocol_core.v) (core, control
space, primitives), [`rtl/protocol_program_memory.v`](../../rtl/protocol_program_memory.v)
(SRAM macro, port arbitration, serial load, `PM_CRC`),
[`rtl/protocol_boot_rom.v`](../../rtl/protocol_boot_rom.v) (generated from the
committed boot image) and the Tiny Tapeout top
[`src/tt_um_2amlogic_protocol_emulator.v`](../../src/tt_um_2amlogic_protocol_emulator.v)
(pin wiring, the `uio_oe` pin-mode logic and the load-phase `uo_out` mux).
[`rtl/README.md`](../../rtl/README.md) maps them.

## Timing model

These are **logical** (cycle-level) statements. The section
[Logical timing and electrical evidence](#logical-timing-and-electrical-evidence)
says what has and has not been shown about delays at the pins.

- **Execute.** One instruction per cycle. Costs are in the instruction table:
  1 cycle, except `WAIT imm8` (`imm8 + 1`, so 1 to 256) and the control
  accesses the control table marks 2 or 9.
- **Fetch one cycle ahead.** The SRAM macro reads synchronously, so the
  address of the instruction that executes in cycle *N+1* is computed
  combinationally in cycle *N* by the next-PC mux and presented to the memory
  at the edge ending cycle *N* (DR 0005's fetch-ahead text, made part of
  DR 0001 by its 2026-10-11 amendment for #85). This costs nothing per
  instruction: every branch takes its target from `imm8` and reads the `Z`
  written by an earlier instruction, so a taken and an untaken `BZ`/`BNZ`
  both cost 1 cycle.
- **Fixed run-phase entry.** The first run-phase cycle only presents
  address 0; instruction 0 executes on the second. This +1 cycle happens once
  per reset and does not depend on data.
- **`IN` samples on the edge that retires it.** The value is in `Rd` from the
  next cycle.
- **`OUT` drives on the edge that retires it.** `uo_out` and `uio_out` are
  registers, not combinational paths, so a pin changes exactly one cycle after
  the `OUT` executes, never earlier.
- **Program-memory accesses stall fetch for exactly one cycle, always.** The
  macro has one port, so `WCTL PM_DATA_LO` (commit a word) and
  `RCTL PM_DATA_HI` (read a word) take a fixed 2 cycles. `WCTL RUN`
  (computed jump) also always pays one fetch cycle: 2, whatever the target.
  `WCTL CRC_BYTE` is a fixed 9 (1 + 8 stall).
- **`HALT`** retires in 1 cycle; the core then idles until reset.

The consequence is that a straight-line section's cycle count is the sum of
its instructions' table costs. The assembler computes exactly that for every
`.cyclesec` section and commits it next to the image
(`firmware/build/*.cycles.txt`).

A conditional branch may depend on data (that is its job); its cost may not.
A loop whose trip count comes from a pin is therefore a timing hazard when
it produces protocol timing. The assembler warns about it, and DR 0001 names
the legitimate case: an I2C ACK wait is a handshake, not a timing budget.

## Registers, flags and ports

- `R0`–`R3`: 8-bit general-purpose registers, cleared at reset.
- `Z`, `C`: flags, cleared at reset. Only `BZ` and `BNZ` read a flag (`Z`).
  No instruction reads `C`; it is defined so that a later revision inherits
  one meaning ([DR 0016](../../spec/decision-records/0016-isa-flag-and-shift-details.md)).
- Program memory is not data-addressable by ordinary instructions. Firmware
  reaches it only through the `PM_*` control registers.

Pin ports (checked table). `IN` and `OUT` name the port; the code rides
bits `[9:8]`.

<!-- arch-table:ports:begin -->
| Name | Code | IN | OUT | Tiny Tapeout signal |
|---|---|---|---|---|
| `UI_IN` | `00` | yes | no | `ui_in[7:0]`, dedicated inputs |
| `UIO_IN` | `01` | yes | no | `uio_in[7:0]`, bidirectional pins, input side (always readable) |
| `UO_OUT` | `10` | no | yes | `uo_out[7:0]`, dedicated outputs |
| `UIO_OUT` | `11` | no | yes | `uio_out[7:0]`, bidirectional pins, output side; direction is set by `UIO_DIR` / `UIO_OD` |
<!-- arch-table:ports:end -->

The two combinations a port's direction forbids are not wasted. `OUT` to
code `00` is `WCTL` and `IN` from code `10` is `RCTL` (the control space,
below). `OUT` to code `01` and `IN` from code `11` stay reserved 1-cycle
no-ops.

## Instruction encoding

```
 15  14  13  12 | 11  10 |  9   8  |  7   6   5   4   3   2   1   0
 ----opcode----- --Rd---  Rs / port  ---------imm8 / k / unused-------
```

Every word is 16 bits, decoded combinationally. Bits a form does not use
are 0 in assembled code. `OUT` and `WCTL` carry their **source** register
in `[11:10]` (the `Rd` field), because `[9:8]` holds the port code for every
I/O form.

Instruction table (checked). It has one row for each of the assembler's 16
opcodes and one for each of its two control-space mnemonics, which reuse the
`OUT` and `IN` opcodes.

<!-- arch-table:opcodes:begin -->
| Mnemonic | Opcode | Kind | Operands | Encoding | Cycles | Z | C | Effect |
|---|---|---|---|---|---|---|---|---|
| `NOP` | `0x0` | `none` | none | `0000 00 00 00000000` | 1 | unchanged | unchanged | nothing |
| `LDI` | `0x1` | `ldi` | `Rd, imm8` | `0001 dd 00 iiiiiiii` | 1 | unchanged | unchanged | `Rd` ← `imm8` |
| `MOV` | `0x2` | `rr` | `Rd, Rs` | `0010 dd ss 00000000` | 1 | unchanged | unchanged | `Rd` ← `Rs` |
| `ADD` | `0x3` | `rr` | `Rd, Rs` | `0011 dd ss 00000000` | 1 | zero | carry | `Rd` ← `Rd + Rs` mod 256 |
| `SUB` | `0x4` | `rr` | `Rd, Rs` | `0100 dd ss 00000000` | 1 | zero | borrow | `Rd` ← `Rd − Rs` mod 256 |
| `AND` | `0x5` | `rr` | `Rd, Rs` | `0101 dd ss 00000000` | 1 | zero | unchanged | `Rd` ← `Rd & Rs` |
| `OR` | `0x6` | `rr` | `Rd, Rs` | `0110 dd ss 00000000` | 1 | zero | unchanged | `Rd` ← `Rd` or `Rs` (bitwise) |
| `XOR` | `0x7` | `rr` | `Rd, Rs` | `0111 dd ss 00000000` | 1 | zero | unchanged | `Rd` ← `Rd ^ Rs` |
| `SHF` | `0x8` | `shf` | `Rd, LEFT` or `Rd, RIGHT` | `1000 dd 0r 00000000` | 1 | unchanged | shift-out | shift `Rd` one place, 0 fills (shift table) |
| `IN` | `0x9` | `in` | `Rd, UI_IN` or `Rd, UIO_IN` | `1001 dd pp 00000000` | 1 | unchanged | unchanged | `Rd` ← port, sampled on the retiring edge |
| `OUT` | `0xA` | `out` | `UO_OUT, Rs` or `UIO_OUT, Rs` | `1010 ss pp 00000000` | 1 | unchanged | unchanged | port register ← `Rs`; the pin changes one cycle later |
| `WAIT` | `0xB` | `wait` | `imm8` | `1011 00 00 iiiiiiii` | imm8 + 1 | unchanged | unchanged | stall; `WAIT 0` is 1 cycle, `WAIT 255` is 256 |
| `JMP` | `0xC` | `branch` | `imm8` or label | `1100 00 00 iiiiiiii` | 1 | unchanged | unchanged | `PC` ← `imm8` |
| `BZ` | `0xD` | `branch` | `imm8` or label | `1101 00 00 iiiiiiii` | 1 | unchanged | unchanged | `PC` ← `imm8` if `Z = 1`, else `PC + 1`; same cost either way |
| `BNZ` | `0xE` | `branch` | `imm8` or label | `1110 00 00 iiiiiiii` | 1 | unchanged | unchanged | `PC` ← `imm8` if `Z = 0`, else `PC + 1`; same cost either way |
| `HALT` | `0xF` | `none` | none | `1111 00 00 00000000` | 1 | unchanged | unchanged | stop; the core idles until reset |
| `WCTL` | `0xA` | `wctl` | `k, Rs` | `1010 ss 00 kkkkkkkk` | control table | unchanged | unchanged | control register `k` ← `Rs` (`OUT` to port `00`) |
| `RCTL` | `0x9` | `rctl` | `Rd, k` | `1001 dd 10 kkkkkkkk` | control table | unchanged | unchanged | `Rd` ← control register `k` (`IN` from port `10`) |
<!-- arch-table:opcodes:end -->

Legend. **Encoding**: `0`/`1` are fixed bits; `dd` is `Rd`, `ss` the source
register, `pp` the port code, `r` the shift direction, `iiiiiiii` the
immediate or branch target, `kkkkkkkk` the control index. **Z**: `zero`
means `Z` ← (8-bit result = 0). **C**: `carry` is bit 8 of the 9-bit sum,
`borrow` is 1 exactly when `Rd < Rs` unsigned (bit 8 of the 9-bit
difference), `shift-out` is the bit shifted out. `unchanged` means the
instruction does not write that flag. The flag rules are DR 0001's table as
completed by DR 0016's four rulings: `SUB`'s `C` is a borrow, `SHF` leaves
`Z`, the logic operations leave `C`, `SHF` fills with 0.

There is no immediate ALU form and no add- or subtract-with-carry: a
countdown keeps `LDI R_one, 1` outside the loop and `SUB R_count, R_one`
inside it. Delays above 256 cycles are loops with a constant trip count.

Shift table (checked). The direction is bit 8 (`Rs[0]`) of the word.

<!-- arch-table:shift:begin -->
| Direction | Rs[0] | Fill | C |
|---|---|---|---|
| `LEFT` | 1 | 0 | `Rd[7]` |
| `RIGHT` | 0 | 0 | `Rd[0]` |
<!-- arch-table:shift:end -->

## Control space

`WCTL k, Rs` writes control register `k`; `RCTL Rd, k` reads it. `k` is the
immediate, so every access's cost is fixed by the program text
([DR 0012](../../spec/decision-records/0012-control-space-and-runtime-pin-direction.md),
with DR 0015's P1/P2 indices from DR 0012's 2026-10-10 note). No control
access writes `Z` or `C`. The assembler accepts the names below or a number.

Control register map (checked). `reserved` means the map assigns nothing in
that direction (see [Reserved encodings](#reserved-encodings)).

<!-- arch-table:control:begin -->
| k | Name | W | R | Write cycles | Read cycles | Meaning |
|---|---|---|---|---|---|---|
| `0x00` | `UIO_DIR` | yes | yes | 1 | 1 | per-pin push-pull drive enable for `uio[n]` |
| `0x01` | `UIO_OD` | yes | yes | 1 | 1 | per-pin open-drain enable; wins over `UIO_DIR` |
| `0x02` | `PM_ADDR` | yes | yes | 1 | 1 | program-memory word address for the next `PM_DATA_*` access |
| `0x03` | `PM_DATA_HI` | yes | yes | 1 | 2 | W: latch the high byte. R: read `PM[PM_ADDR]`, return the high byte, latch the low byte |
| `0x04` | `PM_DATA_LO` | yes | yes | 2 | 1 | W: commit `{HI, Rs}` to `PM[PM_ADDR]`, then `PM_ADDR + 1`. R: return the latched low byte, then `PM_ADDR + 1` |
| `0x05` | `RUN` | yes | no | 2 | reserved | `PC` ← `Rs`, fetch from program memory (leaves the boot ROM; also the one computed jump) |
| `0x06` | `PM_CRC_LO` | yes | yes | 1 | 1 | R: low byte of the CRC-16/XMODEM of every committed word. W: clears all 16 bits |
| `0x07` | `PM_CRC_HI` | yes | yes | 1 | 1 | R: high byte of that CRC. W: clears all 16 bits |
| `0x08` | `BOOT_STATUS` | no | yes | reserved | 1 | bit 0: a serial load ended since reset; bit 1: this instruction was fetched from the boot ROM |
| `0x09` | `HW_ID` | no | yes | reserved | 1 | design revision, `0x01` |
| `0x10` | `CRC_CFG` | yes | yes | 1 | 1 | P1: `[4:0]` width − 1, `[5]` reflected, `[6]` read-out inversion; a write rewinds the byte pointer |
| `0x11` | `CRC_POLY` | yes | yes | 1 | 1 | P1 polynomial, one byte at the byte pointer, pointer + 1 |
| `0x12` | `CRC_STATE` | yes | yes | 1 | 1 | P1 state, one byte at the byte pointer, pointer + 1; reads masked to the width |
| `0x13` | `CRC_BIT` | yes | no | 1 | reserved | P1: one CRC/LFSR step with data bit `Rs[0]` |
| `0x14` | `CRC_BYTE` | yes | no | 9 | reserved | P1: eight steps with the bits of `Rs` (1 + 8 stall cycles, fixed) |
| `0x15` | `CRC_NEXT` | no | yes | reserved | 1 | P1 read-out: state, inverted if configured, masked, one byte, pointer + 1 |
| `0x16` | `LINE_CFG` | yes | yes | 1 | 1 | P2: `[1:0]` NRZI mode, `[3:2]` stuff rule, `[6:4]` N; write bit 7 loads the line level |
| `0x17` | `LINE_PUT` | yes | no | 1 | reserved | P2: present data bit `Rs[0]`; on a stuff slot the stuff bit goes out instead |
| `0x18` | `LINE_OUT` | no | yes | reserved | 1 | P2: bit 0 the line level, bit 1 its complement |
| `0x19` | `LINE_STUF` | no | yes | reserved | 1 | P2: bit 0 set when the last `LINE_PUT` was a stuff slot |
<!-- arch-table:control:end -->

`0x0A`–`0x0F`, `0x1A`–`0x1F` (held for DR 0015's P3/P4 or replacements) and
`0x20`–`0xFF` are unassigned. Every control register resets to 0 except
`HW_ID`; `LINE_OUT`'s complement bit therefore reads 1. Per-field detail of
P1 and P2 is in the datasheet, [`docs/info.md`](../info.md) § How it works,
and in [DR 0015](../../spec/decision-records/0015-stretch-protocols-with-neutral-primitives.md).

### Runtime pin direction and open drain

Each `uio[n]` pin's mode comes from `UIO_OD[n]` and `UIO_DIR[n]`, both set by
firmware at run time:

| `UIO_OD[n]` | `UIO_DIR[n]` | Mode | `uio_oe[n]` |
|---|---|---|---|
| 1 | any | open drain: drives low on `uio_out[n] = 0`, releases on 1 | `~uio_out[n]` (`uio_out` here is port 11, the register `OUT` writes; the pad data of the pin is tied to 0) |
| 0 | 1 | push-pull output | 1 |
| 0 | 0 | input | 0 |

`uio_in` is always readable, so a released open-drain line reads back the
bus (I2C ACK, clock stretching, a PS/2 host pulling the clock low). At reset
`UIO_DIR = UIO_OD = 0`: every `uio` pin is an input and nothing is driven
until a program configures it. Because `uio_out` also resets to 0, an
open-drain program writes `OUT UIO_OUT` (release the lines) **before**
`WCTL UIO_OD`; `scripts/check_protocol_pin_roles.py` flags committed images
that do it the other way round. `RCTL` of `UIO_DIR`/`UIO_OD` returns the
register, not the effective `uio_oe` (DR 0012 open item 1, frozen as built).

The logic is two assignments in the top, from the core's port-11 register
`core_uio_out`: `uio_out = core_uio_out & ~uio_od` and
`uio_oe = (uio_od & ~core_uio_out) | (~uio_od & uio_dir)`. An open-drain
pin's pad data is the constant 0 and `uio_oe` alone carries the bit, so the
pad cannot drive high whatever the relative delay of the two nets
([DR 0020](../../spec/decision-records/0020-open-drain-pad-data-tied-low.md),
a conformance fix to DR 0012; issue #244). `uio_oe` is the same function of
port 11, `UIO_DIR` and `UIO_OD` as before, and no program can read the
`uio_out` pins, so nothing in this document's instruction or control tables
moved. The benches check the logical behaviour; the routed behaviour is
below.

### Program-memory access from firmware

`WCTL PM_ADDR` sets the address; `WCTL PM_DATA_HI` then `WCTL PM_DATA_LO`
commits a word and advances the address; `RCTL PM_DATA_HI` then
`RCTL PM_DATA_LO` reads one and advances. Every committed word, by this path
or by the serial load, updates `PM_CRC` (CRC-16/XMODEM, polynomial `0x1021`,
init 0, high byte of each word first). A write to the word fetched next
takes effect for fetches after the write retires; self-modifying code must
not rely on anything earlier. `WCTL RUN` jumps to `Rs` in program memory,
which is how the boot ROM hands over and how a running program can load and
start another one.

### What the control space is not

It holds pin direction, program-memory access, load integrity, identity, and
two **protocol-neutral** primitives: P1, a CRC/LFSR step with a programmable
polynomial and width, and P2, NRZI coding with a bit-stuffing counter.
DR 0015 admitted them under a four-part test: no framing, fixed latency, at
least three unrelated protocols need them, reached only through the control
space. Neither knows a frame, a start bit or an address; firmware builds
every packet. P3 (Manchester) failed the test and is not built; P4 (clock
recovery) is deferred.

## Reserved encodings

The hardware defines every encoding: a reserved write is a 1-cycle no-op
and a reserved read returns `0x00` in 1 cycle. The assembler treats them as
firmware bugs. Accesses the control map leaves unassigned are refused unless
`--allow-reserved` is given. The two I/O no-ops (`OUT` to port `01`, `IN`
from port `11`) and the control encodings spelled as plain `IN`/`OUT` are
refused with or without the flag (checked table; `error` means the assembler
refuses the line, a number is the assembled cycle count).

<!-- arch-table:reserved:begin -->
| Example | Default | With --allow-reserved | Hardware |
|---|---|---|---|
| `WCTL 0x1A, R0` | error | 1 | unassigned index: 1-cycle no-op |
| `RCTL R0, 0x1F` | error | 1 | unassigned index: `0x00` in 1 cycle |
| `WCTL HW_ID, R0` | error | 1 | write to a read-only register: 1-cycle no-op |
| `RCTL R0, RUN` | error | 1 | read of a write-only register: `0x00` in 1 cycle |
| `OUT UIO_IN, R0` | error | error | `OUT` to port `01`: 1-cycle no-op |
| `IN R0, UIO_OUT` | error | error | `IN` from port `11`: 1-cycle no-op |
| `OUT UI_IN, R0` | error | error | this encoding is `WCTL`; write it as `WCTL` |
| `IN R0, UO_OUT` | error | error | this encoding is `RCTL`; write it as `RCTL` |
<!-- arch-table:reserved:end -->

## Boot and load path

How a program reaches program memory
([DR 0013](../../spec/decision-records/0013-program-loading.md), Proposed).
The datasheet [`docs/info.md`](../info.md) gives the host-side procedures and
cycle counts.

1. **Serial load (layer 1, no firmware, cannot be bricked).** Hold `MODE`
   (`ui_in[7]`) high across `rst_n` release. Each clock shifts one bit from
   `ui_in[0]`, MSB first; every 16th bit commits a word at an
   auto-incrementing address from 0. While loading, `uo_out` shows the
   running `PM_CRC` (low byte when `ui_in[1] = 0`, high byte when 1), so the
   host checks the load before it runs anything. Dropping `MODE` starts the
   run phase at address 0 with the fixed +1 entry cycle, and sets
   `BOOT_STATUS[0]`. `MODE` is latched only at reset release, so a running
   program cannot be reloaded under itself.
2. **Boot ROM (layer 2, firmware).** With `MODE` low at `rst_n` release the
   core fetches from a ROM synthesized as logic. Its content is an ordinary
   program in this ISA ([`firmware/asm/boot/boot_rom.asm`](../../firmware/asm/boot/boot_rom.asm)),
   assembled by the same assembler; [`rtl/protocol_boot_rom.v`](../../rtl/protocol_boot_rom.v)
   is generated from the committed image and checked against it in lint. It
   reads straps `ui_in[6:5]`: `00` UART load (RX `ui_in[1]`, TX `uo_out[0]`),
   `01` SPI-flash boot from a Tiny Tapeout QSPI Pmod on `uio[0..3]`, `10` warm
   start of an image already in memory if its CRC signature checks, `11` as
   `00`. Each verifies the image through `PM_CRC` before `WCTL RUN 0`, and
   never runs an image that fails. The UART receiver and the SPI controller
   here are firmware, like every other protocol on the chip.
3. **Runtime load.** Any running program can write program memory through
   `PM_*` and jump with `RUN`, for example to swap protocols.

The boot ROM is firmware, not ISA: DR 0017 does not pin its content, and
changes to it change this section's prose but not the instruction set. The
latest was PR #248 for issue #211 (merged 2026-10-11), which added the UART
frame's count-complement byte; the frame format is in
[`docs/info.md`](../info.md).

## What the ISA does not do

- **No fixed-function protocol peripheral.** No UART, SPI, I2C, PS/2,
  WS2812, USB or Ethernet block. Each protocol on record is a committed
  program, graded against an independent model of that protocol. The only
  computation in the control space is the load CRC (the serial load runs no
  firmware that could compute it) and DR 0015's two protocol-neutral
  primitives.
- **No data-dependent latency.** No instruction waits for a pin, and no cost
  depends on a register. A blocking "wait for edge" was ruled out by DR 0015's
  admission test.
- **No data memory, stack, subroutine call or interrupt.** Programs are flat
  loops over four registers. `RUN` is the one computed jump.
- **No instruction reads `C`.** No branch-on-carry, no add-with-carry, no
  shift through carry.
- **No immediate ALU form and no shift that merges a bit.** This is why a
  full-duplex SPI byte that keeps the received bits runs slower than
  f_clk/4 (DR 0001's 2026-10-10 note): transmit with the sample taken fits
  4 cycles per bit; assembling the received byte takes 10 on DR 0010's pins.
- **No program memory beyond 256 words** and no wider PC.

## Logical timing and electrical evidence

**Logical timing** (cycle counts, the edge on which a pin changes) is what
the ISA defines. It is checked by RTL benches, by formal properties, by an
independent lockstep model and on the gate-level netlist at zero delay.

**Electrical evidence** is thinner, and nothing here is a silicon
measurement:

- The routed-netlist SDF regression (LibreLane netlist and SDF, Icarus and
  cocotb through `klt functional-verification`) runs the core test program at
  three corners: [`post-layout-sdf-regression`](../../verification/records/post-layout-sdf-regression/).
  Since 2026-10-11 the same records carry the UART TX, SPI and I2C
  repeated-START firmware benches on the routed netlist with SDF delays, at
  the same three corners (#217's harness; the records leave open whether
  that closes #217, and #217 was closed on that evidence on 2026-10-11). The boot programs, UART
  RX, PS/2 and WS2812 have no routed-SDF run.
- The `uio` pad model the protocol benches run on is logical and
  zero-delay: [`uio-pad-model`](../../verification/records/uio-pad-model/).
  It resolves the design's `uio_oe`/`uio_out`; it is not a characterization
  of the Tiny Tapeout IO cells.
- **Finding #244, fixed by DR 0020.** On the routed netlist with SDF delays,
  the top as first built drove an open-drain pin HIGH for part of a cycle on
  each release edge: `uio_oe[n]` was derived from `uio_out[n]` and the two
  reached the pins 50 to 210 ps apart. The pad data of an open-drain pin is
  now tied to 0. The routed-SDF I2C repeated-START run passes at all three
  corners on the fixed netlist, and the same run on the pre-fix netlist fails
  at all three with the pads driven high; both are in
  [`post-layout-sdf-regression`](../../verification/records/post-layout-sdf-regression/)
  (records `20261011-114800-e5a0bae` and its three siblings). The Tiny Tapeout
  IO cell and mux are outside the netlist, so this is the design's boundary,
  not a pad waveform. One case is left to firmware: writing `UIO_OD` on a pin
  that is push-pull and high at that moment (DR 0020, "Limits"); no committed
  program does.
- No synthesis, area or timing figure is quoted in this document. Those
  figures and the flow that produced each are in
  [`verification.md`](verification.md) and the records it cites.

## Evidence

Each line names the bench and the append-only record family. A record that a
later one supersedes stays in place; the live (not superseded) records are
the current results, and `verification.md` cites the specific ones.
[`verification.md`](verification.md) is the judge-facing account of what
each one shows, its oracle, its design level and its limits.

| Claim | Bench | Record family |
|---|---|---|
| Every opcode's result, on a numbered clock edge | [`test_protocol_emulator.py`](../../verification/test_protocol_emulator.py) | [`core-datapath`](../../verification/records/core-datapath/) |
| RTL matches an independent ISA model on every edge | [`test_isa_lockstep.py`](../../verification/test_isa_lockstep.py), [`isa.py`](../../verification/reference_models/isa.py) | [`isa-lockstep`](../../verification/records/isa-lockstep/) |
| No data-dependent latency (formal, bounded) | [`no_data_dependent_latency.sv`](../../verification/formal/no_data_dependent_latency.sv) | [`no-data-dependent-latency`](../../verification/records/no-data-dependent-latency/) |
| `OUT` visible one cycle later, never earlier (formal) | [`pin_write_latency.sv`](../../verification/formal/pin_write_latency.sv) | [`pin-write-latency`](../../verification/records/pin-write-latency/) |
| Control space: reset values, readback, reserved indices, fixed stalls, pin modes | [`test_control_space.py`](../../verification/test_control_space.py) | [`control-space`](../../verification/records/control-space/) |
| P1 and P2 against catalogue CRCs and an independent line decoder | [`test_primitives.py`](../../verification/test_primitives.py) | [`primitives`](../../verification/records/primitives/) |
| Serial load phase | [`test_program_memory.py`](../../verification/test_program_memory.py) | [`program-load-phase`](../../verification/records/program-load-phase/) |
| Load-phase CRC readout on `uo_out` | [`test_load_integrity.py`](../../verification/test_load_integrity.py) | [`load-integrity`](../../verification/records/load-integrity/) |
| Boot ROM: straps, warm start, refusal of bad images | [`test_boot_rom.py`](../../verification/test_boot_rom.py) | [`boot-rom`](../../verification/records/boot-rom/) |
| SPI-flash boot | [`test_boot_spi.py`](../../verification/test_boot_spi.py) | [`boot-spi`](../../verification/records/boot-spi/) |
| UART load | [`test_boot_uart.py`](../../verification/test_boot_uart.py) | [`boot-uart`](../../verification/records/boot-uart/) |
| `uio` pin modes through a logical pad model | [`test_uio_pads.py`](../../verification/test_uio_pads.py) | [`uio-pad-model`](../../verification/records/uio-pad-model/) |
| Assembler output runs as the assembler says | [`test_firmware_roundtrip.py`](../../verification/test_firmware_roundtrip.py) | [`firmware-assembler-roundtrip`](../../verification/records/firmware-assembler-roundtrip/) |
| Firmware and control space on the gate-level netlist (zero delay) | [`run-firmware-gate-level.sh`](../../flow/run-firmware-gate-level.sh) | [`firmware-gate-level`](../../verification/records/firmware-gate-level/) |
| Core test program, and the UART TX, SPI and I2C repeated-START firmware (`--suite protocols`), on the routed netlist with SDF, three corners | [`run-post-layout-sdf.sh`](../../flow/run-post-layout-sdf.sh) | [`post-layout-sdf-regression`](../../verification/records/post-layout-sdf-regression/) |

The protocols themselves (UART, SPI, I2C, WS2812, PS/2) are in the
datasheet's "Protocols as firmware" table, each with its program, bench and
record.

## Limitations and open items

- **Partly ratified.** DR 0001 is Ratified (PR #242, DR 0009). DR 0005,
  0012, 0013, 0015, 0016 and 0017 are Proposed; DR 0001's 2026-10-11
  amendment from the PR #242 EE-key review scopes its statements to the
  instruction set it defines and leaves DRs 0012, 0013 and 0015 unbound. Ratifying them
  is outside this document.
- **Frozen, with amendments.** DR 0017 pins eleven ISA-defining files by hash.
  At the reviewed commit, `spec/isa-freeze.json` records three
  `no-behaviour-change` amendments (DR 0013 note, #234; DR 0001's fetch-ahead
  amendment, #85; DR 0001's runtime-direction amendment, #44). None changes
  what a program observes. Since then it has gained a fourth of that kind
  (DR 0013's #211 entry), one `conformance-fix` amendment for the top
  (DR 0020, #244), and, with PR #242, two more `no-behaviour-change`
  amendments to DR 0001 (its Status flip to Ratified, and the EE-key scoping
  note): seven in all as of `a9ac6940`. None changes what a program
  observes.
- **#244**, the routed open-drain release glitch (above): fixed by DR 0020.
- **#211 / PR #248**, the boot ROM's UART frame (the count byte was outside
  the CRC, DR 0013 finding F8): resolved; #211 is closed and PR #248 merged.
  It changed the boot firmware, not the ISA. A coordinated corruption of
  count and complement that also aliases the CRC is still not rejected.
- **#217**, routed-SDF evidence for the protocol firmware: closed. UART TX,
  SPI and I2C repeated START have it (above); the boot programs, UART RX,
  PS/2 and WS2812 do not.
- **DR 0012's open items** (`RCTL UIO_*` returns the register; `RUN` is
  allowed outside the boot ROM) are frozen as built, still Proposed.
- **No silicon.** Every statement here is from simulation, formal or static
  checks.

## The table contract

`scripts/check_architecture.py` reads only the five tables between
`<!-- arch-table:NAME:begin -->` and `<!-- arch-table:NAME:end -->` markers
(`ports`, `opcodes`, `shift`, `control`, `reserved`). Prose and the other
tables are free text. In a checked table:

- The header row names the columns; the checker finds them by name, so their
  order may change and extra columns (such as Effect or Meaning) are
  allowed. A missing column fails.
- Backticks are stripped from cells. A cell may not contain `|`.
- `ports`: one row per assembler port; `Code` is two binary digits; `IN` and
  `OUT` are `yes` or `no`.
- `opcodes`: one row per entry of the assembler's `OPCODES` and
  `CTL_MNEMONICS`, exactly once each. `Opcode` is `0x` and one hex digit;
  `Kind` is the assembler's operand kind; `Encoding` is 16 characters from
  `0 1 d s p r i k` (spaces ignored), where a letter run gives the field of
  the matching operand, and the letters present must be exactly the
  operands that instruction has (bits it does not use are written as the
  fixed 0/1 the assembler emits); `Cycles` is a number, `imm8 + N`, or `control table`;
  `Z` is `zero` or `unchanged`; `C` is `carry`, `borrow`, `shift-out` or
  `unchanged`.
- `shift`: rows `LEFT` and `RIGHT`; `Rs[0]` and `Fill` are 0 or 1; `C` is
  `Rd[0]` … `Rd[7]`.
- `control`: one row per entry of the assembler's `CTL_REGS`, exactly once
  each. `k` is `0x` and two hex digits; `W` and `R` are `yes` or `no`; a
  cycle cell is a number where that direction is assigned and `reserved`
  where it is not.
- `reserved`: each `Example` is one line of assembly; `Default` and
  `With --allow-reserved` are `error` or the assembled cycle count. Rows must
  cover the six reserved cases (unassigned write, unassigned read, write to
  a read-only register, read of a write-only register, `OUT` port `01`, `IN`
  port `11`).

What it compares: names, opcodes and kinds with `OPCODES`/`CTL_MNEMONICS`;
indices, permissions and per-direction latencies with `CTL_REGS` and the
reference model's `CONTROL`; ports with `PORTS`; the documented encoding and
cycle formula with words and `Instruction.cycles` the assembler produces for
every operand form (registers, both shift directions, every port, `WAIT 0`,
`WAIT 255`, branch targets, every assigned control index in each direction,
the reserved examples), and with the reference model's `static_cost`. The
assembler has no flag table, so the `Z` and `C` columns are compared with
the independent reference model's effects (`isa.py`, written from DR 0001 and
DR 0016) on representative operands: `ADD` carry, `SUB` borrow, logic
operations leaving `C`, `SHF` leaving `Z` and filling with 0. That checks
this document against existing sources; it is not a new proof of the ISA.
Every relative link in this file must resolve. The checker imports the
assembler and the model read-only and writes nothing.

Run it locally with Python 3 and nothing else:

```bash
python3 scripts/check_architecture.py
python3 scripts/test_check_architecture.py
```
