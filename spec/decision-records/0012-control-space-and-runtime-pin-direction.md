# 0012: A Control-Register Space in the Existing No-Op Encodings — Runtime `uio` Direction and Program-Memory Access

Status: **Proposed 2026-10-09.** It goes to ratification through the
program's two-key (`RATIFY-KEY`) mechanism on the PR that carries it
(`spec/README.md`, "How ratification works here"; DR
[`0004`](0004-target-spec-ratification.md) and
[`0006`](0006-two-key-ratification-never-ran.md)). It binds only when that
PR's history shows **two** `RATIFY-KEY` reviews, one EE key and one market
key, neither held by this record's author. That mechanism has never run in
this repository (issue #44), so this record is a proposal, the same way
DRs 0001–0005, 0007, 0008 and 0010 are. It makes no target-spec row met.
Date: 2026-10-09
Issues: #129, #130, #133 (context); implementation issues are filed from
this record.

**Numbering note.** `main` carries 0001–0008 and 0010; open PR #84 reserves
0009 and open PR #128 reserves 0011. This record is **0012**; its companion
on program loading is [`0013`](0013-program-loading.md).

## Context

### What changed: the organizers' 2026-10-09 entrant update

The competition organizers sent registered entrants an update and FAQ on
2026-10-09. They say it will be folded into the competition blog post; until
then the verbatim quotes in issues #129–#134 are the citable copy. Three
statements bear on the ISA:

> Flexibility is the main thing: can the chip be reprogrammed to support
> protocols it wasn't designed for?

> Running protocols concurrently, or supporting both controller and target
> roles, is a plus but not required.

> How does the program get loaded? That's part of your design.

### Two places where today's ISA fixes in silicon what firmware should decide

1. **`uio` direction is fixed at synthesis time.** DR 0001's port table and
   § Consequences fix `uio_oe` per protocol pin plan and flag runtime
   direction as an open question. DR 0008 proposed a synthesis-time
   open-drain mask, and DR 0010 proposed its value. **Neither is in the
   RTL.** `src/tt_um_2amlogic_protocol_emulator.v` still has
   `assign uio_oe = 8'h00;`, so on silicon every bidirectional pin is an
   input. The I2C firmware's passing evidence comes from a bench-composed
   wired-AND bus (DR 0008 § Context). As built, **the chip cannot pull an
   I2C line low.** A synthesis-time mask, even once wired, also defeats the
   primary judging criterion: a protocol nobody planned for that needs a
   different pin direction (1-Wire on a different pin, a target-role SPI
   whose MISO must drive, a QSPI flash on the Tiny Tapeout QSPI Pmod's
   pinout) cannot be expressed without re-synthesis.
2. **Program memory is reachable only through the reset-gated serial
   loader.** DR 0001: "program memory … is not data-addressable at all".
   Nothing running on the chip can load a program, so every load path needs
   an external host that drives `clk`, `rst_n` and two pins in lockstep. And
   every deselect powers the design down and wipes the SRAM (organizers:
   "plan to reload the program after it's selected again"). DR 0013 decides
   the loading strategy; this record supplies the hardware path it needs.

### The encoding room already exists

DR 0001's opcode table is full (16 of 16), but two operand combinations are
defined as **1-cycle no-ops** that the assembler rejects as firmware bugs:

- `OUT` to a read-only port (`00` `ui_in`, `01` `uio_in`)
- `IN` from a write-only port (`10` `uo_out`, `11` `uio_out`)

In both, `imm8` (`[7:0]`) is unused (DR 0001 § Encoding: "unused
(recommended 0) for register-register forms"; `rtl/protocol_core.v` decodes
`OUT`'s source register from `[11:10]` and ignores `[7:0]`). No committed
firmware uses either combination, because the assembler refuses them.

## Decision (proposed)

### 1. The control space

Give one encoding in each direction a meaning, and keep the other two
as reserved no-ops:

| Encoding | New mnemonic | Effect | Cycles |
|---|---|---|---|
| `OUT` port `00`, `imm8 = k` | `WCTL k, Rs` | control register `k` ← `Rs` | 1, except where the table below says 2 |
| `IN` port `10`, `imm8 = k` | `RCTL Rd, k` | `Rd` ← control register `k` | 1, except where the table below says 2 |
| `OUT` port `01`, `IN` port `11` | — | unchanged: 1-cycle no-op, assembler error (reserved) | 1 |

Every latency is **fixed per index `k`, and `k` is an immediate**, so the
cycle count stays computable from the program text alone. That is target-spec
row 3's guarantee, unchanged. No control register sets `Z`/`C`. A write to an
unassigned index is a 1-cycle no-op. A read of an unassigned index returns
`0x00` in 1 cycle. The assembler rejects both unless given an explicit
`--allow-reserved`.

### 2. The initial register map

| `k` | Name | W | R | Cycles | Meaning |
|---|---|---|---|---|---|
| `0x00` | `UIO_DIR` | ✓ | ✓ | 1 | per-pin push-pull drive enable for `uio[n]` |
| `0x01` | `UIO_OD` | ✓ | ✓ | 1 | per-pin open-drain enable for `uio[n]`: drives low when `uio_out[n] = 0`, releases (hi-Z) when `1` |
| `0x02` | `PM_ADDR` | ✓ | ✓ | 1 | program-memory word address for the next `PM_DATA_*` access |
| `0x03` | `PM_DATA_HI` | ✓ | ✓ | W 1 / **R 2** | W: latch the high byte. R: read `PM[PM_ADDR]`, return the high byte, latch the low byte |
| `0x04` | `PM_DATA_LO` | ✓ | ✓ | **W 2** / R 1 | W: commit `{HI, LO}` to `PM[PM_ADDR]`, then `PM_ADDR++`. R: return the latched low byte, then `PM_ADDR++` |
| `0x05` | `RUN` | ✓ | — | **2** | switch the fetch source to program memory, `PC ← Rs` (DR 0013 uses it to leave the boot ROM) |
| `0x06` / `0x07` | `PM_CRC_LO` / `PM_CRC_HI` | W clears | ✓ | 1 | CRC-16/XMODEM (poly `0x1021`, init `0x0000`) over every word committed to program memory since reset or since the last clear, by any path (DR 0013) |
| `0x08` | `BOOT_STATUS` | — | ✓ | 1 | bit 0: a serial load completed since reset; bit 1: running from the boot ROM; other bits read 0 |
| `0x09` | `HW_ID` | — | ✓ | 1 | constant design/revision byte, so a host or a program can tell silicon revisions apart |
| `0x10`–`0x1F` | — | | | | reserved for the protocol-neutral primitives #130 is evaluating (CRC/LFSR step, NRZI/bit-stuff, Manchester, resync). Each needs its own record and must have fixed latency |

**Index map for the protocol-neutral primitives (dated note, 2026-10-10, issue
#208).** The row above stays as written; it reserved `0x10`-`0x1F`. DR 0015
(Proposed) admits P1 (CRC / LFSR step) and P2 (NRZI + bit stuffing), and the
build of issue #208 assigns these indices. This is a note on a Proposed record,
not a ratification; no Status line changes, and DR 0015's interface is what
defines the semantics.

| `k` | Name | W | R | Cycles | Meaning (DR 0015) |
|---|---|---|---|---|---|
| `0x10` | `CRC_CFG` | ✓ | ✓ | 1 | `[4:0]` width-1, `[5]` reflected, `[6]` read-out inversion; a write rewinds the byte pointer |
| `0x11` | `CRC_POLY` | ✓ | ✓ | 1 | polynomial byte at the byte pointer, then the pointer advances |
| `0x12` | `CRC_STATE` | ✓ | ✓ | 1 | state byte at the byte pointer, then the pointer advances; a read is masked to the width |
| `0x13` | `CRC_BIT` | ✓ | — | 1 | one step with data bit `Rs[0]` |
| `0x14` | `CRC_BYTE` | ✓ | — | **W 9** (1 + 8 stall, fixed) | eight steps with the bits of `Rs`, LSB first if reflected, else MSB first |
| `0x15` | `CRC_NEXT` | — | ✓ | 1 | next byte of the read-out (state, inverted if configured, masked to the width); the pointer advances |
| `0x16` | `LINE_CFG` | ✓ | ✓ | 1 | `[1:0]` NRZI mode, `[3:2]` stuff rule, `[6:4]` N; write bit 7 loads the line level and the write clears the run count |
| `0x17` | `LINE_PUT` | ✓ | — | 1 | present data bit `Rs[0]`; on a stuff slot the stuff bit is emitted and `Rs` is not consumed |
| `0x18` | `LINE_OUT` | — | ✓ | 1 | bit 0 the line level, bit 1 its complement |
| `0x19` | `LINE_STUF` | — | ✓ | 1 | bit 0: the last `LINE_PUT` was a stuff slot |
| `0x1A`-`0x1F` | — | | | | still unassigned; held for DR 0015's P3/P4 or their replacements |

Every other access to these indices (a read of a write-only one, a write to a
read-only one) is a 1-cycle no-op returning `0x00`, as for the table above.
The primitives do not touch the flags (this record, "What this does *not* do").
Only `WCTL CRC_BYTE` is longer than 1 cycle, and its 9 cycles do not depend on
`Rs`, the polynomial or the state. `firmware/tools/asm.py` carries the names.
The byte-pointer indices (`CRC_POLY`, `CRC_STATE`, `CRC_NEXT`) share one 2-bit
pointer, like `PM_DATA_LO` in this record.

**Pin mode, per `uio[n]`.** If `UIO_OD[n]` is set, the pin is open-drain and
`uio_oe[n] = ~uio_out[n]`. Otherwise, if `UIO_DIR[n]` is set, it is push-pull
and `uio_oe[n] = 1`. Otherwise it is an input and `uio_oe[n] = 0`. `uio_in` is
always readable, so an open-drain line that is released reads back the bus.
This keeps DR 0008's wired-AND semantics exactly, with the mask in a register
instead of a synthesis constant.

**Reset values: everything is an input.** `UIO_DIR = UIO_OD = 0x00`, and
`PM_ADDR`, the latches, the CRC and `BOOT_STATUS` are cleared. No `uio` pin is
driven until a program configures it. This is the safe state on a shared demo
board, and it is the state target-spec row 14 asks for. DR 0008's
synthesis-time mask is **not built**. This record proposes to supersede that
mechanism, while DR 0008's open-drain *semantics* and DR 0010's pin roles
survive as firmware conventions. The I2C programs gain a one-instruction
preamble (`WCTL UIO_OD, R` with `0x81`, SCL|SDA per DR 0010). **The preamble
goes after the `OUT UIO_OUT` that releases the lines, not before it.**
`uio_out` resets to `0x00`, so a `WCTL UIO_OD` that runs first pulls SCL and
SDA low for a cycle. The committed images follow this order, and
`scripts/check_protocol_pin_roles.py` reports an image that has it the other
way round. Changing the reset value of `uio_out` instead is not proposed: it
would alter the reset state of every pin. Any program that writes `UIO_OUT`
for bench-debug reasons is harmless only while it executes no `WCTL` (issue
#154, option 3).

**Program-memory timing.** `RM_IHPSG13_1P_256x16_c2_bm_bist` is single-port,
and the fetch-ahead stage (DR 0005) drives its address every cycle. A
`PM_DATA_LO` write or a `PM_DATA_HI` read takes the port for one cycle and
stalls fetch for exactly one cycle, always. That fixed extra cycle is what
the "2" entries in the table mean. A write to the word being fetched next
takes effect for the fetches after the write retires. Firmware that modifies
itself must not depend on anything earlier, and the boot ROM (DR 0013) never
does, because it does not execute from program memory while it loads it.

**Points the first RTL build had to choose.** The record left these open.
Issue #159 collects them; the RTL (`rtl/protocol_core.v`) and
`verification/test_control_space.py` implement them, and they are proposed
here as the behaviour, to be ratified with the rest of the record. Changing
any of them is a new issue with the RTL and the bench following.

| Point | Proposed behaviour |
|---|---|
| Value of `HW_ID` | `0x01`, a module parameter |
| Byte order of the CRC within a word | high byte first, to match DR 0013's big-endian UART frame |
| What a write to `PM_CRC_LO` or `PM_CRC_HI` clears | all 16 bits, from either register |
| Write to a read-only register (`BOOT_STATUS`, `HW_ID`) | 1-cycle no-op; the assembler treats it as reserved |
| Read of write-only `RUN` | `0x00` in 1 cycle; the assembler treats it as reserved |
| When `BOOT_STATUS[0]` is set | when a load phase ends, whatever it loaded, including zero words. Until DR 0013's boot ROM (#138) lands |
| Whether a `PM_DATA_LO` write disturbs the low-byte read latch | it does not |
| Where `RUN`'s second cycle comes from | `RUN` always pays one fetch cycle, as the table says, although no fetch-source switch existed in the first build. Until DR 0013's boot ROM (#138) lands the extra cycle is a bubble, not a source switch |

Two of these interact with the boot ROM: the `BOOT_STATUS[0]` rule and the
`RUN` second cycle. #138 owns any change to them.

### 3. What this does *not* do

- It adds no protocol peripheral. Every register is pin direction,
  program-memory access, integrity or identity. The one piece of
  computation, the CRC, is admitted for load integrity because the serial
  load path runs no firmware that could compute it (DR 0013 § Integrity). It
  is not offered as a protocol CRC. That question belongs to #130.
- It changes no existing instruction's latency or encoding. Every committed
  program assembles to the same words, apart from the I2C preamble above,
  which silicon needs.
- It does not widen the PC or the program memory. 256 words stays row 6's
  size, and area-funded growth is #129's question.

## Alternatives considered

1. **DR 0008 as proposed: a synthesis-time open-drain mask.** It is cheaper
   by one 8-bit register, and it fixes I2C. It is rejected for flexibility:
   every protocol that needs another direction means re-synthesis, which is
   the opposite of what the organizers say they judge.
2. **A fifth port code for `uio_oe`** (DR 0001 § Consequences suggests it).
   The port field is 2 bits and full, so this needs an encoding change to
   every `IN`/`OUT`. It is rejected because the no-op encodings already give
   the room for free.
3. **A new opcode.** None is free. Retiring one (for example folding `MOV`
   into `OR Rd, Rs` after a clear) would churn every committed program and
   the formal latency table. It is rejected.
4. **Memory-mapped I/O.** There is no data memory to map into (DR 0001), and
   adding one changes the machine model. It is rejected.

## Consequences

- **I2C becomes possible on silicon**, and so do target roles and protocols
  nobody planned for that need other pin directions (target-spec row 13).
- **Firmware can write program memory**, which DR 0013's boot ROM and any
  runtime protocol swap need.
- **Verification obligations**, mirrored in `spec/verification-plan.md`:
  - `no_data_dependent_latency` extends to `WCTL`/`RCTL` with the per-`k`
    latency table above.
  - A control-register bench checks reset values, readback, reserved-index
    behaviour and the fixed stall.
  - A **silicon-true pad model** (per-pin `uio_oe`/`uio_out`/pull-up) replaces
    the bench-composed I2C bus, and the I2C evidence re-runs on it.
  - The CRC is checked against an independent CRC-16/XMODEM implementation
    (Python's `binascii.crc_hqx`), not this repo's own.
  - All of the above also runs at gate level.
- **Tooling.** `firmware/tools/asm.py` gains `WCTL`/`RCTL` and named indices.
  `scripts/check_protocol_pin_roles.py`'s `top_uio_oe` pattern changes from a
  constant to "driven by the core's pin-mode logic". `info.yaml`'s `uio` pins
  become "firmware-configured", and the datasheet documents the reset state.
- **Area.** The first estimate, "about 5 registers and a mux", was low: the
  registers listed above come to 62 flip-flops, and the 16-bit-per-word CRC,
  the read mux and the port arbitration account for most of the new logic.
  Measured on commit `4ff0e14` (2026-10-09), the control space alone, each
  flow named per `CLAUDE.md`:
  - **klt/Yosys**, standard-cell area: 568 instances, 10,323.26 um^2 ->
    1,087 instances, 17,460.42 um^2 (+69.1 %)
    (`verification/records/synthesis-baseline/records/20261009-202909-4ff0e14.md`).
  - **LibreLane**, placed standard-cell area: 14,818.2 -> 24,133.3 um^2;
    utilization of the unchanged die 33.90 % -> 41.25 %; worst setup slack
    9.62 -> 8.53 ns at the 20 ns constraint
    (`verification/records/librelane-corner-timing/records/20261009-203554-4ff0e14.md`).
  - Flip-flops, both flows agree: 99 -> 161.

  The two flows' synthesis figures differ, as the records explain; neither is
  picked over the other. DR 0013's boot ROM adds to this: the newest records
  (`20261009-222403-1dc1842` and `20261009-221236-1dc1842` in the same
  directories) give 1,189 instances / 19,451.43 um^2 (klt/Yosys) and
  26,123.7 um^2 at 42.82 % utilization (LibreLane). The 2x2 budget is DR 0014
  / #129's question, not this record's.

## Open items

1. Whether `RCTL` of `UIO_*` should return the effective `uio_oe` rather than
   the register value. Proposed: the register value. The effective value is
   derivable, and a read should not depend on `uio_out` timing.
2. Whether `RUN` should be allowed outside the boot ROM. Proposed: yes, as a
   fixed-latency computed jump. It is the one indirect jump in the ISA, and a
   protocol dispatcher can use it.
