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
                         the nested-WAIT transmitter, and
                         uart_tx_115200.asm (434, issue #281) the same
                         transmitter at the 115,200-class period
    midi_tx.asm          MIDI DIN note-on, control-change and note-off demo
    midi_rx.asm          MIDI DIN monitor with receive running status
    i2c_fast.asm         bit-banged I2C controller, Fast-mode 400 kHz
                         phase budget (issue #73, the I2C third of #23)
    i2c_std.asm          the same controller on the Standard-mode
                         100 kHz phase budget (issue #73)
    spi_mode{0..3}.asm   bit-banged SPI controller, one program per
                         (CPOL, CPHA) mode (issue #72, the SPI third of
                         #23)
    ws2812.asm           WS2812 LED-strip controller on uo_out[7]: N
                         GRB pixels from a table in program memory, 63
                         cycles per bit, refreshed with a >280 us reset
                         (target-spec row 13, issue #141; protocol chosen
                         by DR 0018 after DR 0017's ISA freeze)
    ps2_device.asm       PS/2 keyboard/mouse DEVICE on uio[2] (CLK) and
                         uio[3] (DATA), both open-drain: generates the clock
                         the host may inhibit, receives host bytes with an
                         ACK, echoes them (0xFE on a parity or stop error)
                         (target-spec row 13 stretch column, issue #235;
                         protocol chosen by the dated note in DR 0018 after
                         DR 0017's ISA freeze)
    dmx512_tx.asm        DMX512 (USITT DMX512-A) universe transmitter on
                         uo_out[0] through an external RS-485 transceiver:
                         BREAK, mark-after-break, 0x00 start code, 512
                         channel slots at 200 cycles/bit 8N2, forever
                         (multi-protocol extra credit, issue #445; catalog
                         #443; firmware on the frozen DR 0017 ISA)
    i2s_tx.asm           I2S (Philips) controller / transmitter: 16-bit
                         stereo, 32-BCLK slots, BCLK uo_out[6], WS
                         uo_out[5], SD uo_out[7]; streams a 16-frame
                         sine table from program memory forever
                         (multi-protocol extra credit, issue #451; catalog
                         #443; firmware on the frozen DR 0017 ISA)
    nec_ir.asm           NEC infrared remote TRANSMITTER on uo_out[7]:
                         38 kHz-class carrier (1,316 cycles/period, 439
                         high) gated into a 9-ms-class leader, 32
                         pulse-distance bits from a one-word-per-bit table
                         in program memory, final mark, 60 ms idle, forever
                         (multi-protocol extra credit, issue #448; catalog
                         #443; firmware on the frozen DR 0017 ISA)
    swd_probe.asm        SWD debug PROBE (host) on uio[2] (SWCLK) and
                         uio[3] (SWDIO), push-pull with SWDIO released at
                         each turnaround: line reset, 0xE79E JTAG-to-SWD
                         switch, then five transactions -- DP IDCODE read,
                         DP SELECT write, AP TAR write, the posted AP DRW
                         read and the DP RDBUFF read that returns the
                         addressed memory word -- sent from a stored table
                         by one shared loop; ACK/data/parity samples are
                         reported on uo_out (multi-protocol extra credit,
                         issues #452 and #500; protocol chosen by the dated
                         note in DR 0018 after DR 0017's ISA freeze)
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
```

```bash
# Verify the committed build artifacts still match the committed source
# (what CI runs — catches a stale committed image):
python3 firmware/tools/check_firmware.py
```

`check_firmware.py` is the single invocation shared by CI and local use. It
runs `gen_i2c_sr.py --check`, `gen_spi_modes.py --check` and
`gen_uart_nested.py --check` (generated I2C, SPI and nested-WAIT UART sources
vs their generators), then
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
is **232** words (the SPI-flash boot 64, the UART load 138, the strap
dispatch and warm start the rest, which includes the two-word zero-signature
refusal of issue #168); 24 of the 256 are free. The UART load was 129 words
until issue #211 added the count-complement check (+9: a seventh phase in the
dispatch, 2, and its handler, 7).

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
`verification/records/boot-spi/`. With the UART load the image is 232 words,
which is why the ROM's cap is the 256-word address space (DR 0013 finding F4).

### The UART load (issue #139, DR 0013 layer 2)

Tiny Tapeout "option B", the demo board's USB-UART bridge: RX `ui_in[1]`, TX
`uo_out[0]`. 8N1 at **434 core cycles per bit** (115,200 baud at the 50 MHz
row-4 clock; the cycle count is the claim, the baud figure is arithmetic at
that unconfirmed clock). The frame, built by `firmware/tools/loadseq.py`:

```
0xA5   N-1   ~(N-1)   2N bytes, high byte of each word first   CRC-16/XMODEM, high byte first
```

N is 1 to 256. The third byte is the count's ones' complement (issue #211,
DR 0013 finding F8 resolved). The loader checks it before it commits any word;
a count and complement that do not match are answered `0x15 00 00` at once
(nothing committed) and the loader goes back to waiting for `0xA5`. Otherwise
it writes each word through `PM_DATA_HI` / `PM_DATA_LO`, compares `PM_CRC`
with the trailer, and answers `0x06` + `PM_CRC` (high byte first) and `RUN 0`
on a match, or `0x15` + `PM_CRC` and a wait for the next `0xA5` on a
mismatch. An image whose payload or trailer is corrupted is never run
(CRC-16 over the words the loader took), and any corruption of the count
byte alone, or of the complement alone, is rejected before a word is written
(the old F8 counterexample, `a5 00 fe f0 00 13 c1 00 00` in the new frame,
is the RTL regression). What is still not guaranteed: a corruption that
changes the count and its complement consistently (two or more bit errors,
placed to match) and also makes the shorter or longer stream's CRC match.
TX idles high from the loader's start to the `RUN`, and no `uio` pin is ever
driven.

```bash
python3 firmware/tools/loadseq.py firmware/build/uart_tx.hex --uart -o uart_tx.frame
# on the PC: stty -F /dev/ttyACM0 115200 cs8 -cstopb -parenb raw; cat uart_tx.frame > /dev/ttyACM0
```

How it is built, because the ISA has no call and four registers:

- one byte receiver (`rx_next`..`rx_bit`) is followed by a dispatch on a
  phase number in `R3` (waiting for `0xA5`, count, count complement, payload
  high byte, payload low byte, trailer high, trailer low). The receiver is a loop: the start
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
rest; since issue #211 the two bytes after a stray `0xA5` must also be a
count and its complement, so most false starts are answered `0x15 00 00`
after two bytes instead. There is no timeout. Recover by pulsing `rst_n`, or by sending non-zero
filler until the loader answers `0x15` (zero filler does not work: a message
followed by its own CRC and then zeros still has CRC 0, so the loader reads it
as a valid longer image). Auto-baud was not attempted.

The assembler reports data-dependent-branch warnings for this program (13),
all intended: the two strap branches, the warm start's zero-signature and CRC
verdicts, and in
the UART load the start-edge poll, the phase dispatch, the handlers and the
verdicts (the count-complement check of issue #211 is the thirteenth). None paces a pin: the samples and the transmitted bits are paced by
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
| `uart_tx_115200.asm` | 434 | 177 | nested `WAIT` transmitter, 1 outer pass (issue #281) |

The four nested-`WAIT` programs above are written by
`firmware/tools/gen_uart_nested.py` (`--check` guards drift); the committed
`.asm` stays the evidence.

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

**`uart_tx_115200.asm` (issue #281).** The transmitter side of the
115,200-class point (434 core cycles per bit), firmware only: the same
shape as `uart_tx_9600.asm` with one outer pass (`LDI 1; WAIT 255; SUB;
BNZ` = 259 cycles with the `LDI`) plus a remainder `WAIT` of 170 for a data
bit (171 after the start bit, 173 before the stop bit), so 434 is hit
exactly and the 256-word store is not stressed (177 words). Graded by
`test_uart_tx_115200_class`: `UartDecoder` recovers both frames, every TX
edge gap is a whole multiple of 434 cycles, and a 1.025x re-timed capture
must fail `check_frame`. A core-cycle count; no baud is claimed (434 x 20 ns
is ~115,200 baud only at row 4's unconfirmed 50 MHz).

Bench: `verification/test_firmware_uart_rx.py`
(`verification/request-firmware-uart-rx.json`), evidence in
`verification/records/firmware-uart-rx/`.

```bash
klt functional-verification verification/request-firmware-uart-rx.json --format json
```

### MIDI 1.0 DIN

Load `midi_tx.hex` (**108 words**) to send middle C on MIDI channel 3,
set modulation, then release the note. The nine bytes on the wire are
`92 3C 55  B2 01 40  82 3C 00`. The image sends them once and leaves TX
high. The transmitter reads the nine byte literals in program memory through
`PM_DATA_HI/LO` and shares one 8N1 output routine across all three messages.

Load `midi_rx.hex` (**218 words**) to monitor note-on, note-off and
control-change on all 16 channels. After the second data byte passes its stop
check, sample `uo_out[7:0]` on successive core clocks for the status (channel
included), first data byte, and second data byte. The bus idles at `FF` on
either side, including between messages with identical data bytes. A note-on
with zero velocity retains its received encoding and means release. Running
status stays in R3. The receiver uses the address register `PM_ADDR` to save
the first data byte between frames, with `FF` marking an empty slot.

A new channel status discards a partial message. Unsupported channel or system
common status cancels running status. Real-time bytes can pass between data
bytes without disturbing the parser. A bad stop makes the receiver wait for
idle high and a fresh status. Stray data produces no output.

| Interval | Core clocks | At 50 MHz |
|---|---:|---:|
| TX start bit, each LSB-first data bit, stop bit | 1,600 each | 32 µs (31.25 kbaud) |
| TX start to next start (8N1, contiguous bytes) | 16,000 | 320 µs |
| Explicit status and two data bytes on the wire | 48,000 | 960 µs |
| RX start edge to first data sample | about 2,400 (3-clock polling loop) | about 48 µs |
| RX data sample to next data or stop sample | 1,600 | 32 µs |
| RX result, per byte | 1 | 20 ns |

The time and baud columns assume target-spec row 4's **unconfirmed 50 MHz
clock**. For example, a TX data-to-data interval is one shift, one counter
load, six 258-clock passes, a 47-clock remainder, and three instructions to
mask and drive the next bit. The bench measures TX edges and RX sample marks
against 1,600 ±16 clocks and drives consecutive RX frames at both tolerance
limits.

**DIN interface wiring.** One 3.3 V interface is the Adafruit MIDI
FeatherWing (#4740), jumpered to the demo board's dedicated Pmod headers.
Its H11L1 optocoupler isolates MIDI IN. MIDI OUT uses 33 Ω from 3.3 V to DIN
pin 4 and 10 Ω from the TX driver to DIN pin 5. [Interface schematic](https://github.com/adafruit/Adafruit-MIDI-FeatherWing-PCB/blob/d060360d31ba77963443121e71bae136c882a788/Adafruit%20MIDI%20FeatherWing.sch)

| Image | Demo-board Pmod signal | FeatherWing header | DIN cable |
|---|---|---|---|
| TX | Dedicated output `uo_out[0]` | `TX` | MIDI OUT to instrument IN |
| RX | Dedicated input `ui_in[1]` | `RX` (opto output) | Instrument OUT to MIDI IN |
| Either | 3.3 V and GND | `3V` and `GND` | Logic-side power |

Connect the signal for the loaded image. For RX, release the demo-board MCU's
driver on `ui_in[1]` so the optocoupler can drive it. For TX, load the image
before connecting the instrument since the output header carries the CRC
readout during serial loading. The cocotb test covers the digital pins. The
external current loop has not been tested on hardware.

```sh
klt functional-verification verification/request-firmware-midi.json --format json
python3 verification/midi_mutants.py
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
235 / 200 cycles). The pair is generated from one template by
`firmware/tools/gen_i2c_pair.py` (issue #374; per-mode WAIT literals and
annotation blocks only), and `test_asm.py` (run by CI) fails on drift via
`gen_i2c_pair.py --check` (not `check_firmware.py` or `ci.yml`, which are
hashed inputs of recorded evidence and signoff manifests). Until issue #125 this was low = 235, high = 200 (both
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
SCL and SDA become open-drain, `uio_oe[n] = ~uio_out[n]`, where `uio_out`
is the port-11 register; the pad data of an open-drain pin is tied to 0,
DR 0020). It comes
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

**Where the ACK is sampled (issue #258).** Both ACK slots are sampled in
the middle of the ninth SCL **high** phase — the `IN` is 30 cycles after
the rise and 30 before the fall on Fast, 121 / 121 on Standard — where
UM10204 requires SDA to be stable. The ACK low phases carry no sample: a
peripheral may answer anywhere in them, up to t_SU;DAT before the rise.
Until #258 the `IN` sat in the ACK *low* phase, 22 (Fast) / 32
(Standard) cycles after the SCL fall, so a legal but late ACK was read as
a NACK (the address branch then sent STOP instead of the data byte); the
benches' peripheral answered one cycle after the fall and never showed
it. The address `BNZ` keeps its place in the high phase, so both branch
paths keep the ninth high at exactly 60 / 242 cycles. Rederiving that
for #258 found that Standard's NACK path had held it 284 cycles since
issue #125 (a `WAIT 47` where `WAIT 5` belonged): legal, since UM10204
sets no t_HIGH maximum, but not the stated budget, and invisible to the
fall-through `.cyclesec` count and to the model's t_HIGH(min). It is 242
now. The data ACK is sampled the same way and not branched on; the
core's Z flag holds that reading to `HALT`.
`verification/test_firmware_i2c_ack.py` checks the schedule statically,
runs early and late responders (the latest one exactly t_SU;DAT ahead
of the rise) on both address outcomes, and
`verification/i2c_ack_schedule_mutants.py` shows the original schedule,
assembled into scratch images, failing its late-response test.

**The eight clocks per byte are unrolled, not looped.** DR 0001's
blessed constant-trip-count loop needs five live values (byte, mask,
SCL constant, temp, loop counter) and the ISA has four registers — so
each byte is 65 instructions of straight-line phases (97 since issue
#155's SDA-alignment shifts), and a whole program is 246 words (245
since issue #258 moved the ACK samples). That fits DR 0001's 256-word memory for one
protocol with headroom, but it challenges the sketch's "all three core
protocols coexist with room for a dispatch table" sizing narrative —
recorded as an ISA finding in the evidence record, not a spec change.

Cycle accounting per phase (DR 0001's opcode table; `.cyclesec` sections
state each phase's exact length — the bench cross-checks all 41):

| Phase (Fast / Standard) | Instructions | Cycles |
|---|---|---|
| data-clock low | `OUT`+`WAIT 62`/`255`+`OR` | **65 / 258** |
| data-clock high | `OUT`+`SHF`+`WAIT 51`/`233`+`MOV`+4x`SHF`+`AND` | **60 / 242** |
| ACK low (no sample since issue #258) | `OUT`+`WAIT 62`/`255`+`LDI` | **65 / 258** |
| address ACK high (incl. the `IN` sample), either branch path | `OUT`+`WAIT`+`IN`+`AND`+`WAIT`+`BNZ`, then `LDI`+`MOV`+4x`SHF`+`AND` (ACK) or `LDI`+`WAIT 5` (NACK) | **60 / 242** |
| data ACK high (incl. the `IN` sample) | `OUT`+`WAIT`+`IN`+`AND`+`WAIT`+`LDI` | **60 / 242** |
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
(`uio[3]`) are open-drain pads: `uio_oe[n]` is the complement of the
port-11 bit and the pad data is 0 (DR 0020). The
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
(CPOL, CPHA) combination (generated by `firmware/tools/gen_spi_modes.py`; the
committed `.asm` is the evidence), implementing DR 0001's "SPI (controller, mode 0,
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

**MISO sample placement (modes 1 and 3, issue #309).** In the CPHA=1
modes the peripheral launches MISO on the leading edge, so the functional
burst's `IN` is instruction 5 of the 10-instruction bit: 4 core cycles after
the launch edge and 1 before the trailing (sampling) `OUT`. The delayed-MISO
bench (`verification/test_firmware_spi_miso_delay.py`) receives every byte
pattern with the peripheral's MISO change up to 3 cycles late and misses it at
4; the earlier placement (`IN` 1 cycle after the launch edge, kept as
`verification/fixtures/spi_mode{1,3}_early_in.asm`) misses it at 1. See DR 0021's
dated entry of 2026-10-14 for the margin statement and its t_V assumption.

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
256-word store, against 246 words (245 since issue #258) for the unrolled write-only programs
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

**Multi-byte burst under one CS (issue #286).** `spi_mode0_burst3.asm`
clocks three bytes (MOSI `0xA5`, `0x3C`, `0xD2`) in one CS-low window at
the 4-cycle/bit ceiling, mode 0 only, straight-line (a loop does not fit
the 4-instruction-per-bit budget). Bench `verification/test_firmware_spi_burst.py`
(`klt functional-verification verification/request-firmware-spi-burst.json
--format json`) measures the SCLK gap at each byte boundary; mutants:
`python3 verification/spi_burst_mutants.py --out <dir>`.


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

### `dmx512_tx.asm` — DMX512 universe transmitter (issue #445)

The multi-protocol extra credit's stage-lighting controller (catalog
#443): firmware on the frozen DR 0017 ISA, no RTL change and no hardware
peripheral, speaking USITT DMX512-A. Endless packets, each a BREAK, a
mark-after-break, the 0x00 start code as one 8N2 slot, then 512 channel
slots back to back, the next BREAK landing exactly on the end of slot
512's second stop bit. TX is `uo_out[0]` — DR 0010's `dmx512` role, the
same pad the UART profiles use — driven through an external RS-485
transceiver (pin roles added to DR 0010 by this issue; the catalog row
lands with #443).

**Timing: exactly 200 core cycles per bit**, measured at the pin by
`verification/test_firmware_dmx512.py` against the independent receiver
model `verification/reference_models/dmx512.py`. As with `uart_tx.asm`,
the cycle counts are the claim; the microsecond figures below are
arithmetic at target-spec row 4's **unconfirmed** 50 MHz core clock
(20 ns/cycle; STA against this core is blocked —
`verification/records/sta-corner-sweep/`), so every wall-clock reading
is conditional on row 4.

| Interval | Cycles | at unconfirmed 50 MHz | Graded against |
|---|---|---|---|
| BREAK (line low) | **4,609** | 91.78 us | >= 4,600 (92 us, the issue's controller target; the 1986 spec's 88 us is the receiver limit) |
| mark-after-break (line high) | **605** | 12.1 us | >= 600 (12 us, same reading; spec receiver limit 8 us) |
| one bit | **200** | 4 us | 250 kbaud nominal; the model's per-slot drift bound (below) |
| one slot (1 start + 8 data + 2 stop) | **2,200** | 44 us | 8N2, back to back, no extra inter-slot mark |
| one universe | **1,133,814** | ~22.68 ms | BREAK + mark + start code + 512 slots |

**The channel pattern.** The universe is not stored (four registers, no
data memory): slot n carries level `(5 x (n-1)) mod 256`. A 5-step walk
mod 256 visits every level with period 256 — 512 slots are two periods —
and adjacent slots always differ, including across the 255 -> 4 wrap at
slot 53. The pattern's natural 0x00 slots (1 and 257) send nine
consecutive low periods, and slot 512 carries 251 (0xFB). The bench
computes the expected levels from that formula alone; the model recovers
the bytes independently.

**Where the cycles come from** (the `.cyclesec` sections of the
committed report; every instruction is 1 cycle except `WAIT imm8` =
imm8 + 1):

| Section | Instructions | Cycles |
|---|---|---|
| per data bit (`dmx512_sc_bit`, `dmx512_bit_a`, `dmx512_bit_b`) | `MOV`+`AND`+`OUT`+`SHF`+`SUB`+`WAIT 193`+`BNZ` | 1+1+1+1+1+194+1 = **200** |
| START -> first data bit | `OUT`+`WAIT 194`+`WCTL`+`LDI`+`MOV`+`AND` | 1+195+1+1+1+1 = **200** |
| last data bit -> stop 1 | `OUT`+`SHF`+`SUB`+`WAIT 193`+`BNZ`+`WAIT 1`+`OUT` | 1+1+1+194+1+2+1 = **200** |
| stop 1 -> next START (`dmx512_slot_tail_*`) | `WAIT 194`+`WAIT 195`+`RCTL`+`ADD`x5+`BNZ`+[`JMP`|fall-through]+`XOR` | 1+195+196+1+5+1+1+1 = **400** |

The image is **90 words** of the 256-word store (assembler:
`python3 firmware/tools/asm.py firmware/asm/dmx512_tx.asm`; freshness:
`python3 firmware/tools/check_firmware.py`).

**How 512 slots are counted without a slot counter.** No register is free
inside a slot for one (R1 the pin mask, R0 the level, R2 the transient
pin image, R3 the bit counter), so each half loop of 256 slots terminates
on the pattern itself: the last of the tail's five `ADD`s sets Z exactly
when the level returns to 0 — after slots 256 and 512 only. A slot
counter that wrapped at 8 bits cannot hide in this structure, and the
bench decodes all 513 slots plus the following BREAK.

**The level survives the slot in control space.** The uart_tx bit loop
shifts its byte to zero; here the same register must still hold the
level for the `+ 5`, so the program stashes it across the slot in
`PM_ADDR` (`WCTL`/`RCTL`) — the storage trick DR 0013's boot loader uses
with `UIO_DIR`. This is why the assembler reports **exactly two lint
warnings** (the half-loop `BNZ` after the reload): the linear taint scan
cannot see through a branch-target label, while the program executes no
`IN` at all, so no pin-derived data exists to taint anything. The bench
asserts that warning count.

**Timing model, and what the bench grades.** DMX receivers
resynchronise on every slot's start edge and sample the 11 bits at
nominal centres, so per-slot cumulative drift must stay under half a bit
across 10 bit periods: `MAX_SLOT_DRIFT_PCT = 5%` of the bit period
(`reference_models/dmx512.py`, derived there). E1.11 publishes no
numeric transmitter bit-rate tolerance, so that derived bound is the one
the bench cites; the DUT's slots measure 0%. Negative controls, both on
the DUT's own captured waveform: a copy with the channel-2 slot shifted
one bit early (only one stop bit left) is rejected while the preceding
byte still decodes, and a 1.051x-retimed copy fails the drift bound
while still decoding.

**Wiring a fixture (TX only).** TX = `uo_out[0]` drives D of a 3.3 V
TI **THVD1450** RS-485 transceiver on a TX-only Pmod adapter:

| THVD1450 pin | Signal | Connect to |
|---|---|---|
| 8 VCC | supply | 3.3 V |
| 7 B | line complement (D−) | DMX fixture pin 3 (data complement) |
| 6 A | line true (D+) | DMX fixture pin 2 (data true) |
| 5 GND | common | board GND **and** fixture common (DMX pin 1) |
| 4 D | driver input | `uo_out[0]` (the board pin carrying it) |
| 3 DE | driver enable | 3.3 V (always transmitting) |
| 2 /RE | receiver enable | 3.3 V (held disabled; TX only) |
| 1 R | receiver output | unconnected |

DE and /RE tie high, so the driver is always enabled: the chip sends
whatever `uo_out[0]` does, idle-high between packets. Terminate 120 ohm
across A–B **at the fixture end only** (the last device on the line);
fixtures carry their own connector wiring, pin 1 common, pin 2 true (D+,
`A`), pin 3 complement (D−, `B`). Receipt of this Pmod, bring-up and a
real fixture are out of scope here (issue #445): the claim this program
makes is the cycle-exact waveform at the pad, verified at RTL.

Bench: `verification/test_firmware_dmx512.py`
(`verification/request-firmware-dmx512.json`), registered in
`scripts/rtl-bench-inventory.txt`; model self-test
`verification/test_dmx512_model.py`.

```bash
klt functional-verification verification/request-firmware-dmx512.json --format json
```

### `nec_ir.asm` — NEC infrared remote transmitter (issue #448)

The multi-protocol extra credit's consumer-IR entry (catalog #443):
firmware on the frozen DR 0017 ISA, no RTL change and no hardware
peripheral. The 38 kHz carrier is a counted `OUT`/`WAIT` loop on one pin
(the ISA's own timing determinism is the modulator), and the
pulse-distance coding is which of two exact space lengths follows each
mark. One frame every ~128 ms, forever: the leader (9 ms-class mark +
4.5 ms space), then address, ~address, command and ~command, LSB first
within each byte. Each of the 32 bits has a 562.5-us-class mark followed by a 562.5-us or a 1,687.5-us
space. The final mark precedes 60 ms of silence. The carrier line is
IR_TX = `uo_out[7]` (DR 0010's `nec_ir_tx` role, added by this issue; the
same pad as WS2812's DIN, one image per run — the choice makes the
carrier-high image and the bit-7 mask one constant). The receiver-module
input is IR_RX = `ui_in[4]` (DR 0010's `nec_ir_rx` role): board wiring
for a 38 kHz demodulating receiver module, read by no committed image
yet (the RX decode firmware is a follow-up; see the issue).

**Timing, all measured at the pin** by
`verification/test_firmware_nec_ir.py` against the independent model
`verification/reference_models/nec_ir.py` (demodulator included). As with
its siblings the cycle counts are the claim; the microsecond/kilohertz
figures are arithmetic at target-spec row 4's **unconfirmed** 50 MHz
clock (20 ns/cycle):

| Interval | Cycles | at unconfirmed 50 MHz | vs the protocol |
|---|---|---|---|
| carrier period (rise to rise, every one) | **1,316** | 26.32 us = 37,994 Hz | 38 kHz nominal, −160 ppm |
| carrier high | **439** | 8.78 us | 1/3 duty (33.35%), the customary NEC choice |
| in-burst carrier low | **877** | 17.54 us | completes the 1,316-cycle period |
| leader mark (342 periods) | **449,195** | 8,983.90 us | 9 ms − 0.18% |
| leader space | **225,000** | 4,500.00 us | 4.5 ms, exact |
| bit / final mark (22 periods) | **28,075** | 561.50 us | 562.5 us − 0.18% |
| space of a 0 bit | **28,125** | 562.50 us | 562.5 us, exact |
| space of a 1 bit | **84,375** | 1,687.50 us | 1,687.5 us, exact |
| inter-frame idle | **3,000,000** | 60,000.00 us | >= 4.05 ms (the model's frame-separation floor); frame period 110–146 ms by data |
| one frame (always: a byte and its complement hold 16 ones) | **3,400,670** | 68.01 ms | leader + 16x(28,075+28,125) + 16x(28,075+84,375) + final mark |

**Where the bits come from.** The frame is a table after the code, ONE
WORD PER BIT (`LDI R0, 0x80` = 1, `LDI R0, 0x00` = 0, `HALT` = end
marker), read with DR 0012's `PM_DATA_*`: the high byte separates bit
word from marker, the low byte IS the bit, and `PM_ADDR`'s auto-increment
is the frame's bit counter. A whole byte cannot survive a carrier burst
(the burst needs all four registers), so the isolation happens at
assembly time in the table — which also means a host can load any
32-bit frame by writing table words, and the bench does (random frames,
and the mutation control below).

**The leader is two 171-period halves** because the burst counter is
8-bit and 342 does not fit; the junction completes its carrier low
(`SUB`+`BNZ`+4x`WAIT`+`JMP`+`LDI`+the rise `OUT`'s own cycle = 877), so
every one of the 342 periods measures exactly 1,316 cycles — no dropout
for a demodulator to see.

**The two documented lint warnings.** The marker test (`BNZ
frame_end`) and the bit test (`BZ bit0`) branch on table bytes — the
`RCTL PM_DATA_*` reads taint their destination. The marker branch picks
"one more code word or end of frame" and both targets sit at the same
10-cycle offset to the next rise; the bit branch picks the bit's OWN
space length, which is the pulse-distance encoding itself. Each path is
internally cycle-exact; the difference between them is the protocol. The
bench asserts the warning count is exactly two.

**What the bench grades.** The model's stated windows (±10% on every
mark and space, ±5% on the carrier — no NEC transmitter tolerance is
published) AND the exact cycle counts above, measured edge to edge. The
mutation control (every carrier-high `WAIT 181` -> `WAIT 175`) drifts
the carrier 0.5% and the marks 1% — inside every model window, so the
model still passes and only the exact-cycle assertion catches it: the
cycle guard is the load-bearing check. A 1.15x-stretched copy of the
DUT's own capture fails the model's windows, proving the capture-and-
decode path can fail. Advancing one falling edge in the captured leader by
100 cycles preserves every period and envelope width. The bench rejects
the resulting 339-cycle high and measures its paired low as 977 cycles.

**Wiring a fixture.** IR_TX = `uo_out[7]` drives an IR LED through a
transistor; IR_RX = `ui_in[4]` comes from a 38 kHz demodulating receiver
module (output idle high, active low — e.g. a TSOP34338-class part):

| Part | Pin | Connect to |
|---|---|---|
| NPN transistor (2N3904-class) | base | `uo_out[7]` through 1 kOhm |
| | emitter | GND |
| | collector | TSAL6200 cathode through 100 Ω |
| Vishay TSAL6200 IR LED | anode | 3.3 V |
| receiver module | Vout | `ui_in[4]` |
| | Vcc | 3.3 V, 100 nF close to the pin |
| | GND | GND |

The LED branch targets about 20 mA during each carrier high. Assuming a
1.2 V LED forward drop and 0.2 V across the saturated transistor, the
100 Ω resistor gives (3.3 − 1.2 − 0.2) V / 100 Ω = 19 mA.
[Vishay TSAL6200 datasheet](https://www.vishay.com/docs/81010/tsal6200.pdf)

The transmitter is push-pull into the transistor's base; the module's
open-collector-style output idles high and pulls low on a burst, which
is what a receive firmware would sample. Receipt of real hardware,
bring-up and the RX decode firmware are out of scope here: the claim
this program makes is the cycle-exact waveform at the pad, verified at
RTL.

The image is **164 words** of the 256-word store (assembler:
`python3 firmware/tools/asm.py firmware/asm/nec_ir.asm`; freshness:
`python3 firmware/tools/check_firmware.py`). Bench:
`verification/test_firmware_nec_ir.py`
(`verification/request-firmware-nec-ir.json`), registered in
`scripts/rtl-bench-inventory.txt`; model self-test
`verification/test_nec_ir_model.py`.

```bash
klt functional-verification verification/request-firmware-nec-ir.json --format json
```

### `swd_probe.asm` — SWD debug probe, one word of AP memory (issues #452, #500)

The multi-protocol extra credit's debug-probe role: firmware on the frozen
DR 0017 ISA, no RTL change and no hardware peripheral, speaking Arm's
Serial Wire Debug as the **host**. The chip generates SWCLK and reads a
target's SWDIO responses in the turnaround cycles — the first firmware
here that samples a line the other side clocks back at it. The protocol
choice and the counted cost model are the dated notes in DR 0018. Issue
#452 landed the fallback image (IDCODE and one DP read, 227 stored words,
unrolled at four words per request bit); issue #500 replaced it with the
**table-driven image** below, which reads one word of AP memory:
**256 stored words** of the 256-word store (116 code, 140 table; the store
is full), **356 SWCLK rising edges**, the last SWCLK fall at core edge 2,615. Pins: SWCLK
`uio[2]`, SWDIO `uio[3]` (DR 0010's `swd` phase), both push-pull while
driven (`UIO_DIR` 0x0C), SWDIO released at each turnaround cycle (its
`UIO_DIR` bit cleared) for the target-driven response phases, with a board
pull-up on SWDIO as ADIv5 requires.

The schedule: line reset (50 SWCLK cycles, SWDIO high), the 16-bit
JTAG-to-SWD switch 0xE79E LSB first, a second line reset, two idle clocks
(SWDIO low), then five transactions, each an 8-bit even-parity request, one
clocked turnaround cycle and the 3-bit ACK:

| # | Transaction | Request | Then |
|---|---|---|---|
| 1 | DP IDCODE (DPIDR) read | 0xA5 | 32 data bits + parity from the target |
| 2 | DP SELECT write | 0xB1 | return turnaround, probe drives 0x00000000 + parity |
| 3 | AP TAR write | 0x8B | return turnaround, probe drives 0x20000004 + parity |
| 4 | AP DRW read (**posted**) | 0x9F | returns the read buffer's *previous* value, not the word |
| 5 | DP RDBUFF read | 0xBD | returns the addressed word (the result) |

after which come eight idle clocks with SWDIO low before SWCLK stops. Every
response sample is reported on `uo_out` as the masked SWDIO byte (0x08 or
0x00), in transaction order: the DRW read's data is the stale buffer value
and the RDBUFF read's is the fixture word, so the bench can tell a probe that
reports the posted read from one that fetches the result.

**The table-driven shape.** The ISA has no data memory, but DR 0012's
`PM_ADDR` / `PM_DATA_HI` / `PM_DATA_LO` read stored words (the NEC IR
program's shape). Every probe-driven bit is one stored word, an `LDI` the
program never executes: `LDI R2, 0x0C` (0x180C) is a 1 and `LDI R0, 0x04`
(0x1004) a 0. The *high* byte has bit 3 set only for a 1, so ANDed with the
SWDIO mask it is the SWCLK-low pin image; the *low* byte is the SWCLK-high
image. One 8-word loop (`txq`) sends the request bits and the write-data
bits of every transaction. Control words in the same table drive a small
engine: a start word (another transaction, 8 request bits, or the end), a
word after the request (a response follows: the 2 ACK slots after the first
bit), a word after the ACK (a read: 33 data slots; a write: the 33 write-data
bits that follow the turnaround) and, after a write's data, the
transaction-complete word. The sequence, the kind and the length of every
transaction are therefore data, and the code is 116 words. That is the
measurement DR 0018's note left open: the unrolled schedule needed about 180
words per write; stored as data a bit costs one word, and the five
transactions fit in the 256-word store (issue #500 first had 11 words spare;
the full-ACK check below uses all of them).

**ACK bit order.** The ADIv5 ACK numeric codes are OK = 0b001,
WAIT = 0b010, FAULT = 0b100, and the target sends the code LSB first
(IHI 0031H B4.1.5), so in time order on the wire OK is **1,0,0**, WAIT
**0,1,0** and FAULT **0,0,1**. The report bytes carry that wire order.
The probe branches on the *first* ACK bit: a 0 (WAIT or FAULT) clocks the
two remaining ACK slots, the return turnaround with SWDIO released,
re-drives SWDIO low, and ends the run with the eight trailing idle clocks.
A 1 is then checked against the whole OK code: each of the other two ACK
bits must be **0**. A silent target leaves the pulled-up line at 1,1,1 and
1,0,1 / 1,1,0 are not ACK codes; either is a protocol error, so the probe
never drives write data into it: it keeps SWDIO **released** for the rest of
the ACK, the possible 33 data bits and the turnaround (35 slots, as Arm's
CMSIS-DAP backs off a protocol error), then re-drives SWDIO low, ends the run
with the eight trailing idle clocks and issues no further request. The model's
`ACK_NONE` / `ACK_BAD` targets and the `driven-after-bad-ack` rule grade it,
and a mutant with the check removed is rejected. With CTRL/STAT.ORUNDETECT = 0 (the
power-up setting) a WAIT or FAULT has no data phase — a rejected **write**
sends no data — so no data slots are clocked. There is no retry (agreed
scope): an error on any transaction ends the run there, so a rejected SELECT
or TAR write means the memory read is never issued. DPIDR must answer OK;
the WAIT/FAULT cases are exercised on each of the five transactions.

**The modeled MEM-AP.** `verification/reference_models/swd.py` (`MemAp`)
decodes the requests it is sent. SELECT and TAR have **no reset value**
(an AP access before either write is a violation), so the probe cannot skip
the writes; the DRW read is posted. The MEM-AP's **word-access starting
state** is CSW.Size = 0b010 (32-bit) with CSW.AddrInc = 0b00 — the probe
does not write CSW, so the model starts there; a real part's CSW reset is
implementation-defined, which this records as an assumption rather than
proving it for silicon. The ADIv5 register addresses and fields carry the
same "confirm" mark as the other constants (no copy of IHI 0031 is in this
repository).

**Timing, in core cycles** (every instruction is 1 cycle, a `PM_DATA_HI`
read is a fixed 2; one `OUT` per SWCLK transition). Measured at the pads by
`verification/test_firmware_swd.py` against the independent target model.
As with the other programs, the cycle counts are the claim; every
microsecond figure below is arithmetic at target-spec row 4's
**unconfirmed** 50 MHz core clock (20 ns/cycle; STA against this core is
blocked — `verification/records/sta-corner-sweep/`).

| Interval | Cycles | at unconfirmed 50 MHz | Graded against |
|---|---|---|---|
| line reset, per SWCLK cycle (SWDIO high) | high **1**, low **3** (**2** on the second reset's first cycle) | 20 / 60 ns | >= 50 cycles with SWDIO high (ADIv5 connection; pyOCD's shape sends it) |
| switch / request / write-data, per bit (table loop) | high **7**, low **2** | 140 / 40 ns | SWDIO changes only while SWCLK low, stable across every rising edge (2 cycles of setup) |
| response sample loop, per slot | high **1**, low **4..7** | 20 / 80..140 ns | sample taken in the SWCLK-low phase before the rise (IHI 0031 B4.3.1) |
| request, 8 bits | 72 | 1.44 us | even parity over APnDP/RnW/A2/A3; start 1, stop 0, park 1 |
| write data, 33 bits | 297 | 5.94 us | 32 bits LSB first + even parity |
| whole program | 356 SWCLK cycles; last SWCLK fall at core edge 2,615 | 52.3 us clocked | 8 trailing idle clocks with SWDIO low before SWCLK stops (ADIv5 B4.1.4) |

The table loop's SWCLK-high phase is long (7 cycles) because the next bit's
table read, mask and `OUT` sit between two rising edges; ADIv5 sets no
numeric SWCLK width minimum for a host-generated clock, so no width limit
is invented. The model records the widths above and the bench holds the
program to them. The ADIv5 constants themselves carry DR 0015's "confirm"
mark (no copy of IHI 0031 is in this repository) — the constants that
matter here (50-clock reset, 0xE79E, turnarounds, even parities, 8 trailing
idles) are cross-checked against pyOCD's and CMSIS-DAP's observable
behaviour, as DR 0018 records.

**Register shape.** R0 holds the SWCLK-low/SWDIO-high image 0x08, which
doubles as the SWDIO mask for the table loop and the sample loop's `AND`;
R1 holds the SWCLK-high/SWDIO-high image 0x0C, which doubles as the
push-pull `UIO_DIR` mask; R2 counts (and receives the count words from the
table); R3 is the per-bit image / table-byte / decrement scratch.

**Lint.** The assembler's data-dependent-latency lint reports **nine**
branches. Three (`BZ ackerr` after the first ACK bit, `BNZ ackbad` after each
of the other two) read the target's ACK from the pin — the documented
handshake case. Six branch on a table byte or on a loop count read from the
table (`BNZ tail`, `BNZ txn` after a control word, `BZ ret` for a write,
`BNZ txq`, the loop-count `SUB`s of `txq`, `ackl` and `rx`): the
data is the program's own constant table, so the schedule is fixed at
assemble time, the same reading as the NEC IR program's.

Assemble: `python3 firmware/tools/asm.py firmware/asm/swd_probe.asm`
(**256 words**, 261 fall-through cycles, 9 warnings as above); freshness:
`python3 firmware/tools/check_firmware.py`.

**Wiring a target (direct, same rail).** The chip's I/O is 3.3 V on the
Tiny Tapeout demo board (`docs/info.md`, "External hardware"), and common
SWD targets are 3.3 V, so no level shifter is needed — connect directly:

| Signal | Connect to |
|---|---|
| SWCLK `uio[2]` | target SWCLK (ARM 20-pin / SEGGER 20-pin SWD connector pin **9**, or the target's SWD header; pin 4 is GND) |
| SWDIO `uio[3]` | target SWDIO (20-pin pin **7**), with a pull-up (about 10 kohm) to 3.3 V — ADIv5 requires one; the probe tri-states SWDIO for the turnaround and response phases |
| GND | target GND (20-pin pin **4**; one common is enough at these speeds; pin 1 is VTref, not ground) |

A 5 V target would need level shifting (out of scope; `docs/info.md`
"Levels and other buses"). Receipt on real silicon is out of scope here:
the claim this program makes is the cycle-exact waveform at the pads
against the scripted target, verified at RTL (no gate-level run).

Bench: `verification/test_firmware_swd.py`
(`verification/request-firmware-swd.json`), registered in
`scripts/rtl-bench-inventory.txt`; model self-test
`verification/test_swd_model.py`.

```bash
klt functional-verification verification/request-firmware-swd.json --format json
```

### `can_2a.asm` — CAN 2.0A node (issue #450)

The multi-protocol extra credit's automotive-bus entry (catalog #443):
firmware on the frozen DR 0017 ISA, no RTL change and no hardware
peripheral. One program, one bus sequence: transmit a standard data frame
(ID 0x5A5, DLC 3, data 0x11 0x1F 0x22) with bitwise arbitration and
retransmission on a lost arbitration, then receive a DLC-3 frame with
de-stuffing, the remainder-zero CRC-15 check and a conditional dominant
ACK. Stuffing runs on DR 0015's P2 `LINE_*` unit and the CRC-15 (poly
0x4599, seed 0) on its P1 `CRC_*` engine, one `CRC_BIT` per destuffed bit
(both 1 cycle; no ALU fallback was needed). CAN_TXD is `uo_out[0]`
(push-pull, the pad the UART and DMX512 transmitters also use) and
CAN_RXD is `ui_in[0]` (PROG_SER during the load phase). The file is
generated by `firmware/tools/gen_can_2a.py`; the committed `.asm` is the
evidence.

**Timing: exactly 400 core cycles per bit**, sample point at offset 300
(75%), measured at the pin by `verification/test_firmware_can.py` against
the independent model `verification/reference_models/can_2a.py`. As with
`uart_tx.asm`, the cycle counts are the claim; the microsecond figures
are arithmetic at target-spec row 4's **unconfirmed** 50 MHz core clock
(20 ns/cycle; STA against this core is blocked --
`verification/records/sta-corner-sweep/`), so every wall-clock reading is
conditional on row 4.

| Interval | Cycles | at unconfirmed 50 MHz | Graded against |
|---|---|---|---|
| one bit time | **400** | 8 us (125 kbit/s) | every TXD edge on the 400-cycle grid; the model's +-15% per-bit bound |
| sample point | **300** from the bit-start `OUT` | 6 us (75%) | the sample-point probes (a glitch straddling offset 300 loses; at offset 100 it does not) |
| SOF poll / idle detect | 11 / 20 recessive bits | -- | `docs/info.md` row |

The image is **253 words** of the 256-word store (assembler:
`python3 firmware/tools/asm.py firmware/asm/can_2a.asm`; freshness:
`python3 firmware/tools/check_firmware.py`; report
`firmware/build/can_2a.cycles.txt`). Every path through a bit window --
recessive or dominant, consumed or stuff slot, byte boundary or not -- is
padded to the same 400-cycle OUT-to-OUT span; the generator derives each
`WAIT` from the path's instruction count, and its host-side
cycle-accurate simulation (`firmware/tools/test_gen_can_2a.py`) is its
gate.

**Highest sustained rate recorded: 125 kbit/s** (400 cycles/bit, the
issue's start rate), the benched claim. The generator's static solver
closes the same instruction stream at 100 cycles/bit, but no 500 kbit/s
claim is made without a bench -- it is left unclaimed, not asserted.

**Status words** on `uo_out` (bit 0 is CAN_TXD and stays recessive in
every one): `0x41` / `0x61` after the transmit (ACK seen / not), and at
HALT `0xC1` (received, CRC ok, ACK driven), `0xC3` (received, CRC error,
no ACK), `0xC5` (stuff error, frame abandoned).

**Four ISA findings** (the register ceiling shapes the program):

1. R3 holds the one constant 0x01 (the CAN_RXD mask and the loop
   decrement), so every counter counts in ones and every sample is one
   `AND` away.
2. The 19-bit header is never byte-aligned, so the transmit stream rides
   one arbitrated table loop (five bit-reversed table bytes of `WAIT
   imm8` words read through `PM_DATA_HI`/`PM_DATA_LO`, plus a literal
   3-bit tail). The CRC readout takes two passes: `CRC_NEXT` bytes are
   MSB-first but `LINE_PUT` presents bit 0, so each byte is reversed by a
   7-word rotation loop; byte 0 waits in `PM_ADDR`.
3. The receive path is sized to this image's own frame (DLC 3; 58
   destuffed bits): a general DLC parser needs a fifth live value
   (collector, counter, sampled bit, compare scratch, constant) and the
   ISA has four registers.
4. Arbitration is monitored on every transmitted bit through the CRC
   sequence; a mismatch after the arbitration field is a bit error in CAN
   terms, and this image takes the same back-off-and-retransmit path
   without the error-frame signalling a full controller adds.

**`UIO_DIR` is used as scratch storage, and that drives pads.** The
register ceiling in finding 1 also forces `UIO_DIR` (DR 0012's
pin-direction register) to serve as a spare counter and flag register --
the storage trick DR 0013's boot loader uses, but there with `UIO_OD =
0xFF` so `uio_oe = 0` whatever it holds. This image writes neither
`UIO_OD` nor `UIO_OUT`, so `uio_od = 0` and `uio_out = 0`, and
`uio_oe = uio_dir` (`src/tt_um_2amlogic_protocol_emulator.v`): **every
`UIO_DIR` bit that is set drives that `uio` pad low.** The values
written (`WCTL UIO_DIR` at 7 sites, checked by `prof_can`):

| Phase | `UIO_DIR` value | `uio` pads driven low |
|---|---|---|
| setup, byte-boundary dispatch down-count | 0x05, 0x04, 0x03, 0x02, 0x01, 0x00 | up to `uio[0..2]`, per set bit, through every transmitted frame |
| transmit ACK-slot flag | 0x00 / 0x01 | `uio[0]` when another node ACKed |
| receive CRC-check byte (two cycles) | the CRC_NEXT byte -- any value 0x00-0xFF | any `uio` pad, for about two cycles |
| receive ACK flag | 0x00 (CRC error) / 0x01 (ACK driven) | `uio[0]` when ACK driven |

`uio[0..2]` carry the SPI / I2C / SWD roles and the QSPI Pmod header in
DR 0010's inventory, so a board must not have anything connected to the
`uio` pads while this image runs (the CAN wiring below uses none).
DR 0010's `pin_modes` object holds one `uio_dir` value per profile and
cannot express a varying one, so `can` has no entry; the DR 0010 CAN
section records this instead, and `prof_can` pins the write-site count
and the start value so the two cannot drift silently.

**Wiring a fixture.** TXD = `uo_out[0]` drives D of a 3.3 V TI
**SN65HVD230** CAN transceiver on a Pmod adapter; its R output returns on
`ui_in[0]`:

| SN65HVD230 pin | Signal | Connect to |
|---|---|---|
| 1 D | driver input | `uo_out[0]` (CAN_TXD) |
| 2 GND | common | board GND and bus ground |
| 3 VCC | supply | 3.3 V |
| 4 R | receiver output | `ui_in[0]` (CAN_RXD) |
| 5 Vref | reference output | unconnected |
| 6 CANL | bus low | CAN bus CANL |
| 7 CANH | bus high | CAN bus CANH |
| 8 Rs | slope control | GND (high-speed mode) |

Terminate 120 ohm across CANH-CANL at each end of the bus. **Caveat
(DR 0021):** `IN` samples `ui_in[0]` directly with no synchronizer, so a
transition inside the setup/hold window of the sampling edge can read
metastably. The image samples at 75% of the bit, away from the edges of
a bit-aligned transmitter, but the bench's receive-tolerance figure
(+0.5% receives, +5% does not, hard-sync only) is RTL-level, not a
statement about asynchronous bus edges on silicon. Bring-up with a real
transceiver and bus is out of scope here (issue #450): the claim is the
cycle-exact behaviour at the pins, verified at RTL.

Bench: `verification/test_firmware_can.py`
(`verification/request-firmware-can.json`), registered in
`scripts/rtl-bench-inventory.txt`; model self-test
`verification/test_can_2a_model.py`.

```bash
klt functional-verification verification/request-firmware-can.json --format json
```

### `i2s_tx.asm` — I2S audio transmitter (issue #451)

The multi-protocol extra credit's frame-clocked entry (catalog #443):
firmware on the frozen DR 0017 ISA, no RTL change, no new instruction and
no hardware peripheral. The core is the I2S controller: it drives BCLK, WS
and SD and reads no pin. Philips framing, 16-bit stereo in 32-BCLK slots
(64 BCLK per frame): WS and SD change on BCLK's falling edge, the receiver
samples SD on the rising edge, WS changes one BCLK **before** the slot's
MSB (so the MSB is one BCLK after the WS edge), MSB first, 16 data bits
then 16 zero pad bits, WS low = left. Pins are DR 0010's `i2s` phase: SD
`uo_out[7]`, BCLK `uo_out[6]`, WS `uo_out[5]`, all push-pull.

The samples are a 16-frame stereo table in the last 64 words of program
memory (`LDI R0, b` words, never executed, read with `PM_DATA_HI` /
`PM_DATA_LO`; no data directive exists, DR 0003): left a full-scale sine
(it includes the extremes 0x7FFF and 0x8000), right the same sine at twice
the frequency and half amplitude. The table wrap is undone branch-free by
ORing 0xC0 into `PM_ADDR` during the right slot's pad.

**Timing: exactly 16 core cycles per BCLK (8 low, 8 high).** The figures
below are core cycles, graded at the pins by
`verification/test_firmware_i2s.py` against the independent receiver model
`verification/reference_models/i2s.py`; every frequency is arithmetic at
target-spec row 4's **unconfirmed** 50 MHz clock (20 ns/cycle; STA against
this core is blocked, `verification/records/sta-corner-sweep/`).

| Interval | Cycles | at unconfirmed 50 MHz | Graded against |
|---|---|---|---|
| BCLK period | **16** (8 low + 8 high) | 320 ns, 3.125 MHz | the bench: every BCLK edge on the 8-cycle grid |
| WS / SD change | on the cycle BCLK falls | -- | the model's set-up and hold limits |
| slot (32 BCLK) | **512** | 10.24 us | the model's slot-length check; L/R alternation |
| frame (64 BCLK) | **1,024** | 20.48 us, fs = 48,828.125 Hz | the committed run's 18 frames |
| fs error vs 48 kHz | -- | **+1.73 %** (a rate error, not a framing error) | recorded, not graded |

Why not exactly 48 kHz: a 64-BCLK frame at 48 kHz needs 3.072 MHz, i.e.
16.28 cycles per BCLK, and the core has only integer cycles. Other
reachable rows (2k cycles per BCLK, 64 BCLK per frame) at 50 MHz: 17 cycles
-> 2.941 MHz, fs 45.96 kHz (unequal phases); 32 cycles -> 1.5625 MHz, fs
24.41 kHz. This image uses 16.

The image is **256 words** of the 256-word store: 154 code words, 38 NOP
alignment words (never run; the table must start at 0xC0 so that
`PM_ADDR |= 0xC0` is the wrap, and the assembler has no `.org`), and the
64-word table (assembler: `python3 firmware/tools/asm.py
firmware/asm/i2s_tx.asm`; freshness: `python3 firmware/tools/check_firmware.py`;
report `firmware/build/i2s_tx.cycles.txt`). The bench loads other tables
over the code words, so the table is host-replaceable without touching code.

**External part and Pmod wiring.** A 3.3 V **TI PCM5102A** I2S stereo DAC
breakout on a Pmod adapter (TI datasheet SLAS859C, May 2012, rev. May
2015, [pcm5102a.pdf](https://www.ti.com/lit/ds/symlink/pcm5102a.pdf)).
Confirmed against SLAS859C:

- **No MCLK pin needed (§ 9.3.5.3, *Clock Slave Mode with BCK PLL*).**
  When **SCK** (pin 12) is held at GND while BCK and LRCK toggle for 16
  successive LRCK periods, the internal PLL starts automatically and
  generates the internal system clock from BCK.
- **Format, bit depth and rate (§ 9.3.2.2, Table 2, § 9.3.5.2, Table 11).**
  Hardware-control mode accepts 16-, 20-, 24- and 32-bit binary
  two's-complement MSB-first audio at BCK = 32 fs or 64 fs, with **FMT**
  (pin 16) = Low selecting Philips I2S (LRCK Low = left, High = right;
  High selects left-justified). The `32 kHz - 44.1 kHz - 48 kHz`
  single-rate detector accepts ±4 % tolerance (§ 9.3.5.2), which covers
  this image's 64-BCK frame (`BCK = 3.125 MHz`, `fs = 48.83 kHz`,
  `+1.73 %` over 48 kHz at the unconfirmed 50 MHz clock; BCK period
  320 ns, 160 ns high / 160 ns low vs § 8.6 minimums 20 ns / 9 ns at
  3.3 V).

| Output Pmod (`uo_out` header) | Signal | PCM5102A (TSSOP-20) | Strap / connection |
|---|---|---|---|
| pin 8 (`uo_out[5]`) | WS / LRCLK | 15 LRCK | word clock (low = left) |
| pin 9 (`uo_out[6]`) | BCLK | 13 BCK | bit clock (64 × fs) |
| pin 10 (`uo_out[7]`) | SD | 14 DIN | serial audio data, MSB first |
| pins 5, 11 (GND) | GND | 3 CPGND, 9 AGND, 19 DGND | common ground |
| pins 6, 12 (3.3 V) | 3V3 | 1 CPVDD, 8 AVDD, 20 DVDD | 3.3 V supply (decouple LDOO pin 18 with 0.1 uF) |
| — | MCLK strap | 12 SCK | tie to **GND** (enables internal BCK PLL) |
| — | format strap | 16 FMT | tie to **GND** (I2S format) |
| — | mute control | 17 XSMT | tie to **3.3 V / AVDD** (soft un-mute, § 9.3.3) |
| — | filter / de-emph | 11 FLT, 10 DEMP | tie to **GND** (normal latency, de-emphasis off) |

A Digilent Pmod I2S2 is **not** a 3-wire drop-in: its Cirrus CS4344 DAC
has no BCK PLL and requires an external MCLK (a fourth output this image
does not generate). Bring-up with a physical DAC is out of scope
(issue #451): the claim is the cycle-exact behaviour at the pins, verified
at RTL.

Bench: `verification/test_firmware_i2s.py`
(`verification/request-firmware-i2s.json`), registered in
`scripts/rtl-bench-inventory.txt`; model self-test
`verification/test_i2s_model.py`. Negative controls (each rejected for its
own reason): no one-BCLK delay (left-justified), a 31-BCLK slot, a
17-cycle BCLK period, and a re-graded capture with SD delayed 0.4 T.

```bash
klt functional-verification verification/request-firmware-i2s.json --format json
```

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
`PM_DATA_LO`, `RUN`, `PM_CRC_LO`, `PM_CRC_HI`, `BOOT_STATUS`, `HW_ID`, and
DR 0015's primitives `CRC_CFG`, `CRC_POLY`, `CRC_STATE`, `CRC_BIT`,
`CRC_BYTE`, `CRC_NEXT`, `LINE_CFG`, `LINE_PUT`, `LINE_OUT`, `LINE_STUF`
(0x10–0x19, issue #208) — or a number. The cycle report costs them per the
table: 1 cycle, except `WCTL PM_DATA_LO`, `WCTL RUN` and `RCTL PM_DATA_HI`,
which are a fixed 2, and `WCTL CRC_BYTE`, a fixed 9. An
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
| `CRC_CFG`, `CRC_POLY`, `CRC_STATE`, `CRC_NEXT` (DR 0015 P1) | any `WCTL` of a tainted register to a `CRC_*` index has happened. One taint covers the whole unit, and it stays (the CRC accumulates, and one clean byte does not clean the other three). |
| `LINE_CFG`, `LINE_OUT`, `LINE_STUF` (DR 0015 P2) | the last `WCTL LINE_CFG` wrote a tainted register, or a tainted `WCTL LINE_PUT` came after it. |

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
