# firmware/ — programs and the DR 0003 assembler (issue #22)

Protocols live in programs. This tree is where those programs are written,
assembled, and committed as evidence, per
[`spec/decision-records/0003-firmware-toolchain.md`](../spec/decision-records/0003-firmware-toolchain.md)
(the ratified toolchain design) and
[`spec/decision-records/0001-isa.md`](../spec/decision-records/0001-isa.md)
(the ISA the assembler encodes — its opcode table is the authority this
tool cites, never re-derives).

## Layout (DR 0003's fixed shape)

```
firmware/
  asm/            hand-written .asm source, one file per protocol program
    demo_roundtrip.asm   the assembler's round-trip coverage program (the
                         opening issue #22; not a protocol program)
    uart_tx.asm          bit-banged 8N1 UART transmitter (issue #71, the
                         UART third of #23; SPI and I2C are its siblings)
    uart_rx.asm          bit-banged 8N1 UART receiver, 50 cycles/bit
                         (issue #91); uart_rx_115200.asm (434) and
                         uart_rx_9600.asm (5,208) are the same receiver
                         on nested-WAIT bit periods; uart_tx_9600.asm is
                         the nested-WAIT transmitter
    i2c_fast.asm         bit-banged I2C controller, Fast-mode 400 kHz
                         phase budget (issue #73, the I2C third of #23)
    i2c_std.asm          the same controller on the Standard-mode
                         100 kHz phase budget (issue #73)
    spi_mode{0..3}.asm   bit-banged SPI controller, one program per
                         (CPOL, CPHA) mode (issue #72, the SPI third of
                         #23)
    boot/boot_rom.asm    the on-chip boot ROM's program (issues #138 and
                         #139, DR 0013 layer 2: warm start and UART load).
                         Not loaded into program memory: the ROM in
                         rtl/protocol_boot_rom.v is generated from its
                         image. See "The boot ROM" below.
  build/          assembler output (program images + cycle reports) —
                  COMMITTED, not gitignored: a program's image and cycle
                  report are part of the evidence record, byte for byte
    boot/         the boot ROM image and its cycle report
  tools/          the assembler itself
    asm.py        the assembler (Python 3 stdlib only, no dependencies)
    test_asm.py   its unit tests (all 16 opcodes, the DR 0012 control
                  mnemonics + malformed input)
    gen_boot_rom.py       writes rtl/protocol_boot_rom.v from
                          build/boot/boot_rom.hex; `--check` reports drift
    test_gen_boot_rom.py  its unit tests (the 256-word cap, determinism,
                          stale and hand-edited ROMs)
    check_firmware.py     every freshness check in one command
    loadseq.py            host tooling from a .hex: the layer-1 pin sequence
                          (issue #118) and, with --uart, the layer-2 UART boot
                          frame (issue #139)
    test_loadseq.py       its unit tests
    mkflash.py            turns a .hex into the 512-byte signed flash image
                          the SPI-flash boot loads (issue #140);
                          test_mkflash.py tests it
```

## Cold-start invocation (a third party can run this from a fresh clone)

The assembler and its tests need **only Python 3 (>= 3.9) from the stdlib**
— no PDK, no simulator, no `pip install`:

```bash
# Unit tests over the whole instruction set, including malformed input:
python3 firmware/tools/test_asm.py

# Assemble a program (writes firmware/build/<stem>.hex + .cycles.txt):
python3 firmware/tools/asm.py firmware/asm/demo_roundtrip.asm

```bash
# Verify the committed build artifacts still match the committed source
# (what CI runs — catches a stale committed image):
python3 firmware/tools/check_firmware.py
```

`check_firmware.py` is the single invocation shared by CI and local use. It
runs `gen_i2c_sr.py --check` (generated I2C sources vs generator), then
`asm.py <file> --check` on every `firmware/asm/*.asm` it discovers (image
and cycle report), then the boot ROM chain below, keeps going after a
failure, exits 1 if any check failed, and never rewrites an artifact. A
newly committed program is covered automatically. A single program:
`python3 firmware/tools/asm.py <file> --check`. `npm run lint` runs it too.

## The boot ROM (issue #138, DR 0013 layer 2)

With `MODE` low at reset the core fetches from an on-chip ROM, not from
program memory. The ROM's contents are a program in this ISA, and the ROM's
Verilog is generated from that program's committed image:

```
firmware/asm/boot/boot_rom.asm
    asm.py --out-dir firmware/build/boot       (check: asm.py ... --check)
firmware/build/boot/boot_rom.hex  (+ boot_rom.cycles.txt)
    gen_boot_rom.py                            (check: gen_boot_rom.py --check)
rtl/protocol_boot_rom.v
```

```bash
# After editing the boot program:
python3 firmware/tools/asm.py firmware/asm/boot/boot_rom.asm --out-dir firmware/build/boot
python3 firmware/tools/gen_boot_rom.py
```

`check_firmware.py` checks both links, so a ROM that no longer matches the
committed program fails CI at the link that went stale. The generator
refuses an image over **256 words**, the fetch address space. DR 0013
proposed a cap of 128; the UART load does not fit it (finding F4 in that
record), so the cap is the address space until the record decides. The image
is **223** words (the SPI-flash boot 64, the UART load 129, the strap
dispatch and warm start the rest, which includes the two-word zero-signature
refusal of issue #168).

What the program does: its first instruction reads the straps `ui_in[6:5]`.
Strap `10` is the **warm start**: it reads every word of program memory and
commits it back unchanged, which runs all 256 words through `PM_CRC` (the
hardware CRC only sees commits), and executes `WCTL RUN` to address 0 only
if the result is zero, that is, only if word 255 is the CRC-16/XMODEM of
words 0–254. It first restores `R0`–`R3`, `Z` and `C` to their reset
values, so a warm-started program starts in the state a serial-loaded one
does, except that it reads `BOOT_STATUS = 0x00`. One pass of the loop is 9
cycles (`.cyclesec warm_word`), and word 0 of a verified image executes
exactly 2,325 cycles after the boot program's first instruction. Straps
`00` and `11`, and a warm start that fails its check, run the **UART load**
below.

Strap `01` is the **SPI-flash boot** (issue #140, `spi_boot` at the end of
the source, 64 words): it makes CS0, MOSI and SCK (`uio[0]`, `uio[1]`,
`uio[3]`, the Tiny Tapeout QSPI Pmod pinout) outputs, runs one SPI mode 0
transaction (`0x03`, address 0, 512 bytes), commits each word through
`PM_*`, checks `PM_CRC` against the warm start's signature, releases every
pin, and either takes the warm start's hand-over (`run_image`) or halts.
`firmware/tools/mkflash.py` makes a flash image from a committed `.hex`;
[`docs/spi-flash-boot.md`](../docs/spi-flash-boot.md) is the guide to
putting one on the Pmod. Bench: `verification/test_boot_spi.py`
(`verification/request-boot-spi.json`), negative controls
`verification/boot_spi_mutants.py`, evidence in
`verification/records/boot-spi/`. With the UART load the image is 223 words,
which is why the ROM's cap is the 256-word address space (DR 0013 finding F4).

### The UART load (issue #139, DR 0013 layer 2)

Tiny Tapeout "option B", the demo board's USB-UART bridge: RX `ui_in[1]`, TX
`uo_out[0]`. 8N1 at **434 core cycles per bit** (115,200 baud at the 50 MHz
row-4 clock; the cycle count is the claim, the baud figure is arithmetic at
that unconfirmed clock). The frame, built by `firmware/tools/loadseq.py`:

```
0xA5   N-1   2N bytes, high byte of each word first   CRC-16/XMODEM, high byte first
```

N is 1 to 256. The loader writes each word through `PM_DATA_HI` /
`PM_DATA_LO`, compares `PM_CRC` with the trailer, and answers `0x06` + `PM_CRC`
(high byte first) and `RUN 0` on a match, or `0x15` + `PM_CRC` and a wait for
the next `0xA5` on a mismatch. An image whose payload or trailer is
corrupted is never run (CRC-16 over the words the loader took). The count
byte is **not** covered by the CRC: a corrupted count is rejected unless the
CRC of the shorter prefix happens to equal the two bytes that follow it, in
which case the truncated image is accepted and run (DR 0013 finding F8; the
frame `a5 00 f0 00 13 c1 00 00` is the RTL regression). TX idles high from
the loader's start to the `RUN`, and no `uio` pin is ever driven.

```bash
python3 firmware/tools/loadseq.py firmware/build/uart_tx.hex --uart -o uart_tx.frame
# on the PC: stty -F /dev/ttyACM0 115200 cs8 -cstopb -parenb raw; cat uart_tx.frame > /dev/ttyACM0
```

How it is built, because the ISA has no call and four registers:

- one byte receiver (`rx_next`..`rx_bit`) is followed by a dispatch on a
  phase number in `R3` (waiting for `0xA5`, count, payload high byte, payload
  low byte, trailer high, trailer low). The receiver is a loop: the start
  edge is found by a 3-cycle poll of `ui_in[1]` (the other `ui_in` bits are
  masked, not assumed constant), the first sample lands 1.5 bit periods after
  the edge, and the eight samples are exactly 434 cycles apart with no branch
  between them (`.cyclesec uart_rx_bit`). The loop exits at the middle of the
  stop bit, so the handlers run inside half a bit;
- the receiver uses `R0`-`R2`, so the words still to come are kept in
  `UIO_DIR`. That register is safe as storage because with `UIO_OD = 0xFF`
  and `uio_out = 0xFF` the pin-mode rule gives `uio_oe = 0` whatever `UIO_DIR`
  holds. The hand-over writes `UIO_DIR`, then `UIO_OD`, then `uio_out`, back to
  0 in that order, so no cycle drives a pin;
- the reply reuses one transmitter (`tx`) per byte, with the byte counter in
  `PM_ADDR` and the verdict in `UIO_DIR`; the stop bit is padded a few cycles
  past 434 so the hand-over cannot shorten it;
- on a match it jumps to the warm start's tail (`handover:`), so a UART-loaded
  program starts in the same state a warm-started one does (`R0`-`R3` = 0,
  `Z` = `C` = 0, `PM_ADDR` = 0, `UIO_*` = 0, `uo_out` = 0, `BOOT_STATUS` =
  0x00), except that `PM_CRC` holds the CRC of the image.

If the host loses sync (a wrong length, a lost byte) the loader reads the
stray bytes as a new frame whenever one of them is `0xA5`, and waits for the
rest. There is no timeout. Recover by pulsing `rst_n`, or by sending non-zero
filler until the loader answers `0x15` (zero filler does not work: a message
followed by its own CRC and then zeros still has CRC 0, so the loader reads it
as a valid longer image). Auto-baud was not attempted.

The assembler reports data-dependent-branch warnings for this program (12),
all intended: the two strap branches, the warm start's zero-signature and CRC
verdicts, and in
the UART load the start-edge poll, the phase dispatch, the handlers and the
verdicts. None paces a pin: the samples and the transmitted bits are paced by
`WAIT` literals and a counter that never holds pin data.

Zero signatures are refused (DR 0013 Finding F1, closed by issue #168): 256
zero words carry their own valid signature (the CRC starts at 0), so the
warm start refuses word 255 = `0x0000` before its CRC verdict, as the
SPI-flash boot does. Two words: the loop's last pass leaves word 255 in
`R0`/`R1`. An image whose real CRC is `0x0000` (1 in 65,536) must be
re-padded; `firmware/tools/mkflash.py` refuses to build one.

Bench: `verification/test_boot_rom.py`
(`verification/request-boot-rom.json`), negative controls
`verification/boot_rom_mutants.py`, evidence in
`verification/records/boot-rom/`. The UART load has its own bench,
`verification/test_boot_uart.py` (`verification/request-boot-uart.json`),
driven by the independent host model `verification/uart_boot_host.py`;
evidence in `verification/records/boot-uart/`.

## Programs

### `uart_tx.asm` — bit-banged 8N1 UART transmitter (issue #71)

The UART third of issue #23's three-protocol batch, implementing DR 0001's
"Per-protocol cycle-budget sketch → UART (bit-banged, 8N1)" inner loop
(`MOV`/`AND`/`OUT`/`SHF`/`WAIT`) on `UO_OUT` bit 0, line idling high. It
transmits two frames, `0x5A` then `0xA5`, so both stop-bit adjacencies (a
last data bit of 0 and of 1) are exercised.

**Bit period: exactly 50 core cycles**, measured at the pin by
`verification/test_firmware_uart.py` and recorded in
`verification/records/firmware-uart/`. That cycle count is the claim; the
"1 µs / 1,000,000 baud" reading of it is arithmetic at target-spec row 4's
**unconfirmed** 50 MHz core clock (row 4 is unconfirmed on both flows and
STA against this core is blocked — `verification/records/sta-corner-sweep/`),
so no wall-clock baud figure here is a measurement.

Cycle accounting (DR 0001's opcode table: 1 cycle per instruction, `WAIT
imm8` = imm8 + 1):

| Interval | Instructions | Cycles |
|---|---|---|
| per data bit (the `.cyclesec uart_bit_frame*` sections) | `MOV`+`AND`+`OUT`+`SHF`+`SUB`+`WAIT 43`+`BNZ` | 1+1+1+1+1+44+1 = **50** |
| START → first data bit | `OUT`+`WAIT 46`+`MOV`+`AND` | 1+47+1+1 = **50** |
| last data bit → STOP | `OUT`+`SHF`+`SUB`+`WAIT 43`+`BNZ`+`WAIT 1` | 1+1+1+44+1+2 = **50** |

DR 0001's sketch quotes `WAIT 45` for the same 50-cycle period; that is
the *unrolled* per-bit form (a 4-instruction body plus 46 padding cycles).
This program uses DR 0001's own blessed compile-time-constant-trip-count
loop instead, so two of those 46 padding cycles go to `SUB`+`BNZ` and the
immediate is 43. Same 50-cycle total — the sketch's arithmetic holds, and
the evidence record says so explicitly rather than leaving the discrepancy
in the immediate unexplained.

Run its DUT-facing bench with:

```bash
klt functional-verification verification/request-firmware-uart.json --format json
```

### `uart_rx*.asm` / `uart_tx_9600.asm` — UART receive and low-baud (issue #91)

`uart_tx.asm` covered one direction at one rate. These close the rest of
target-spec row 1's UART line (9,600-1,000,000 baud, both directions) in
firmware, with no UART hardware:

| Program | Cycles/bit | Words | Notes |
|---|---|---|---|
| `uart_rx.asm` | 50 | 132 | one `WAIT` per bit |
| `uart_rx_115200.asm` | 434 | 168 | nested `WAIT`, 1 outer pass |
| `uart_rx_9600.asm` | 5,208 | 168 | nested `WAIT`, 20 outer passes |
| `uart_tx_9600.asm` | 5,208 | 177 | nested `WAIT` transmitter |

All fit DR 0001's 256-word program store. Baud figures are arithmetic at
the unconfirmed 50 MHz clock (5,208 cycles x 20 ns = ~9,600 baud); the
claim is the cycle count. A bit period above one `WAIT` (256 cycles) uses a
compile-time-constant outer loop, `LDI n; WAIT 255; SUB; BNZ` = 258 cycles
per pass plus a remainder `WAIT`; the bit blocks are unrolled because the
loop needs the fourth register.

**Receiver shape.** RX = `UI_IN` bit 1 (idle high; DR 0010's option B, issue #178). A 3-cycle poll
(`IN`/`AND`/`BNZ`) finds the start edge; the first sample lands at the
centre of data bit 0 (1.5 bit periods after the edge, within the poll's
3-cycle granularity); later samples are exactly one period apart with no
branch between them. The byte is assembled by shifting and emitted on
`UO_OUT`; `UIO_OUT` bit 1 is a sample mark (the bench reads the real
sample instants off it) and bit 2 a framing-error flag (stop bit read 0).
`R1` holds the RX mask (2), so it is also the mark value and the delay-loop
decrement (outer counts are doubled) and each sample uses six `SHF LEFT` and
a `NOP`: word and cycle counts are unchanged.
The assembler's data-dependent-latency lint reports exactly three warnings
per receiver: the two start-edge handshakes and the post-stop re-arm.

Bench: `verification/test_firmware_uart_rx.py`
(`verification/request-firmware-uart-rx.json`), evidence in
`verification/records/firmware-uart-rx/`.

```bash
klt functional-verification verification/request-firmware-uart-rx.json --format json
```

### `i2c_fast.asm` / `i2c_std.asm` — bit-banged I2C controller, both speed grades (issue #73)

The I2C third of issue #23's batch, implementing DR 0001's "Per-protocol
cycle-budget sketch → I2C". `i2c_fast.asm` paces the Fast-mode budget
(low = 65, high = 60 core cycles per SCL clock — the 125-cycle / 400 kHz
period of the sketch, with t_LOW exactly at UM10204 Table 10's 1.3 µs
floor); `i2c_std.asm` is the same instruction stream on the
Standard-mode budget (low = 258, high = 242 — a 500-cycle clock, i.e. no
faster than the 100 kHz Standard-mode ceiling at the unconfirmed nominal
50 MHz clock; both phases clear UM10204 Table 10's t_LOW / t_HIGH minima of
235 / 200 cycles). Until issue #125 this was low = 235, high = 200 (both
floors to the cycle, 435 cycles, ~114.9 kHz at the nominal clock), which met
every phase minimum but ran *faster* than the 100 kHz Standard-mode maximum;
that was a non-compliance, not a "maximum" the bus was allowed to reach, and
the 500-cycle clock supersedes it. The 65 extra cycles cost no instruction
words: 258 is as long as a single `WAIT 255` reaches in the data-clock low
phase, and the rest goes to the high phase's existing `WAIT`. Each program performs one write
transfer: START, address 0xA0 (0x50 << 1 | W), ACK slot, data byte 0x5A,
ACK slot, STOP.

**Pin plan** (DR 0010's target plan, the standard Tiny Tapeout I2C Pmod,
upper row; issue #155): SCL = `UIO_OUT` bit 2, SDA = `UIO_OUT` bit 3,
open-drain convention (1 = released, 0 = asserted).
Each I2C program makes that convention real on the pins with one
instruction in its setup, `WCTL UIO_OD, R3` with `R3 = 0x0C` (DR 0012:
SCL and SDA become open-drain, `uio_oe[n] = ~uio_out[n]`). It comes
**after** the `OUT UIO_OUT` of `0x0C`, because `uio_out` resets to 0 and
enabling open-drain first would pull both lines low for a cycle. It sits in
the idle setup, outside every `.cyclesec`, so no phase length changed.
The 0x08 mask register does double duty — bit extraction and the
ACK-slot "SDA released" pin value — because SDA sits on bit 3. The data
bit is R0's MSB, so each extraction first shifts a copy right four times
(`SHF R3, RIGHT` x 4, paid for out of the same high phase's `WAIT`, so
no phase length changed). Until issue #155 SDA was bit 7 and needed no
shift; the move costs 64 words (182 -> 246 of 256) and nothing in timing.

**The ACK handshake is the one sanctioned data-dependent branch.** The
address ACK slot samples SDA with `IN` + `AND` and branches `BNZ` on it:
a NACK skips the data byte and goes straight to STOP. DR 0001 names
exactly this branch as legitimate (a protocol handshake, not a timing
budget), and each program therefore carries exactly one assembler
*warning* — asserted by the bench, not silenced. Timing phases
themselves never branch on pin data: every phase is straight-line code
with assemble-time `WAIT` literals.

**The eight clocks per byte are unrolled, not looped.** DR 0001's
blessed constant-trip-count loop needs five live values (byte, mask,
SCL constant, temp, loop counter) and the ISA has four registers — so
each byte is 65 instructions of straight-line phases (97 since issue
#155's SDA-alignment shifts), and a whole program is 246 words. That fits DR 0001's 256-word memory for one
protocol with headroom, but it challenges the sketch's "all three core
protocols coexist with room for a dispatch table" sizing narrative —
recorded as an ISA finding in the evidence record, not a spec change.

Cycle accounting per phase (DR 0001's opcode table; `.cyclesec` sections
state each phase's exact length — the bench cross-checks all 41):

| Phase (Fast / Standard) | Instructions | Cycles |
|---|---|---|
| data-clock low | `OUT`+`WAIT 62`/`255`+`OR` | **65 / 258** |
| data-clock high | `OUT`+`SHF`+`WAIT 51`/`233`+`MOV`+4x`SHF`+`AND` | **60 / 242** |
| ACK low (incl. the `IN` sample) | `OUT`+`WAIT`+`IN`+`WAIT`+`AND`+`LDI` | **65 / 258** |
| START hold (t_HD;STA) | `OUT`+`WAIT`+`LDI`+`MOV`+4x`SHF`+`AND` | **65 / 205** |
| STOP setup (t_SU;STO) | `OUT`+`WAIT`+`LDI` | **60 / 205** |

Every data/ACK clock is low + high = **125 / 500** cycles, fall to fall;
the reference model bounds each clock's complete period by UM10204 Table
10's f_SCL maximum (2500 ns Fast, 10000 ns Standard at the nominal 20 ns
clock), independently of the t_LOW / t_HIGH minima (issue #125).

The measured quantities are those **cycle counts**; the 400 kHz / 100
kHz names are arithmetic at target-spec row 4's unconfirmed clock (same
stance as `uart_tx.asm`).

**Open-drain, and what the bench does about it.** The programs' first
instructions release both lines (`OUT` of `0x0C`) and then write `0x0C`
to DR 0012's `UIO_OD` control register, so SCL (`uio[2]`) and SDA
(`uio[3]`) are open-drain pads: `uio_oe[n] = ~uio_out[n]`. The
DUT-facing benches run on a pad model (`verification/uio_pads.py`, issue
#136) that resolves each line from the design's `uio_oe` / `uio_out`, a
pull-up, and the peripheral as an external open-drain driver, and feeds
the line back on `uio_in`. The independent reference model grades those
lines, the ACK flows through the core's real `IN` path, and the benches'
negative control runs each image with `UIO_OD` left at reset: no pad is
enabled, the lines never move, and the model finds no transfer. (Before
#136 the benches composed `uio_out AND uio_in` themselves and never read
`uio_oe`; before DR 0012 the top had `uio_oe = 8'h00` and could not pull
a line low at all.) The pad model is zero-delay and logical: it is not
evidence about pull-up rise time, pad delay or drive strength, and an
I2C bus still needs external pull-ups, which this design does not
provide.
### `spi_mode{0..3}.asm` — bit-banged SPI controller, all four modes (issue #72)

The SPI third of issue #23's three-protocol batch: four programs, one per
(CPOL, CPHA) combination, implementing DR 0001's "SPI (controller, mode 0,
SCLK ≤ f_clk/4)" cycle-budget sketch extended to modes 1–3 (the sketch
itself covers mode 0 only; the mode variants are this issue's own design
work, with `verification/reference_models/spi.py`'s `SpiMode` semantics —
not the sketch — as the authority on which edge samples per mode).

**Pin map** (DR 0010's target plan, the standard Tiny Tapeout SPI Pmod,
upper row; issue #155). Each program writes its idle image to `UIO_OUT`
and then `0x0B` to DR 0012's `UIO_DIR`, which makes CS, MOSI and SCLK
push-pull outputs; MISO stays an input. Until #155 CS/SCLK/MOSI were on
`uo_out[0..2]` and MISO on `uio_in[0]`.

| Pin | uio bit | Role |
|---|---|---|
| CS | `uio[0]` | active low, push-pull (`UIO_DIR`) |
| MOSI | `uio[1]` | controller-driven, push-pull |
| MISO | `uio[2]` | peripheral-driven, sampled by `IN` |
| SCLK (Pmod SCK) | `uio[3]` | idles at CPOL, push-pull |

**Two bursts per program, both full-duplex** (an `IN` samples MISO every
bit in both), both graded by the independent model in
`verification/test_firmware_spi.py`:

1. **Ceiling burst** — exactly **4 core cycles per SCLK period**
   (SCLK = f_clk/4, DR 0001's ceiling; 2-cycle half-periods, zero `WAIT`),
   32 instructions for 8 bits (`.cyclesec spi_mode*_ceil`, straight-line,
   no branches). The write on the mode's sampling edge carries the data
   bit; the other phase's write is a static register image (MOSI low
   there) — the model samples only on the mode-correct edges, so the
   sampled value is the data bit with a half-period of setup.
2. **Functional burst** — 10 cycles/bit (under the ceiling;
   `.cyclesec spi_mode*_func`, 80 cycles), the same full-duplex shape plus
   MISO extraction and assembly (`IN`+`AND`+2x`SHF`+`SHF`+`OR` per bit —
   the extraction cannot fit the 4-cycle budget), after which the
   assembled byte is echoed on `uo_out[7:0]` once CS releases. MISO on
   `uio[2]` needs two right shifts per bit to reach bit 0; on `uio[0]`
   (before issue #155) it needed none and the burst ran at 8 cycles/bit.

**Measured at the pin** (record
`verification/records/firmware-spi/`): SCLK period exactly 4 cycles
(80.000 ns at the bench's nominal-only 20 ns clock) on the ceiling burst
in all four modes, both data streams decoded byte-exact by the
independent `check_burst` in all four modes, and the echoed assembled RX
byte matching the peripheral's byte in all four modes. As with UART, the
cycle counts are the claim; any MHz figure is arithmetic at
target-spec row 4's **unconfirmed** clock.

**ISA finding** (recorded as a dated note in the evidence record, per
#72's acceptance criterion 5): DR 0001's 4-cycle sketch budget **holds** —
4 cycles/bit with the MISO sample (`IN`) inside the loop — but its literal
instruction sketch does not: the sketch's one `SHF` ("shift in sampled
bit, shift out next TX bit") presumes a shift the ISA does not have (the
real `SHF` shifts one register, fills with 0, and there is no immediate
ALU form), so the data-bearing phase write is built from per-bit `LDI`
immediates instead. RX **assembly** costs a further 4 ops/bit and does
not fit at 4 cycles/bit — hence the 8-cycle functional burst.

Run the DUT-facing bench with:

```bash
klt functional-verification verification/request-firmware-i2c.json --format json
```

Its result is committed as an append-only evidence record under
`verification/records/firmware-i2c/`.

### `i2c_{fast,std}_sr[_poll].asm` — write, repeated START, read, clock stretch (issue #92)

Four programs generated by `firmware/tools/gen_i2c_sr.py` (one instruction
stream; only phase literals and the poll differ), each a complete
START, `0xA0` + ACK, `0x5A` + ACK, **repeated START**, `0xA1` + ACK, **one
byte read from the peripheral, controller NACK**, STOP; the received byte
is published on `UO_OUT`. t_SU;STA is paced exactly at the Table 10
minimum (30 cycles Fast, 235 Standard). Standard data/ACK clocks are 500
cycles (low 258 + high 242; polled rise phases +2), Fast 125 (issue #125). The bit loops keep a counter, so
the programs are 152 words (`_sr`) and 192 words (`_sr_poll`) of the
256-word store, against 246 words for the unrolled write-only programs
(131 / 171 / 181 before issue #155's SDA-alignment shifts; SCL is
`uio[2]`, SDA `uio[3]`, `UIO_OD` = `0x0C`).
`_sr` has no pin-dependent branch; `_sr_poll` polls the peripheral's SCL
after every rise (10 `BZ` sites, each a sanctioned handshake warning) and
loops while it is held low. Determinism claims exclude the interval spent
in a poll loop. Bench: `verification/test_firmware_i2c_sr.py`
(`klt functional-verification verification/request-firmware-i2c-sr.json
--format json`); record under `verification/records/firmware-i2c/`.
klt functional-verification verification/request-firmware-spi.json --format json
```


The cocotb round-trip bench — assembling `demo_roundtrip.asm`, loading the
image serially through `rtl/protocol_program_memory.v`'s DR 0001 load
phase, and reading every word back through the fetch port — additionally
needs the pinned toolchain the rest of this repo's verification uses
(`klt` at the `layout/toolchain.json` pin plus Icarus; both provisioned by
`./scripts/setup-env.sh` — see
[`verification/README.md`](../verification/README.md)):

```bash
klt functional-verification verification/request-firmware-roundtrip.json --format json
```

Its result is committed as an append-only evidence record under
`verification/records/firmware-assembler-roundtrip/`.

## Source syntax

One instruction per line. `;` starts a comment. `label:` defines a label
(resolved to absolute 8-bit addresses per DR 0001's `JMP`/`BZ`/`BNZ`).
Mnemonics, registers (`R0`–`R3`), ports (`UI_IN`, `UIO_IN`, `UO_OUT`,
`UIO_OUT`), and shift directions (`LEFT`/`RIGHT`) are case-insensitive;
labels are case-sensitive. Immediates are decimal or `0x`-hex, `0..255`.

Directives: `.cyclesec <name>` … `.endcyclesec` brackets a
protocol-timing-critical section; the assembler computes its exact
entry→exit cycle count statically (DR 0001's no-data-dependent-latency
guarantee makes that a property of the instruction stream alone) and
records it in the cycle report. A section containing branches is flagged
`branches=true` — the straight-line count is still exact, but a loop's
trip count is the program's business, not the assembler's.

**Control space (DR 0012).** `WCTL <reg>, Rs` writes a control register
and `RCTL Rd, <reg>` reads one. They are not new opcodes: `WCTL` is `OUT`
to port `00` and `RCTL` is `IN` from port `10`, with the register index in
`imm8`. `<reg>` is a name — `UIO_DIR`, `UIO_OD`, `PM_ADDR`, `PM_DATA_HI`,
`PM_DATA_LO`, `RUN`, `PM_CRC_LO`, `PM_CRC_HI`, `BOOT_STATUS`, `HW_ID` — or a
number. The cycle report costs them per DR 0012's table: 1 cycle, except
`WCTL PM_DATA_LO`, `WCTL RUN` and `RCTL PM_DATA_HI`, which are a fixed 2. An
index the record does not assign in that direction (an unassigned number,
a write to `BOOT_STATUS`/`HW_ID`, a read of `RUN`) is an error unless the
assembler is run with `--allow-reserved`. `OUT` to port `01` and `IN` from
port `11` stay errors either way, and `OUT UI_IN` / `IN UO_OUT` are errors
that point at `WCTL` / `RCTL`.

The assembler rejects, as errors with line numbers: unknown mnemonics,
wrong operand arity, registers outside `R0`–`R3`, immediates outside
`0..255`, bad ports/directions, `IN` from a write-only port or `OUT` to a
read-only port (DR 0001 defines those as hardware no-ops and makes
flagging them the assembler's job), undefined or duplicate labels,
programs exceeding DR 0001's 256-word program memory, and malformed
`.cyclesec` usage.

It warns (never errors) on the data-dependent-latency hazard DR 0001's
timing model names: a conditional branch whose governing flags were last
set by an instruction over `IN`-sampled (pin-derived) data — legitimate
for a protocol handshake (an I2C ACK wait), a hazard if that loop produces
protocol timing.

Taint enters at `IN` and follows the data through `MOV` and the ALU ops;
`LDI` clears it. It also survives a trip through the control space:
`WCTL` then `RCTL` is a `MOV` with extra steps, so the lint tracks what
each piece of writable control state holds, by what `rtl/protocol_core.v`
does on each access.

| `RCTL` of | Reads tainted when |
|---|---|
| `UIO_DIR`, `UIO_OD`, `PM_ADDR` | the last `WCTL` to that index wrote a tainted register. A `WCTL` of an untainted register clears it. (`PM_DATA_LO`'s post-increment of `PM_ADDR` changes nothing.) |
| `PM_DATA_HI`, `PM_DATA_LO` | always. These return a program-memory word (`PM_DATA_HI` reads `PM[PM_ADDR]` and latches its low byte for `PM_DATA_LO`), not the `WCTL PM_DATA_HI` latch, and the assembler cannot establish what a memory word holds: it depends on every commit ever made to it. |
| `PM_CRC_LO`, `PM_CRC_HI` | a tainted word has been committed since the last clear: a `WCTL PM_DATA_LO` of a tainted register, or one following a tainted `WCTL PM_DATA_HI`. A later constant commit does not clean the sum. Any `WCTL` to either CRC index clears it, whatever the register holds. A tainted `PM_ADDR` does not taint it (the CRC covers data, not addresses). |
| `BOOT_STATUS`, `HW_ID` | never: a load-time status bit and a build-time constant. |

The scan is linear, so stored control state is known only along
straight-line code from reset, where every control register and the CRC
are cleared. Where control can arrive from somewhere else the stored
state is **unknown and reads as tainted** until the program rewrites it
(or clears the CRC): at every label and numeric branch target, after a
`JMP`, `HALT` or `WCTL RUN`, and everywhere in a program that contains a
`WCTL RUN`, since a computed jump can land on any address. `BOOT_STATUS`
and `HW_ID` stay clean in all of those.

## Build artifacts

For `foo.asm`, `firmware/build/` carries:

- `foo.hex` — the program image, one 4-hex-digit 16-bit word per line
  (`$readmemh`-compatible), loaded MSB-first by the serial load phase.
- `foo.cycles.txt` — the cycle-accounting report: `WORDS` / `TOTAL-CYCLES`
  / one `CYCLES name=… start=… end=… cycles=…` line per `.cyclesec`,
  `WARNING` lines, and a per-instruction `ADDR … WORD … cycles=…` listing.

Both are deterministic (no timestamps, canonical repo-relative source
path) so `--check` and CI byte-compare them. A change to a program or the
assembler that changes its cycle behavior is a **new committed artifact**,
not an in-place edit that silently invalidates a prior recorded pass.

Until the ISA core lands (issue #18), "a program assembled by it executes
correctly in the cocotb bench" means the program-memory path: the image
loads through the DR 0001 serial load phase and reads back exactly through
the fetch port the core will execute from — the same out-of-band stance as
`verification/test_program_memory.py`, because DR 0001 defines no readback
instruction and the 16-opcode table is exactly full.
