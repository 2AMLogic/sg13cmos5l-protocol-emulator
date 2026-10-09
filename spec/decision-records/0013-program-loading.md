# 0013: Program Loading — A Firmware Boot ROM over an Unbrickable Serial Recovery Path

Status: **Proposed 2026-10-09.** It goes to ratification through the
two-key (`RATIFY-KEY`) mechanism on the PR that carries it (`spec/README.md`).
That mechanism has never run here (DR 0006, issue #44), so this record is a
proposal like DRs 0001–0005, 0007, 0008, 0010 and 0012. It makes no
target-spec row met.
Date: 2026-10-09
Issues: #118, #131, #132 (context); depends on DR
[`0012`](0012-control-space-and-runtime-pin-direction.md).

## Context

The organizers' 2026-10-09 entrant update (quoted verbatim in issues
#129–#134) made loading a judged design surface with a hard operational
constraint:

> How does the program get loaded? That's part of your design. The
> microcontroller on the demo board is the natural host, but any documented
> host works.

> When your design is deselected it's powered down and loses its state, so
> plan to reload the program after it's selected again.

> Unlike an FPGA, flops don't start at 0, so your design needs to use the
> reset signal (rst_n) to get into a known state.

DR 0001's loader samples `ui_in[7]` (`MODE`) at `rst_n` release. With `MODE`
high, it shifts one bit per clock from `ui_in[0]` into the SRAM. With `MODE`
low, it **runs program memory from address 0**. That loader has three
problems the update exposes:

1. **After a power-up or a reselect, `MODE` low runs uninitialized SRAM.**
   The macro's contents are undefined at that point, so the design can
   execute garbage and drive pins. Today's reset leaves `uio` as inputs only
   because `uio_oe` is hardwired to 0, and DR 0012 removes that.
2. **Every load needs a host that drives `clk` and `rst_n` and holds two pins
   in lockstep, and nothing checks the load.** One missed or extra clock
   edge silently misaligns every word after it. Row 6's "program-dump
   readback path" was never built.
3. **It demonstrates nothing.** A shift register says nothing about the
   architecture. The organizers' main criterion is reprogrammability, and
   the way programs reach the chip is the first place to show it.

Tiny Tapeout's published pinouts (https://tinytapeout.com/specs/pinouts/,
read 2026-10-09) set the physical options:

- The demo board's MCU bridges USB-UART to **RX `ui_in[1]`, TX `uo_out[0]`**
  ("option B"), or RX `ui_in[3]` / TX `uo_out[4]` ("option A").
- The **QSPI flash/PSRAM Pmod** (mole99/qspi-pmod) puts flash CS0 on
  `uio[0]`, SD0/MOSI on `uio[1]`, SD1/MISO on `uio[2]` and SCK on `uio[3]`.
  That matches the standard SPI Pmod pinout.

## Decision (proposed): three layers

### Layer 1: serial recovery load (DR 0001, kept, plus an integrity check)

The `MODE`-high load protocol is unchanged, pin for pin and cycle for cycle.
It is the **unbrickable path**: it needs no firmware and no ROM, so a ROM bug
can never lock a chip out. Added:

- Every committed word updates DR 0012's `PM_CRC` (CRC-16/XMODEM).
- **While still in load phase**, `uo_out` presents the running CRC: the low
  byte when `ui_in[1] = 0`, the high byte when `ui_in[1] = 1`. `ui_in[1]` has
  no role during load. The host reads both bytes before dropping `MODE` and
  compares them with its own CRC of the image. A mismatch means it reloads,
  and never runs.
- When `MODE` drops, behaviour is as today: run program memory from 0.
  `BOOT_STATUS[0]` is set, so the loaded program can tell it was
  serial-loaded.

### Layer 2: on-chip boot ROM, written in this ISA

At `rst_n` release with `MODE` **low**, fetch comes from a small **boot ROM**
instead of program memory. `BOOT_STATUS[1]` is set while it runs. The ROM is
synthesized as logic, registered to match the macro's one-cycle read so the
fetch stage is unchanged, and capped at **128 words**. Its contents are a
**program in this ISA**, assembled by the DR 0003 assembler and committed
byte for byte like any other firmware image. The ROM netlist is generated from
that image. The boot program reads two **strap pins**, `ui_in[6:5]` (the demo
board's input DIP switches), and branches:

| `ui_in[6:5]` | Boot program | Pins | Host |
|---|---|---|---|
| `00` (default, all switches off) | **UART load**: receive a framed image, write it through `PM_ADDR`/`PM_DATA_*`, verify, report, `RUN 0` | RX `ui_in[1]`, TX `uo_out[0]` (Tiny Tapeout "option B") | the demo board's MCU as a USB-UART bridge, so **any PC over USB**, or any 3.3 V UART |
| `01` | **SPI-flash boot**: drive flash CS0/SCK/MOSI as outputs through `UIO_DIR`, read 512 bytes from flash address 0 with command `0x03` (single-bit SPI), write and verify, `RUN 0` | Tiny Tapeout QSPI Pmod pinout on `uio[0..3]` | **none**: standalone after reset |
| `10` | **Warm start**: verify the image already in program memory (CRC over 256 words against a signature word) and `RUN 0`. If it fails, fall through to UART load | — | none, for an `rst_n` button press while the design stays selected |
| `11` | reserved; behaves as `00` | | |

**UART framing (the baseline):**
- 8N1 with a fixed divisor of **434 core cycles per bit**, which is
  115,200 baud at the 50 MHz row-4 clock. The datasheet gives the formula for
  other clocks.
- Frame: `0xA5`, word count `N` (1–256, sent as `N−1`), `2N` bytes
  big-endian, then the image's CRC-16.
- The ROM checks `PM_CRC` against the trailer and answers `0x06` + CRC on
  success or `0x15` + CRC on failure. It never runs a failed image.
- Auto-baud (timing a `0x55` sync byte) is a candidate refinement for the
  implementation issue, not a requirement.

**Why it matters for judging:** the chip loads its own programs **using its
own protocol firmware**: UART receive, and SPI controller reads from a flash
part. The boot programs are ordinary firmware, so changing the boot medium
needs a new ROM image and no new hardware. The same `WCTL PM_*` path lets an
ordinary running program load the next protocol (a runtime swap), which is
the most direct demonstration of target-spec row 13.

### Layer 3: host tooling and documented contracts

- **`loadseq` (issue #118)** produces both host artifacts from a committed
  `.hex`: the layer-1 pin sequence for the demo board's MCU, with the CRC
  check, and the layer-2 UART frame for a PC.
- **The datasheet (`docs/info.md`) states the reload contract.** After every
  power-up or reselect, assert `rst_n`. Then either fit a flash Pmod (strap
  `01`, and reset is enough), send a UART frame (strap `00`), or serial-load
  (`MODE` high). Required external parts (flash Pmod, I2C pull-ups) are
  listed there, per the organizers' "please document anything your design
  needs" and issue #133.

## Integrity: why a CRC in hardware does not breach `CLAUDE.md`'s rule

`CLAUDE.md` bars fixed-function peripherals for target protocols "unless a
decision record admits it and says why the ISA could not". The `PM_CRC`
register is not a protocol peripheral. It checks writes into program memory.
On layer 1 the ISA *cannot* compute it, because no firmware runs during a
serial load. On layer 2 the boot ROM could compute it in firmware, but sharing
one CRC register for both paths keeps the host-side check identical and costs
roughly 16 flops and an XOR tree. Whether a CRC is offered *to protocol
firmware* (USB CRC5/16, Ethernet CRC32) is #130's question and is not decided
here.

## Alternatives considered

1. **Serial load only (status quo) plus a CRC.** The cheapest option.
   Rejected as the *only* path: it keeps a clock-and-reset-capable host
   mandatory after every reselect and demonstrates nothing. It is kept as
   layer 1.
2. **A hardware SPI-flash boot state machine** (a fixed reader copying flash
   into SRAM). Rejected: it is a fixed-function SPI controller in RTL. Layer
   2's strap `01` does the same job in firmware.
3. **Execute in place from external flash or PSRAM.** It would remove the
   256-word limit. Rejected: fetch latency would depend on the external part,
   which breaks target-spec row 3, the property the design stands on.
4. **Byte-parallel load over all eight `ui_in` pins.** Rejected: speed is not
   the problem (4,096 clocks is milliseconds even at a slow manual clock), and
   it occupies six more pins during load.

## Consequences

- **Target-spec row 6** gains a second load path. The serial path's pins,
  cycles and semantics stay as DR 0001 has them.
- **Target-spec row 14:** after power-up, the design never executes
  unverified program memory. `MODE` low now means "boot ROM", not "run SRAM".
  This is a **behaviour change** for any host that relied on reset-with-
  `MODE`-low running a previously loaded image. Only the cocotb benches did
  that, and they always serial-load first. The `10` strap preserves a
  verified warm start.
- **Area:** about 128×16 bits of ROM as logic, plus the CRC, plus the
  fetch-source mux. Both flows measure it. If it threatens the 2×2 row-7
  budget, #129 decides.
- **Verification**, added to `spec/verification-plan.md` §7:
  - one bench per boot program, each with an **independent host model**: a
    UART host that frames and checks, and a SPI flash behavioural model that
    answers `0x03` reads
  - the layer-1 CRC exposure checked against `binascii.crc_hqx`
  - ROM image freshness checked like the other `.hex` files
  - power-up and reselect cases under row 14's random-initial-state run
  - all of the above at gate level
- **Pin plan (DR 0010):** the UART boot uses Tiny Tapeout option B (RX
  `ui_in[1]`, TX `uo_out[0]`). Today's UART *profile* firmware uses `ui_in[0]`
  for RX. Aligning the profiles with Tiny Tapeout's recommended pinouts
  is #133's revision of DR 0010, which DR 0012's runtime direction makes
  possible without re-synthesis. That revision is made: DR 0010's "Target pin
  plan" puts the profile RX on `ui_in[1]` too, and the move is #155.

## Open items

1. **Image signature format for warm start (strap `10`).** Proposed: the last
   word holds the CRC of words 0–254, so a warm start is "CRC matches, then
   run".
2. **Whether the ROM should also offer an I2C-target or SPI-target load.**
   Deferred. They are good row-13 demonstrations once the role-reversal
   firmware exists, and they fit the 128-word cap only if UART and SPI-flash
   leave room.
3. **Exact ROM size.** 128 words is a cap, not an estimate. The first
   assembled boot image sets it, and anything over the cap returns to this
   record.
