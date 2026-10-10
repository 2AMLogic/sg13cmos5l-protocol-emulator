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

## Findings from building layer 1 (issue #137)

*Added 2026-10-09 by the layer-1 build. These are findings, not decisions.
The design above was built as written. Evidence:
`verification/records/load-integrity/`.*

1. **`uo_out` during a serial load conflicts with target-spec row 14(b) as
   worded.** Row 14(b) says `uo_out` "holds its documented reset value until
   a program writes" it. Under layer 1 `uo_out` carries `PM_CRC` bytes from
   the first committed word until `MODE` drops, and no program has written
   anything. Whatever is wired to `uo_out` sees that: a UART peer on
   `uo_out[0]` sees the line move, and an SPI peripheral sees its CS, SCLK
   and MOSI pins (`uo_out[0..2]`) move. In reset, and from the `MODE`-drop
   edge until the program's first `OUT`, `uo_out` is 0 as before. One of the
   two texts needs a sentence: either row 14(b) excepts the load-phase
   readout, or the readout moves off `uo_out`.
2. **A CRC that starts at 0 cannot see an all-zero image.** `PM_CRC` resets
   to `0x0000` (DR 0012), and zero words leave a zero CRC at zero, so an
   image of all zero words reads `0x0000` at any length, including no load
   at all. No truncation or edge fault of such an image is detectable. A
   non-zero initial value would close this. It would also change DR 0012's
   `PM_CRC` and the host-side reference, so it is not done here.
3. **One doubled clock edge is undetectable because it is harmless.** A
   repeat of the last bit of the image, or of any bit in a run of equal bits
   that reaches the end of the image, leaves every committed word intact.
   The spare bit is a partial word, discarded when `MODE` drops. The readout
   matches, correctly. "A doubled clock edge must mismatch"
   (verification-plan §7) holds for every doubled edge that changes what
   memory holds, which is what the bench checks.
4. **DR 0010's pin table still gives `ui_in[1]` and `uo_out[7:0]`
   `load_role: none`.** Layer 1 gives both a load-phase role. The table was
   not edited in this issue; `scripts/check_protocol_pin_roles.py` was taught
   the readout mux instead, so it still checks that the core's port is the
   whole of `uo_out` in run phase.
5. **Area**, each number with its flow, is in
   `verification/records/synthesis-baseline/` (klt/Yosys) and
   `verification/records/librelane-corner-timing/` (LibreLane) at the
   records minted for issue #137.

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

## Implementation notes and findings (issue #138, 2026-10-09)

> Added when layer 2's infrastructure was built (the ROM, the fetch-source
> switch and the warm start; the UART and SPI-flash boot programs are issues
> #139 and #140). The Decision above is left as written. Nothing here
> changes it: these are what building it showed, recorded per the issue's
> instruction that a finding goes in the record and the design is not
> quietly changed. This record is still **Proposed**. Evidence:
> `verification/records/boot-rom/`.

**Built as decided.**

- With `MODE` low at `rst_n` release the core decodes the boot ROM
  (`rtl/protocol_boot_rom.v`), and `BOOT_STATUS[1]` reads 1 for as long as it
  does. A `WCTL RUN` switches the fetch source to program memory and sets
  the PC; nothing switches it back short of a reset. A serial load (`MODE`
  high) never decodes a ROM word and is unchanged, pin for pin and cycle for
  cycle: every existing bench's console output is line-identical before and
  after.
- The ROM is logic behind one register, so its read has the macro's
  one-cycle delay and the fetch stage's cycle timing is the same from either
  source. Addresses past the image read as `HALT`.
- The ROM's Verilog is generated from the committed image
  `firmware/build/boot/boot_rom.hex`, which the DR 0003 assembler assembles
  from `firmware/asm/boot/boot_rom.asm`. `firmware/tools/check_firmware.py`
  checks both links.

**One thing built beyond the text.** While the ROM is the fetch source the
program memory does not read the macro for fetch at all (the core's
`pm_fetch`). The Decision only requires that unverified memory is not
*executed*; without the gate it would still be read every cycle and
discarded at the decoder. With it, "fetch comes from a boot ROM instead of
program memory" is true at the macro's pins, and the macro idles during
boot. Cost: one AND term on the macro's read enable.

**Open item 1, the warm-start signature: built as proposed, with one
finding.** Word 255 holds the CRC-16/XMODEM of words 0–254, high byte of
each word first.

- *How the check runs.* DR 0012's `PM_CRC` covers words **committed** to
  program memory and nothing else, and § Integrity above chooses to share
  that one register rather than compute a CRC in firmware. So the boot
  program reads each word and commits the same word back to the same
  address. The array ends as it began and `PM_CRC` ends as the CRC of all
  256 words, which for this CRC is zero exactly when word 255 equals the CRC
  of words 0–254. This is buildable and is what was built; it is recorded
  because "verify the image already in program memory" does not say that
  verifying means rewriting. A warm start therefore performs 256 writes, and
  takes a fixed 2,323 cycles from the boot program's first instruction to
  the image's first.
- *Finding F1: the all-zero image verifies.* `PM_CRC` starts at `0x0000`
  (DR 0012), and the CRC of zeros from a zero seed is zero. 256 zero words
  are therefore their own valid signature, and strap `10` runs them. They are
  256 `NOP`s that wrap; nothing is driven. This is the one image for which
  "never executes unverified program memory" (target-spec row 14 (c)) holds
  only because executing it is harmless, not because it was rejected. An
  SRAM that powers up all-zero would pass. Closing it needs a nonzero CRC
  seed or a magic word in the signature, which changes DR 0012's register
  definition or this record's signature format. **Not changed here.** The
  behaviour is pinned by a test
  (`test_warm_start_all_zero_image_is_the_known_weak_case`) so it cannot
  change unnoticed, and the question is issue #168.
  *Superseded 2026-10-10 (issue #168): the warm start now refuses a
  signature of `0x0000` (option 4). The text above is kept as the finding
  was made; the decision and its reasons are in "Implementation notes and
  findings (issue #168, 2026-10-10)" below.*
- *What the image is entered with.* The boot program restores `R0`–`R3`, `Z`
  and `C` to their reset values before `RUN 0`, so a warm-started program
  starts in the state a serial-loaded one does, with three differences it
  can observe: `BOOT_STATUS` reads `0x00` (a serial-loaded program reads
  `0x01`); `PM_CRC` reads `0x0000`, the residue (after a serial load it
  reads the CRC of the loaded words, which is also zero for a full signed
  image); and the `PM_DATA` latches hold word 255's bytes.

**Open item 3, the ROM size.** The first image is **30 words** of the
128-word cap: 9 for the strap dispatch, 2 for the stubs, 19 for the warm
start. That leaves 98 for the UART load and the SPI-flash boot together.
For scale, and as a risk for #139 and #140 rather than a result: the
committed 434-cycle UART receiver `uart_rx_115200.asm` is 168 words on its
own, because its bit blocks are unrolled. A boot-ROM receiver has to be
written as a loop. If the two boot programs do not fit in 98 words the
question returns to this record, as open item 3 says.

**Straps are firmware.** The boot program's first instruction is an
ordinary `IN R0, UI_IN`; there is no strap latch. It samples `ui_in[6:5]`
on the third clock edge after `rst_n` is released (the edge that retires
it), so the host must hold the straps until then. A loaded program sees
those two pins as plain input bits.

**The stubs drive nothing, including the UART's TX.** Straps `00`, `01` and
`11` reach a `HALT` with `uo_out` at its reset value, `0x00`. `uo_out[0]` is
the UART boot's TX (Tiny Tapeout option B), and an idle UART line is high;
a host on that pin sees a continuous break until #139 replaces the stub.
The stub leaves it because "every pin at its reset value" is the property
the row-14 evidence checks. What TX does before a frame arrives is #139's
decision.

**Correction to § Consequences.** "Only the cocotb benches did that, and
they always serial-load first": confirmed for the benches. No top-level
bench releases reset with `MODE` low; the one helper that does
(`verification/_dut.py`'s `reset`) has no caller. But the benches were not
the only dependents. Both formal harnesses modelled the run phase as "`MODE`
low, run program memory" with a single free program table. They now model
the ROM as a second free table and the fetch source as the design has it;
`pin_write_latency`'s shadow model derives the source itself.

**Area and timing, each number with its flow** (§ Consequences: "Both flows
measure it. If it threatens the 2×2 row-7 budget, #129 decides"):

| | klt/Yosys flow (synthesis, cell area only) | LibreLane flow (placed and routed, 20 ns) |
|---|---|---|
| Standard-cell area, before → after | 17,460.42 → 19,451.43 µm² (+1,991.00, +11.4 %) | 24,133.3 → 26,123.7 µm² placed (+1,990.4, +8.2 %) |
| Flip-flops | 161 → 176 | 161 → 176 |
| ROM alone, 30 words | 104 instances, 1,531.20 µm², 14 flip-flops | not separable |
| Utilization of the 2×2 die | not measured by this flow | 41.25 % → 42.82 % |
| Worst setup slack (slow / typ / fast) | **no timing**: this flow cannot time the design (`sta-corner-sweep`) | +7.422 / +12.168 / +14.473 ns; was +8.529 / +12.866 / +14.400 |
| Worst hold slack (slow / typ / fast) | — | +0.604 / +0.300 / +0.119 ns |
| Setup and hold violations | — | 0 at all three corners |

Records: `verification/records/synthesis-baseline/records/20261009-222403-1dc1842.md`
and `verification/records/librelane-corner-timing/records/20261009-221236-1dc1842.md`
(`gds` run 37996177546). The two flows differ by about 3 % on synthesis
area, as before, and agree on what this change costs. LibreLane reports one
new max-slew violation at the slow and typ corners; it is not a setup or
hold violation and is recorded there. Two of the ROM's 16 output flops are
optimized away because bits 4 and 7 are zero in every word of this image; a
later image can bring them back.

**The 2×2 budget (row 7) is not threatened.** The die is unchanged and 57 %
of the core is unoccupied, so nothing is raised on #129 or against DR 0014.
The slow-corner setup slack fell by 1.1 ns of 20; the remaining boot
programs add ROM words, not another mux.

## Implementation notes and findings (issue #140, 2026-10-10)

> Added when strap `01`, the SPI-flash boot, was built. The Decision above is
> left as written; nothing here changes it. These are what building it
> showed, recorded per the issue's instruction that a finding goes in the
> record and the design is not quietly changed. This record is still
> **Proposed**. Evidence: `verification/records/boot-spi/`. Guide to putting
> an image on the flash: `docs/spi-flash-boot.md`.

**Built as decided.** Strap `01` makes flash CS0 `uio[0]`, MOSI `uio[1]` and
SCK `uio[3]` outputs with `WCTL UIO_DIR` (`0x0B`), and leaves MISO `uio[2]`
and every other `uio` an input. It runs one single-bit SPI mode 0
transaction, command `0x03`, address `0x000000`, 512 bytes, writes each word
through `PM_DATA_HI`/`PM_DATA_LO`, verifies with `PM_CRC` against the
image's signature (word 255 = CRC-16/XMODEM of words 0-254, the warm start's
format), and then either takes the warm start's hand-over (`R0`-`R3`, `Z`,
`C` at reset values, `RUN 0`) or halts with every `uio` an input. It is
64 words (`spi_boot` to `spi_fail`, `firmware/asm/boot/boot_rom.asm`). From
its first instruction to the image's first instruction: **58,793 cycles**,
the same for every image (the loops have constant trip counts), 1.18 ms at
the unconfirmed 50 MHz row-4 clock. SCK is high for 2 cycles and has a
period of 14, 16 or 17: at most f_clk/14.

**Finding F2: the PSRAM chip selects default to deselected.** The Tiny
Tapeout QSPI Pmod (`mole99/qspi-pmod`, `main`, read 2026-10-10) carries
three resistors `R1`-`R3` of 10 k from +3.3 V to the Pmod-side nets of
`PMOD1` (`uio[0]`, flash CS0), `PMOD7` (`uio[6]`, RAM A CS) and `PMOD8`
(`uio[7]`, RAM B CS) (`qspi-pmod.kicad_sch`; the schematic's text labels the
group "CS pull up", and the pull-ups sit on the connector side of the CS
cut link). The README says "a 1k resistor pulls up the chip's /CS" when a
trace is cut. **The schematic value (10 k) and the README (1 k) disagree;
nothing was measured.** Both give the same default: with the design leaving
`uio[6]` and `uio[7]` inputs, as it does, both PSRAM chip selects float to
high and both RAMs are deselected, so they cannot drive MISO against the
flash. The bench models that as a pull-up on `uio[0]`, `uio[6]` and
`uio[7]` and requires `uio_oe[7:4]` and `uio_oe[2]` to be 0 on every edge of
every boot (`assert_pin_discipline`). Two corollaries, both from the same
schematic: the flash's CS0 has the same pull-up, so before the ROM drives it
(reset, power-up) the flash is deselected, and when the program releases the
pins at the end CS0 is held high by the pull-up, though the program drives
it high for two cycles first and the bench fails a boot that leaves that to
the pull-up (`cs-left-to-the-pull-up`); and `uio[4]`/`uio[5]` (SD2/SD3) have
no pull-up, so they float. `0x03` does not use them provided the flash's
Quad Enable bit is set (the Pmod ships that way, per Tiny Tapeout's guide);
with QE clear the flash's `/WP`/`/HOLD` use those pins and a floating
`/HOLD` can stall a read. That is a hardware precondition recorded in
`docs/spi-flash-boot.md`, not something the design can do anything about.

**Built beyond the text: a signature of `0x0000` is refused.** DR 0013's
Finding F1 (the all-zero image verifies) matters more here than for the
warm start. A warm start sees zeros only if the SRAM powered up as zeros
and the result is 256 `NOP`s. The flash boot sees 256 zero words whenever
MISO reads 0: no Pmod fitted with the line pulled low, a dead flash, a
wrong strap setting with the part not powered. That would be reported as a
good image and `RUN` it, so the program also refuses an image whose word
255 is `0x0000` (6 words: set `PM_ADDR` to 255, read the word back, `OR`
its bytes). The cost is one valid image in 65,536 (one whose real CRC is
zero), which `firmware/tools/mkflash.py` refuses to build and tells the user
to re-pad. An all-`0xFF` flash (blank, or no Pmod with MISO pulled high)
needs no extra rule: its CRC is `0x7FA1`. This does not close F1 for the
warm start, which is still issue #168. *(2026-10-10: it now does; issue
#168 applies the same refusal to the warm start. See the notes of issue
#168 below.)*

**Finding F3: the two boot programs use 93 of the 128 ROM words, leaving 35
for the UART load.** Open item 3 said the first image sets the size and
that anything over the cap returns to this record. Before this issue the ROM
was 30 words (9 dispatch, 2 stubs, 19 warm start). The SPI-flash boot is 64
and replaces one stub word: 4 to set the pins up, 3 constants, 17 for the
chip-select fall, command and address clocks, 21 for the data loop and word
commit, and 19 for the release, the two checks and the hand-over. That
leaves **35 words for #139**, where
this record, written when 98 were free, expected the two programs to share
them. The 168-word `uart_rx_115200` receiver is far over it, and a
looped receiver plus the `0xA5`/count/CRC framing, the CRC check and the
`0x06`/`0x15` reply does not obviously fit in 35. This issue does not raise
the cap, shrink the SPI program, or move work into hardware. *(2026-10-10,
issue #168: the warm start's zero-signature refusal adds 2 words; the ROM
is now 95 words and 33 are left. See the notes of issue #168 below.)*
Options for
#139 and for ratification, none taken here: raise the cap (the ROM is
logic, and the measurement below gives its price: 29-34 um^2 per word on
either flow, so the 35 words that the UART load would want beyond today's
cap, or the 98 more of a doubled cap, are about 1.0-1.2 k um^2 or 2.8-3.3 k
um^2 on a die that is 55 % unoccupied; but that is #129's call, not a
firmware issue's); cut the SPI program (the 6-word signature
check is the cheapest to lose, and costs the dead-MISO rule above); or let the UART load be a short stub that loads a
longer loader into program memory. The first two change numbers this record
states; the third changes the DR 0013 UART design.

**Finding F4 (2026-10-09, issue #196): the flash Pmod owns the `uio`
header.** The QSPI Pmod uses `uio[0..7]` (CS0 `uio[0]`, SD0 `uio[1]`, SD1
`uio[2]`, SCK `uio[3]`, SD2 `uio[4]`, SD3 `uio[5]`, CS1 `uio[6]`, CS2
`uio[7]`; Tiny Tapeout pinouts), and DR 0010's SPI profile (CS `uio[0]`,
MOSI `uio[1]`, MISO `uio[2]`, SCK `uio[3]`) and I2C profile (SCL `uio[2]`,
SDA `uio[3]`) use the same pins. Decided: one device on the `uio` header at
a time. After a strap `01` hand-over a user SPI program talks to the flash,
no I2C peripheral can share the header, UART is unaffected, and a user SPI
program can erase or overwrite the boot image (WREN `0x06`, then erase/program;
opcodes recalled, not re-read from the flash datasheet). The shipped
`spi_mode0` sends `0xA5` and `0x3C` and cannot arm a write. To use another
SPI device, remove the Pmod after boot (or boot with strap `00`/`10`): the SPI
CS is `uio[0]`, the flash's CS0, so holding CS0 high does not isolate it; it
only isolates the flash from a program that leaves `uio[0]` alone, such as I2C. No pin,
RTL or hardware change; the bottom-row Pmod variants (`uio[4..7]`) remain a
possible future option. See DR 0010, "Target pin plan", and
[`docs/info.md`](../../docs/info.md).

**What the flash model is, and is not.** `verification/reference_models/
spi_flash.py` answers `0x03` from a byte image and checks SPI mode 0:
SCK idle low at CS edges and while CS is high, CS setup/hold and high time,
MOSI setup and hold, SCK pulse widths and the READ frequency ceiling, and
that a rising edge comes at least `t_clqv` after the falling edge that
selected the bit. The numeric limits are the W25Q128JV's **as recalled by
the author, not re-read from the datasheet**; the bench clock (20 ns)
satisfies every one with a wide margin. They are constructor parameters.
This is a model of a conforming slave and says nothing about a real part's
timing or the Pmod's trace delays; the Pmod has an optional 22 pF "CLOCK
cap" on SCK that the model does not include.

**Pad assumptions the bench makes.** The design's `uio_oe`/`uio_out` are
resolved through `verification/uio_pads.py` with pull-ups on `uio[0]`,
`uio[6]` and `uio[7]`. A floating SCK or MOSI (after the program has
released the pins) reads as low to the flash model; CS0 is high by then, so
a real flash ignores them. Zero delay, logical levels.

**Area and timing of the 93-word ROM, each number with its flow** (§
Consequences: "Both flows measure it"). The change is +63 ROM words and +2
flip-flops: bits 4 and 7 of the ROM word, zero in every word of the 30-word
image (issue #138's notes), are used by the SPI program, so the two output
flops that were optimized away are back.

| | klt/Yosys flow (synthesis, cell area only) | LibreLane flow (placed and routed, 20 ns) |
|---|---|---|
| Standard-cell area, 30 -> 93 words | 19,451.43 -> 21,263.63 um^2 (+1,812.21, +9.3 %) | 26,123.7 -> 28,266.5 um^2 placed (+2,142.8, +8.2 %) |
| Instances | 1,189 -> 1,366 | 1,680 -> 1,946 |
| Flip-flops | 176 -> 178 | 176 -> 178 |
| ROM alone | 104 -> 274 instances, 1,531.20 -> 3,116.76 um^2 | not separable |
| Utilization of the 2x2 die | not measured by this flow | 42.82 % -> 44.51 % |
| Worst setup slack (slow / typ / fast) | **no timing**: this flow cannot time the design | +7.422 / +12.168 / +14.473 -> +6.300 / +11.499 / +14.327 ns |
| Worst hold slack (slow / typ / fast) | n/a | +0.604 / +0.300 / +0.119 -> +0.565 / +0.282 / +0.114 ns |
| Setup and hold violations | n/a | 0 at all three corners, before and after |

Records: `verification/records/synthesis-baseline/records/20261010-020506-ed5f2d1.md`
(the baseline was re-measured with the same host tools: the host's Yosys
0.67 gives the same 19,451.43 um^2 for the 30-word tree as the earlier
record's 0.69) and
`verification/records/librelane-corner-timing/records/20261010-020340-ed5f2d1.md`
(`gds` run 38013383254, whose gl_test and precheck are green). The two
flows differ by about 3 % in absolute synthesis area, as before, and agree
on what the change costs, within 18 %. The LibreLane run shows the
max-slew violation of issue #138's notes gone and max-cap up by one at the
fast corner; neither is a setup or hold violation. The 2x2 budget is not
threatened (55 % of the core is unoccupied), so nothing is raised against
DR 0014 or on #129.

**Not claimed.** No real flash, Pmod, demo board or silicon was involved.
No timing against a part's datasheet. The DR 0013 UART load is #139.

## Implementation notes and findings (issue #168, 2026-10-10)

> Added when Finding F1 was closed for the warm start. The Decision above
> is left as written, and so is the text of every earlier finding; where
> this section changes a number or a conclusion, the earlier text carries a
> dated pointer here. This record is still **Proposed**. Evidence:
> `verification/records/boot-rom/` and the gate-level and LibreLane records
> named below.

**Finding F1, superseded 2026-10-10: a warm start refuses a signature of
`0x0000`.** Issue #168 listed four ways to settle F1; the fourth was found
by its curator on `main`. Chosen: **option 4.**

1. *A nonzero `PM_CRC` seed* (for example `0xFFFF`). Changes DR 0012's
   register definition, the host-side CRC of `loadseq` (#118) and the
   layer-1 readout (#137). **Not chosen here, and not rejected:** whether
   to change the seed is an open operator question (#166), and nothing in
   this change depends on the answer. The seed stays `0x0000`; DR 0012,
   `firmware/tools/loadseq.py` and the #137 readout are untouched. If a
   nonzero seed is adopted later, the all-zero image fails the CRC on its
   own and the refusal below becomes redundant for it but stays correct
   (it then refuses only images whose real CRC is `0x0000`, still 1 in
   65,536); whether to keep its two words is a question for that change.
2. *A magic word* in word 254. Changes open item 1's signature format and
   every tool that builds an image, and costs about four ROM words. Not
   chosen: option 4 closes the same hole for fewer words with no format
   change.
3. *Accept it.* Not chosen: it leaves target-spec row 14 (c) holding for
   this one image only because executing it is harmless.
4. *Refuse a zero signature, as the SPI-flash boot already does.*
   **Chosen.** It closes the warm-start hole without touching the register
   definition, the signature format or the host-side CRC, and both layer-2
   boot programs now agree on what a signed image is.

*How it is built.* The warm-start loop's last pass reads word 255 into `R0`
(high byte) and `R1` (low byte), so the check needs no read-back: `OR R0,
R1` / `BZ uart_load`, placed after the loop and before the CRC verdict.
**Two words**, against the SPI path's six. Sharing the SPI path's code was
considered and costs more: it reads word 255 back because its own loop
does not leave the word in registers, and a shared check would need a jump
in and a second fail target, since a failed warm start falls through to the
UART load (§ Decision, layer 2) while a failed flash boot halts. A refused
image falls through to the UART load like any other failed check, with
`PM_CRC` left at `0x0000`.

*Cost.* (a) The one valid image in 65,536 whose real CRC is `0x0000` must
be re-padded, by changing a filler word, exactly as for flash.
`firmware/tools/mkflash.py` already refuses to build such an image, and it
is the only tool in this repository that produces a signed image, in the
format both strap `01` and strap `10` read; its messages now say the warm
start refuses it too. `firmware/tools/loadseq.py` loads the words it is
given and appends no signature, so it needs no rule of its own: a host that
serial-loads a `mkflash.py` image gets the rule for free, and a host that
signs images by other means must apply it. (b) A passing warm start takes
two more cycles: word 0 now executes **2,325** cycles after the boot
program's first instruction (open item 1's bullet above says 2,323; that
was the design before this change), the same for every image. (c) Two ROM
words: see F3 below.

*What it does not change.* Any other image still passes the check exactly
when word 255 is its CRC, so random power-up contents escape with the
CRC's own odds (about 1 in 65,536), as before; F1 was the one image that
passed with certainty. Straps `00`, `01` and `11` are unchanged, and the
SPI-flash boot's cycle count (58,793) is unchanged.

*Evidence.* `verification/test_boot_rom.py`:
`test_warm_start_all_zero_image_is_the_known_weak_case` is replaced by
`test_warm_start_refuses_a_zero_signature` (the all-zero image, and the
probe program padded so that its real CRC is `0x0000`, which would drive
pins if it ran: neither runs) and `test_warm_start_runs_zero_padded_images`
(zero-padded images with nonzero signatures, including `0x00nn` and
`0xnn00`, still run on the predicted edge). `verification/boot_rom_mutants.py`
adds three controls (the refusal branch made a `NOP`, and the test reading
only one byte of the signature), each caught. The old pinning record stays
in `verification/records/boot-rom/`; the new one supersedes it.

**Finding F3, superseded 2026-10-10: the boot programs use 95 of the 128
ROM words, leaving 33 for the UART load** (was 93 and 35). Everything else
F3 says about #139 stands, with two fewer words.

**Area and timing of the 95-word ROM, each number with its flow** (§
Consequences: "Both flows measure it"). Before -> after is the 93-word ROM
of issue #140 (as re-measured with issue #173's A_REN buffer) -> this
change.

| | klt/Yosys flow (synthesis, cell area only) | LibreLane flow (placed and routed, 20 ns) |
|---|---|---|
| Standard-cell area | 21,263.63 -> 21,331.03 um^2 (+67.40) | 27,910.9 -> 28,255.7 um^2 placed (+344.8); its synthesis step 21,603.49 -> 21,859.63 um^2 |
| Instances | 1,366 -> 1,377 | 1,894 -> 1,890 placed; synthesis step 1,431 -> 1,422 cells |
| Flip-flops | 178 -> 178 | 178 -> 178 |
| ROM alone | 274 -> 286 instances, 3,116.76 -> 3,256.51 um^2 | not separable |
| Utilization of the 2x2 die | not measured by this flow | 44.23 % -> 44.51 % |
| Worst setup slack (slow / typ / fast) | **no timing**: this flow cannot time the design | +6.100 / +11.371 / +14.318 -> +5.621 / +11.049 / +14.100 ns |
| Worst hold slack (slow / typ / fast) | n/a | +0.557 / +0.278 / +0.112 -> +0.563 / +0.280 / +0.111 ns |
| Setup and hold violations | n/a | 0 at all three corners, before and after |

Records: `verification/records/synthesis-baseline/records/20261010-082700-704a3fb.md`
and `verification/records/librelane-corner-timing/records/20261010-084500-704a3fb.md`
(`gds` run 38037477407, all four jobs green). The flows agree that the area
grew and disagree on the sign of the synthesis cell-count change (+11 on
klt/Yosys, -9 on LibreLane's synthesis step); that is recorded in the
LibreLane record as a finding, not resolved by picking one. Max-slew
violations stay at 0 (issue #173's A_REN repair holds: 0.064 ns at the slow
corner); max-cap violations on the macro's `A_DOUT` are 3 / 3 / 3 (1 / 2 / 3
before), not setup or hold violations. The 2x2 budget is not threatened.
Gate level: the boot-ROM bench, including the zero-signature refusal, passes
on the LibreLane netlist of that run (`verification/records/firmware-gate-level/`).

## Implementation notes and findings (issue #139, 2026-10-10)

> Added when the UART load (strap `00`) was built. The Decision above is left
> as written. Nothing here changes it except where a finding below says a
> constant had to move, and that is flagged as a finding for this record to
> decide. This record is still **Proposed**. Evidence:
> `verification/records/boot-uart/`; the loader is
> `firmware/asm/boot/boot_rom.asm`, block `uart_load`.

**Built as decided.**

- Straps `00` and `11`, and a warm start whose check fails, run the UART load.
  RX is `ui_in[1]`, TX is `uo_out[0]` (Tiny Tapeout option B), 8N1 at 434 core
  cycles per bit. The frame is `0xA5`, `N-1`, `2N` bytes high byte first,
  CRC-16/XMODEM high byte first (`firmware/tools/loadseq.py IMAGE.hex --uart`
  writes it from a `.hex`). Words go through `PM_DATA_HI`/`PM_DATA_LO`; the loader
  compares `PM_CRC` with the trailer and replies `0x06` + `PM_CRC` and `RUN 0`,
  or `0x15` + `PM_CRC` and waits for the next `0xA5`. A failed image is never
  run. The reply carries the CRC the chip computed, high byte first, so a
  rejected host sees what arrived.
- It is firmware. The only hardware in the path is the `PM_*` access and
  `PM_CRC` that DR 0012 already admitted; there is no UART peripheral.
- Auto-baud (timing a `0x55` sync byte) was **not attempted**: the divisor is
  fixed. See F4 for why a loader that is already over its budget is the wrong
  place to add it.

**What the strap-`00` stub's note left open: what TX does before a frame
arrives.** The loader drives `uo_out[0]` high from its first instruction and
leaves it high between frames (an idle UART line), so a host sees an idle line
instead of the stub's continuous break. `uo_out[7:1]` stay 0.

**Finding F4: the UART load does not fit the proposed 128-word cap, and F3's
35 free words were short by 94.** The loader is **129 words**. The boot image
is **223**: 9 for the strap dispatch, 21 for the warm start, 64 for the
SPI-flash boot (#140) and 129 for the UART load. This record proposed 128
words for the whole ROM and noted "98 for the UART load and the SPI-flash
boot together"; F3 above counted 35 words free for the UART load once the
SPI-flash boot had taken its 64 (33 once #168's two words are counted, short
by 96). The reasons the loader is four times that are
the ISA's, not the loader's care:

| Part | Words |
|---|---|
| set-up (guard, TX idle, phase 0) | 6 |
| byte receiver: poll, delay, 8-sample loop | 24 |
| phase dispatch (6 phases) and trailer-high handler | 16 |
| trailer-low handler, `0xA5` handler, count handler, payload high/low handlers | 7 + 5 + 6 + 3 + 10 = 31 |
| transmitter: one byte (start, 8 data bits, stop) | 3 + 19 |
| reply sequencing (3 bytes) | 14 |
| verdict, hand-over, reject | 16 |

There is no call or return, so a routine used from six places is one block
plus a dispatch on a phase number, and the dispatch and the handlers are 47
words. With four registers the byte receiver needs three, so the state a
frame needs (phase, words left) lives in `R3` and in a control register. The
ISA has no immediate form of `AND`, so an unrelated `ui_in` bit cannot be
masked without a register or eight shifts, and the eight shifts are the single
largest part of the receiver (8 of its 24 words). The transmitter needs all
four registers, so its caller's state goes in `PM_ADDR`.

What was done about it: the generator's cap (`ROM_WORDS_MAX`) is **256**, the
8-bit fetch address space and the most the ROM's `case` can address, instead
of 128. That is a change to a number this record proposed, made so the UART
load could be built and tested at all, and it is **not decided**. It is
recorded here, in `firmware/tools/gen_boot_rom.py` and in
`firmware/tools/test_gen_boot_rom.py`, and it is the first of the options F3
listed. The others:

1. keep 256 as the ROM's size (what the code does now; 33 words of address
   space are left);
2. raise the PC for the ROM only, which is an architecture change;
3. cut the loader, for example by dropping the reply's CRC, the `0xA5` resync
   or the count byte, which the issue's frame keeps;
4. cut the SPI-flash boot, or drop the ROM for one of the two media; or load
   a longer loader into program memory from a short stub (F3's other option),
   which needs a first stage that is itself a UART receiver.

*Area and timing, each number with its flow* (against the 95-word ROM of the
two boot programs the #168 notes above measure). **klt/Yosys flow** (cell area
only; `klt synthesize flow/synthesize-protocol-emulator.json`, klt v0.7.0,
Yosys 0.67): the top goes from 1,377 instances and 21,331.03 µm² to **1,614
instances and 23,729.03 µm²** (178 flip-flops, unchanged), **+237 instances and
+2,397.99 µm² (+11.2 %)**. The ROM alone is 286 instances and 3,256.51 µm² at 95
words and **545 instances and 5,837.45 µm²** at 223: **+2,580.95 µm² for 128
words, about 20 µm² per word**, a little under the ~30 µm² per word the #140
notes measured, because the receiver and transmitter share logic. This flow
reports no timing for this design. **LibreLane flow** (the `gds` workflow, run
38054423540 at `a0f91e3`, LibreLane 3.1.0.dev3, post-route, 20 ns): placed
standard cells **28,255.7 → 30,745.0 µm² (+2,489.3, +8.8 %)**, 1,890 → 2,210
instances, utilization 44.51 % → **46.47 %** on the unchanged die (about 53 % of
the core unoccupied), routed wirelength 85,380 → 119,187 µm. Timing still closes
with **zero setup and zero hold violations at all three corners**, with less to
spare: worst setup slack 5.621 → **3.631 ns** (slow), 11.049 → 9.863 ns (typ),
14.100 → 13.454 ns (fast); worst hold slack 0.1108 → 0.1043 ns (fast). Max-cap
violations (SRAM `A_DOUT`) went 3/3/3 → 3/3/4 (slow/typ/fast) and **max-slew
0/0/0 → 1/1/1, on the SRAM's `A_WEN`** (0.909 ns against a 0.595 ns limit at the
slow corner): a different macro pin from the A_REN pin #173 repaired, which stays
clean (0.104 ns); the violating pin moves with the placement re-roll (an
earlier layout of this branch had it on `A_DIN[0]`), tracked as issue #201. None
is a setup or hold violation, and the flow does not fail on them. LVS, route DRC
and antenna are clean and the Tiny Tapeout precheck is green. LibreLane's own
synthesis step reports 1,422 → 1,704 cells and 21,859.63 → 24,237.28 µm² before
placement, +2,377.7 µm²: the two flows agree on what the UART load costs
(+2,398.0 and +2,377.7 µm² at synthesis, 1 % apart). The template's `gl_test`
job passes 3/3 on this netlist, including a 3-word UART frame loaded and run on
gates. The 2×2 budget (row 7) is not threatened, but **the setup margin at the
slow corner is now 3.6 ns of a 20 ns period**, so a further ROM growth of this
size is the thing to watch. Gate level (zero delay) for the cocotb benches
including both loaders', the reset/power-up bench, and the SDC-aligned SDF run
(12 passed, 0 failed, 1 skipped at all three corners, as for the 95-word ROM)
are in `verification/records/firmware-gate-level/`, `reset-power-up/` and
`post-layout-sdf-regression/`; the area and timing records are
`verification/records/synthesis-baseline/` and `librelane-corner-timing/`.

**Finding F5: the loader keeps a byte in `UIO_DIR`, so `uio_out` is `0xFF`
while it runs.** The receiver has no register to spare for "words left". The
only writable, readable control registers are `UIO_DIR`, `UIO_OD` and
`PM_ADDR`, and `PM_ADDR` is the write pointer. `UIO_DIR` is safe as storage
only while no `uio_oe` bit can follow it: with `UIO_OD = 0xFF` and `uio_out =
0xFF`, DR 0012's rule `uio_oe = (od & ~out) | (~od & dir)` is 0 whatever `dir`
holds. So the loader sets that guard first and clears it, in the order `UIO_DIR`,
`UIO_OD`, `uio_out`, before `RUN`, so that no cycle drives a pin (clearing
`uio_out` first drives every `uio` pin low for two cycles, which a negative
control checks). Consequences: `uio_oe` is 0 at every edge for as long as the
boot program runs, which is what target-spec row 14 (b) asks, but `uio_out`
reads `0xFF`, not its reset value 0, while the UART loader is waiting. Row 14
(b) as written talks about driven pins, so it holds; a checker that compares
`uio_out` with its reset value during the load would see a difference, and
`test_boot_rom.py` now allows exactly this state for the UART paths.

**Finding F6: recovery from a lost byte.** The loader has no timeout, and a
frame whose length is wrong leaves bytes the loader reads as the start of a
frame whenever one is `0xA5`. A host that has lost sync recovers by pulsing
`rst_n`, or by sending non-zero filler until the loader answers `0x15` (about
2N+2 bytes at most). **Zero filler does not recover:** the CRC of a message
followed by its own CRC and then zeros is still 0, so the loader reads the
stream as a valid, longer image and runs it. This is an exact consequence of
the CRC and not a loader bug; `loadseq.py` and the README say so.

**Finding F8: the count byte is outside the CRC, so "a bad length never reaches
`RUN`" is conditional (PR #210 review; follow-up issue #211).** The frame is
`0xA5`, `N-1`, `2N` payload bytes, CRC. The CRC the loader checks is `PM_CRC`,
which covers the words it committed and nothing else; the count and the magic
are not in it. A corrupted count is therefore caught only because the shorter
(or longer) stream then fails the trailer comparison, and that comparison can
succeed by coincidence. Counterexample, simulated on the RTL of the submitted
top (`verification/test_boot_uart_count_alias.py`, record
`verification/records/boot-uart/` (record 20261010-164351-57c5c8c)): the valid image
`[0xF000, 0x13C1]` is framed `a5 01 f0 00 13 c1 00 00`, and `0x13C1` is the
CRC-16/XMODEM of `f0 00`. Flip bit 0 of the count, `a5 00 f0 00 13 c1 00 00`:
the loader commits `0xF000`, takes `13 c1` as the trailer, the CRC matches,
and the chip **replies `06 13 c1` and leaves the boot ROM (RUN)**, with
program memory word 0 = `0xF000`. The bytes after the trailer (`00 00`) arrive
while the loader is transmitting its reply and are ignored. Observed result:
ACK and RUN, no recovery frame or padding needed.

Scope of the residue. A count flip *down* to k words is accepted only when the
CRC of the first k words equals the next two payload bytes: about 1 in 65,536
for an arbitrary image, certain for a constructed one (this one is
constructed). A flip *up* makes the loader wait for bytes that do not come
(F6). The reply does let the host notice afterwards: the chip answers with the
CRC of what it committed (`13 c1`), which differs from the host's CRC of the
image it sent (`00 00`, the residue of a message followed by its own CRC), but
by then the image is already running, so the reply is a report and not a
guard. (The reply-versus-sent comparison was not simulated as a separate
check.)

Reconciled claims. Issue #139 asked that corrupted payloads, bad lengths and a
bad CRC never reach `RUN`. What is built and measured: payload bit flips, CRC
bytes, and the *tested* bad lengths (too small by one word and by half, 1
word, too large) are never run, and a retry then is. What is **not**
guaranteed: every length corruption. The integrity the protocol gives is
"CRC-16 over the words taken", not "the length is authenticated". The README,
`docs/info.md`, `spec/verification-plan.md` section 7's status line and the
bench README now say so. `test_bad_images_never_run` in `test_boot_uart.py`
is unchanged (its chosen images do not alias, which is why it passes) and the
new module pins the aliasing case rather than hiding it.

No fix is made here. Rejecting this needs a protocol change (a field that
covers the length, or the loader committing the count through `PM_*` so that
`PM_CRC` includes it) and that changes the wire format, `loadseq.py`, the ROM
(which is already over the proposed cap, F4) and every record that hashes
them. That is a decision for this record, not an implementation detail of
#139, so it is deferred to issue #211 with the options listed there. The
cheapest mitigation needing no ROM change is on the host side: `loadseq.py`
can refuse to frame an image for which some prefix's CRC equals the next word.
Nothing in the ratified spec is relaxed.

**Finding F7: what a loaded program is entered with.** The UART load hands
over through the warm start's tail, so a loaded program starts as a warm-started
one does: `R0`-`R3` = 0, `Z` = `C` = 0, `PM_ADDR` = 0, `UIO_DIR` = `UIO_OD` = 0,
`uio_out` = 0, `uo_out` = 0, `BOOT_STATUS` = `0x00`. It differs in `PM_CRC`
(the CRC of the image rather than the residue 0) and in the `PM_DATA`
latches. `BOOT_STATUS` cannot tell a UART-loaded program from a warm-started
one: bit 0 means "a serial load completed" (layer 1) and nothing sets it here.
If a program should know, that is a register-map change and not made.

**Timing, in core cycles (the clock is row 4's unconfirmed one, so no baud
figure here is a measurement).**

- The receiver finds the start edge with a 3-cycle poll, so the edge is
  located to within 3 cycles; the first sample is 650 cycles after the poll's
  `IN` saw it (1.5 bit periods less half the poll), and the next seven are
  exactly 434 cycles apart (`.cyclesec uart_rx_bit`, 434 cycles). It leaves
  the loop in the middle of the stop bit. The longest path from there to the
  next poll is about 30 cycles, so the next start edge, at least half a bit
  (217 cycles) away, is found with a margin of about 190 cycles even from a
  host 2 % fast (which pulls it in by 0.19 bit, 82 cycles).
- The transmitter emits start, data and stop with every edge on a multiple of
  434 cycles from the start edge, measured at the pin; the stop bit is 437
  to 440 cycles, padded so the hand-over's `uo_out` write cannot shorten it.
- *Measured tolerance* (`test_row10_tolerance_edges`, host bit period scaled,
  back to back, whole-percent steps, a 22-word image): the loader accepts a
  host up to **+5 %** slow and **-4 %** fast, against the row-10 bound of
  2 %, and rejects (or ignores) a host 12 % off in either direction, which is
  the bench's negative control. These are measurements of this loader in RTL
  simulation at those steps, not specifications.

**Verification.** `verification/test_boot_uart.py` with the independent host
`verification/uart_boot_host.py` (its own CRC, by table; its own line timing
with fractional bit periods, edge jitter and idle bits; no import from
`firmware/`). It checks: the nominal load and the state the program is
entered with; ±2 % with and without idle bits, jitter, and the unrelated
`ui_in` bits toggling; flipped payload bits, bad CRC bytes, lengths too small
and too large, a wrong magic, each never run (for the images chosen; F8 is the
case they do not cover) and each followed by a retry that is; garbage ahead of the magic; the committed `uart_tx` program loaded over the
UART and graded by the existing `UartDecoder`/`check_frame`; a full 256-word
image (which, being signed, then survives a warm start); strap `11`; and the
fall-through from a failed warm start. The host's frame bytes equal
`loadseq.py`'s for every committed image, and both equal `binascii.crc_hqx`'s
CRC. `verification/boot_uart_mutants.py` injects seven ROM defects, each
caught by a test meant to catch it.
