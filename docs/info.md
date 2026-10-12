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
`uo_out` and `uio_out` writable by `OUT`. The direction of each
bidirectional pin is set by firmware at run time, through the control
space below; after reset every one is an input.

**Control space** (`spec/decision-records/0012-control-space-and-runtime-pin-direction.md`,
Proposed). Two operand combinations that used to be no-ops address
control registers, with the register index in `imm8`: `WCTL k, Rs` (`OUT`
to port `00`) writes one and `RCTL Rd, k` (`IN` from port `10`) reads one.

| `k` | Name | Access | Cycles | Meaning |
|---|---|---|---|---|
| `0x00` | `UIO_DIR` | R/W | 1 | per-pin push-pull drive enable for `uio[n]` |
| `0x01` | `UIO_OD` | R/W | 1 | per-pin open-drain enable: drives low when `uio_out[n]` is 0, releases when 1; wins over `UIO_DIR` |
| `0x02` | `PM_ADDR` | R/W | 1 | program-memory word address |
| `0x03` | `PM_DATA_HI` | R/W | W 1, R 2 | W: latch the high byte. R: read the word at `PM_ADDR`, return its high byte, latch its low byte |
| `0x04` | `PM_DATA_LO` | R/W | W 2, R 1 | W: commit `{high latch, Rs}` at `PM_ADDR`, then `PM_ADDR` + 1. R: return the latched low byte, then `PM_ADDR` + 1 |
| `0x05` | `RUN` | W | 2 | jump: program counter ← `Rs` |
| `0x06`, `0x07` | `PM_CRC_LO`, `PM_CRC_HI` | R, W clears | 1 | CRC-16/XMODEM (poly `0x1021`, init 0) over every word committed to program memory, by the serial load or by `PM_DATA_LO`; high byte of each word first |
| `0x08` | `BOOT_STATUS` | R | 1 | bit 0: a serial load completed since reset. Bit 1: the instruction reading it was fetched from the boot ROM (so a loaded program always reads 0 there) |
| `0x09` | `HW_ID` | R | 1 | design revision byte, `0x01` |
| `0x10` | `CRC_CFG` | R/W | 1 | P1 configuration: bits 4:0 width − 1 (1 to 32 bits), bit 5 reflected (LSB first), bit 6 read-out inversion. A write rewinds the byte pointer |
| `0x11` | `CRC_POLY` | R/W | 1 | P1 polynomial, one byte per access at the byte pointer (byte 0 first), pointer + 1. Normal form for normal mode, bit-reversed for reflected mode |
| `0x12` | `CRC_STATE` | R/W | 1 | P1 register, one byte per access at the byte pointer, pointer + 1; reads mask to the width |
| `0x13` | `CRC_BIT` | W | 1 | one CRC/LFSR step with data bit `Rs[0]` |
| `0x14` | `CRC_BYTE` | W | **9** | eight steps with the bits of `Rs` (LSB first if reflected), 1 + 8 stall cycles |
| `0x15` | `CRC_NEXT` | R | 1 | the register, complemented if inversion is on, masked to the width, one byte at the pointer, pointer + 1 |
| `0x16` | `LINE_CFG` | R/W | 1 | P2 configuration: bits 1:0 NRZI (01 toggle on 0, 10 toggle on 1, else none), bits 3:2 stuffing (01 a 0 after N ones, 10 the complement after N equal bits), bits 6:4 N; bit 7 sets the line level. A write clears the run count |
| `0x17` | `LINE_PUT` | W | 1 | present data bit `Rs[0]`; on a stuff slot the stuff bit goes out instead and the data bit is not consumed |
| `0x18` | `LINE_OUT` | R | 1 | bit 0 the line level, bit 1 its complement (one `OUT` drives a differential pair) |
| `0x19` | `LINE_STUF` | R | 1 | bit 0: the last `LINE_PUT` was a stuff slot, so present the same bit again |

`0x10`–`0x19` are DR 0015's protocol-neutral primitives (Proposed): **P1**,
a CRC / LFSR step with a programmable polynomial, and **P2**, NRZI coding
with a bit-stuffing counter. Neither knows a frame; the firmware builds the
packet and uses them for the line coding and the CRC. They are checked
against the published CRC catalogue values (CRC-5/USB, CRC-16/USB, CRC-32,
CRC-8/MAXIM, CRC-15/CAN), a PRBS7 sequence, and an independent USB / HDLC /
CAN line decoder (`verification/test_primitives.py`).

Any other index is reserved: a write does nothing and a read returns 0, in
one cycle, and the assembler refuses it unless given `--allow-reserved`.
Every control register resets to 0 except `HW_ID` (and `LINE_OUT`, which
reads its complement bit as 1). No control access changes a
flag. `OUT` to port `01` and `IN` from port `11` remain no-ops.

**Timing is the product, so it is fixed by construction.** Every instruction
retires in exactly one cycle, with two kinds of exception, both fixed by
the instruction word itself and never by a register or a pin: `WAIT imm8`
stalls `imm8 + 1` cycles, the three control accesses marked 2 in the
table above take exactly 2 (the program memory has one port, so a data
access to it stalls instruction fetch for one cycle, always), and
`WCTL CRC_BYTE` takes exactly 9. A conditional branch costs the
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
phase needs a fresh `rst_n` pulse with MODE high.

**The load can be checked before anything runs**
(`spec/decision-records/0013-program-loading.md` layer 1, Proposed). For
as long as the design is in load phase, `uo_out` shows the running
`PM_CRC` of the words committed so far: its low byte while `ui_in[1]` is 0
and its high byte while `ui_in[1]` is 1. The host compares the two bytes
with its own CRC-16/XMODEM of the image and drops MODE only if they match;
the procedure is under "How to run a protocol". From the edge that takes
MODE low onward, `uo_out` is the program's port again and `ui_in[1]` is an
ordinary input. The readout changes nothing else about loading: the same
pins, the same edges, and a host that ignores `uo_out` loads exactly as
before. The remaining pins (`ui_in[6:2]`, `uio`) are untouched by loading.

**With MODE low at reset the core does not run program memory. It runs a
boot ROM** (`spec/decision-records/0013-program-loading.md` layer 2,
Proposed). After a power-up or a reselect the SRAM holds nothing a host put
there, so the core fetches from a small on-chip ROM instead. The ROM is
synthesized logic, 232 words (DR 0013 proposed a cap of 128; the UART
load alone is 138 words and does not fit it, finding F4, so the cap is the
256-word fetch address space until the record decides), and its contents
are a program in this same instruction set
([`firmware/asm/boot/boot_rom.asm`](../firmware/asm/boot/boot_rom.asm));
`rtl/protocol_boot_rom.v` is generated from the committed image. The boot
program's first instruction reads two straps on `ui_in[6:5]`:

| `ui_in[6:5]` | Boot program | Today |
|---|---|---|
| `00` | UART load | implemented (issue #139) |
| `01` | SPI-flash boot: read 512 bytes from a QSPI Pmod flash, check, run | implemented |
| `10` | warm start: run the image already in program memory if it checks | implemented |
| `11` | reserved, behaves as `00` | implemented, as `00` |

Neither boot program is a stub. The SPI-flash
boot makes `uio[0]` (CS0), `uio[1]` (MOSI) and `uio[3]` (SCK) outputs and
reads `uio[2]` (MISO): the Tiny Tapeout QSPI Pmod's pinout. It reads 512
bytes from flash address 0 with the single-bit `0x03` command (SPI mode 0),
writes them to program memory, checks word 255 against the CRC of words
0-254 exactly as the warm start does (and refuses a signature of
`0x0000`), then releases every pin and runs the image from address 0 after
58,793 cycles, or halts with every pin an input. How to put an image on the
flash: [spi-flash-boot.md](spi-flash-boot.md). 

**UART load (strap `00`).** The demo board's USB-UART bridge, Tiny Tapeout
"option B": RX `ui_in[1]`, TX `uo_out[0]`, 8N1, 434 core cycles per bit (115,200
baud if the core clock is the 50 MHz of target-spec row 4, which is unconfirmed;
the cycle count is the claim). Send `0xA5`, `N-1` (N is 1 to 256), the
count's complement `~(N-1)` (that is, `0xFF - (N-1)`), `2N` image bytes with
the high byte of each word first, then the CRC-16/XMODEM of the image bytes
(high byte first; the CRC does not cover the first three bytes). The chip
checks the complement first: if it does not match it answers `0x15 00 00` at
once, while you are still sending, writes nothing, and waits for the next
`0xA5`, so read the reply as it arrives and, on `0x15`, finish or abandon the
frame and pulse `rst_n` before resending. Otherwise the chip writes the
words, checks its CRC against yours, and answers `0x06` plus its CRC (high
byte first) and runs the image from address 0, or answers `0x15` plus its CRC
and waits for the next `0xA5`. It never runs an image that failed. `python3 firmware/tools/loadseq.py IMAGE.hex --uart -o
FRAME` writes the frame. TX idles high from the first instruction of the
loader; no `uio` pin is driven, though `uio_out` reads `0xFF` while the loader
waits (it uses `UIO_DIR` as storage under a guard, DR 0013 finding F5). A
loader that has lost sync (a wrong length) reads stray bytes as a frame
whenever one is `0xA5`: pulse `rst_n`, or send non-zero filler until it answers
`0x15` (zero filler is read as a valid, longer image). A corrupted count
byte, or a corrupted complement, is rejected before anything is written
(every single-bit flip of either is in the RTL regression; DR 0013 finding
F8, resolved by issue #211). Not ruled out: a corruption that changes the
count and its complement consistently (at least two bit errors placed to
match) and also makes the CRC of the shorter or longer stream match. The loaded program starts
in the state a warm start leaves, with `PM_CRC` holding the image's CRC. In RTL
simulation the loader accepted hosts up to 5 % slow and 4 % fast
(`verification/records/boot-uart/`). 

The warm
start is for an `rst_n` pulse while the design stays selected. It runs
program memory from address 0 only if word 255 equals the CRC-16/XMODEM of
words 0–254 (high byte of each word first); otherwise it falls through to
the UART load. A passing warm start executes the image's first
instruction exactly 2,325 cycles after the boot program's own first
instruction, with `R0`–`R3`, `Z` and `C` at their reset values and
`BOOT_STATUS` reading `0x00`. Like the SPI-flash boot, the warm start
refuses a signature of `0x0000`: 256 zero words are their own valid CRC,
so an SRAM that powered up all-zero would otherwise pass (DR 0013, Finding
F1, closed by issue #168). The cost is the image whose real CRC is
`0x0000`, about 1 in 65,536: change one filler word and re-sign it, as
`firmware/tools/mkflash.py` already requires. Hold the straps steady for at least three
clocks after `rst_n` is released; the boot program samples them once.
Only a `WCTL RUN` leaves the ROM, and nothing re-enters it without a reset.

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
  MODE-high reprogram attempt does nothing. A second case exercises the
  control space from the pins: register reset values and readback, the
  `uio_oe` pin modes, a program written into memory by firmware and then
  run, and `PM_CRC` against Python's `binascii.crc_hqx`. A third exercises
  the boot ROM: MODE low with straps `00` leaves no `uio` pin driven and TX idle high, a signed image
  warm-starts on the predicted edge, and the same image with one flipped
  bit is never run. A fourth performs the load check described under "How
  to run a protocol": it reads the CRC from `uo_out` before dropping MODE,
  for a good load and for a load one clock edge short.
- `verification/test_protocol_emulator.py` — this program's own klt-driven
  bench (`klt functional-verification`), which exercises all 16 opcodes as
  loaded firmware and asserts each result on a *numbered* clock edge derived
  from the ISA's own cycle table, so a timing regression fails rather than
  merely shifting. See `verification/README.md`; the append-only evidence
  record is `verification/records/core-datapath/`.

## Protocols as firmware

Every program committed under [`firmware/asm/`](../firmware/asm), with its
committed image in [`firmware/build/`](../firmware/build). There is no
protocol hardware: each row is a program for the core above.

**What the numbers are.** *Words* and *Total cycles* are the DR 0003
assembler's static count over the instruction stream (the committed
`<image>.cycles.txt`; valid because every instruction's latency is fixed).
*Rate* is the cycle budget the bench **measured at the pin** against an
independent reference model, in **RTL simulation (Icarus 13.0 driven by
`klt functional-verification` — the klt flow)**. The cycle count is the
claim; any baud/MHz reading is arithmetic at target-spec row 4's 50 MHz
clock, which is **unconfirmed on the klt flow** (`klt sta` produced 0 of 6
corners, [record](../verification/records/sta-corner-sweep/records/20261010-205317-af36071.md)),
so no wall-clock rate is claimed here. Nothing in this table was run on
the Tiny Tapeout LibreLane flow or on silicon (see the
"Evidence not yet in hand" section below).

The table is mechanically checked against `firmware/asm/`,
`firmware/build/` and the cited paths by `scripts/check_datasheet.py`
(run in CI); a program added or removed without a row here fails the build.

<!-- firmware-images:begin -->
| Image | Protocol and mode | Rate (cycles, klt-flow RTL sim) | Words | Total cycles | Bench | Record |
|---|---|---|---|---|---|---|
| [`uart_tx`](../firmware/asm/uart_tx.asm) | UART TX, 8N1, frames 0x5A then 0xA5 | 50 per bit | 34 | 979 | [`test_firmware_uart.py`](../verification/test_firmware_uart.py) | [firmware-uart 20261010-202833-bce5bf4](../verification/records/firmware-uart/records/20261010-202833-bce5bf4.md) |
| [`uart_rx`](../firmware/asm/uart_rx.asm) | UART RX, 8N1 | 50 per bit | 132 | 488 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261010-202835-bce5bf4](../verification/records/firmware-uart-rx/records/20261010-202835-bce5bf4.md) |
| [`uart_rx_115200`](../firmware/asm/uart_rx_115200.asm) | UART RX, 8N1, 115200-baud class | 434 per bit | 168 | 3878 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261010-202835-bce5bf4](../verification/records/firmware-uart-rx/records/20261010-202835-bce5bf4.md) |
| [`uart_rx_9600`](../firmware/asm/uart_rx_9600.asm) | UART RX, 8N1, 9600-baud class (nested `WAIT`) | 5208 per bit | 168 | 2791 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261010-202835-bce5bf4](../verification/records/firmware-uart-rx/records/20261010-202835-bce5bf4.md) |
| [`uart_tx_115200`](../firmware/asm/uart_tx_115200.asm) | UART TX, 8N1, 115,200-class (one outer pass + `WAIT`), frames 0x5A then 0xA5 | 434 per bit | 177 | 8882 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261012-054843-243b6a4](../verification/records/firmware-uart-rx/records/20261012-054843-243b6a4.md) |
| [`uart_tx_9600`](../firmware/asm/uart_tx_9600.asm) | UART TX, 8N1, 9600-baud class (nested `WAIT`), frames 0x5A then 0xA5 | 5208 per bit | 177 | 6578 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261010-202835-bce5bf4](../verification/records/firmware-uart-rx/records/20261010-202835-bce5bf4.md) |
| [`spi_mode0`](../firmware/asm/spi_mode0.asm) | SPI controller, CPOL 0 / CPHA 0 | 4 per SCLK period (ceiling burst), 10 per bit (functional burst) | 137 | 197 | [`test_firmware_spi.py`](../verification/test_firmware_spi.py) | [firmware-spi 20261011-012805-428e12f](../verification/records/firmware-spi/records/20261011-012805-428e12f.md) |
| [`spi_mode1`](../firmware/asm/spi_mode1.asm) | SPI controller, CPOL 0 / CPHA 1 | 4 per SCLK period (ceiling burst), 10 per bit (functional burst) | 138 | 198 | [`test_firmware_spi.py`](../verification/test_firmware_spi.py) | [firmware-spi 20261011-012805-428e12f](../verification/records/firmware-spi/records/20261011-012805-428e12f.md) |
| [`spi_mode2`](../firmware/asm/spi_mode2.asm) | SPI controller, CPOL 1 / CPHA 0 | 4 per SCLK period (ceiling burst), 10 per bit (functional burst) | 137 | 197 | [`test_firmware_spi.py`](../verification/test_firmware_spi.py) | [firmware-spi 20261011-012805-428e12f](../verification/records/firmware-spi/records/20261011-012805-428e12f.md) |
| [`spi_mode3`](../firmware/asm/spi_mode3.asm) | SPI controller, CPOL 1 / CPHA 1 | 4 per SCLK period (ceiling burst), 10 per bit (functional burst) | 138 | 198 | [`test_firmware_spi.py`](../verification/test_firmware_spi.py) | [firmware-spi 20261011-012805-428e12f](../verification/records/firmware-spi/records/20261011-012805-428e12f.md) |
| [`i2c_fast`](../firmware/asm/i2c_fast.asm) | I2C controller, Fast-mode budget, write only | 125 per SCL clock (low 65 + high 60) | 245 | 3350 | [`test_firmware_i2c.py`](../verification/test_firmware_i2c.py), [`test_firmware_i2c_ack.py`](../verification/test_firmware_i2c_ack.py) | [firmware-i2c 20261011-160445-156b58f](../verification/records/firmware-i2c/records/20261011-160445-156b58f.md) |
| [`i2c_std`](../firmware/asm/i2c_std.asm) | I2C controller, Standard-mode budget, write only | 500 per SCL clock (low 258 + high 242) | 245 | 10916 | [`test_firmware_i2c.py`](../verification/test_firmware_i2c.py), [`test_firmware_i2c_ack.py`](../verification/test_firmware_i2c_ack.py) | [firmware-i2c 20261011-160445-156b58f](../verification/records/firmware-i2c/records/20261011-160445-156b58f.md) |
| [`i2c_fast_sr`](../firmware/asm/i2c_fast_sr.asm) | I2C controller, Fast-mode budget, write + repeated START + read, no pin-dependent branch | 125 per SCL clock (low 70 + high 55) | 152 | 1879 | [`test_firmware_i2c_sr.py`](../verification/test_firmware_i2c_sr.py) | [firmware-i2c 20261011-230705-66d2731](../verification/records/firmware-i2c/records/20261011-230705-66d2731.md) |
| [`i2c_fast_sr_poll`](../firmware/asm/i2c_fast_sr_poll.asm) | as `i2c_fast_sr`, polls SCL (tolerates clock stretching) | 127 per SCL clock unstretched (low 70 + high 57) | 192 | 1899 | [`test_firmware_i2c_sr.py`](../verification/test_firmware_i2c_sr.py) | [firmware-i2c 20261011-230705-66d2731](../verification/records/firmware-i2c/records/20261011-230705-66d2731.md) |
| [`i2c_std_sr`](../firmware/asm/i2c_std_sr.asm) | I2C controller, Standard-mode budget, write + repeated START + read, no pin-dependent branch | 500 per SCL clock (low 258 + high 242) | 152 | 5885 | [`test_firmware_i2c_sr.py`](../verification/test_firmware_i2c_sr.py) | [firmware-i2c 20261011-012759-428e12f](../verification/records/firmware-i2c/records/20261011-012759-428e12f.md) |
| [`i2c_std_sr_poll`](../firmware/asm/i2c_std_sr_poll.asm) | as `i2c_std_sr`, polls SCL (tolerates clock stretching) | 502 per SCL clock unstretched (low 258 + high 244) | 192 | 5905 | [`test_firmware_i2c_sr.py`](../verification/test_firmware_i2c_sr.py) | [firmware-i2c 20261011-012759-428e12f](../verification/records/firmware-i2c/records/20261011-012759-428e12f.md) |
| [`ws2812`](../firmware/asm/ws2812.asm) | WS2812 / WS2812B LED data on `uo_out[7]`, GRB pixels from a table in program memory (target-spec row 13) | 63 per bit (T0H 20, T1H 40); reset 15,499 or more | 60 | 377 | [`test_firmware_ws2812.py`](../verification/test_firmware_ws2812.py) | [firmware-ws2812 20261010-233344-21acbc8](../verification/records/firmware-ws2812/records/20261010-233344-21acbc8.md) |
| [`ps2_device`](../firmware/asm/ps2_device.asm) | PS/2 keyboard/mouse device on `uio[2]` (CLK) and `uio[3]` (DATA), open-drain: sends 0xAA, ACKs and echoes host bytes, abandons a frame the host inhibits (target-spec row 13, stretch column) | clock low about 2,006 and high about 2,035..2,083 cycles; 50 us hold-off about 4,016 | 213 | 951 | [`test_firmware_ps2.py`](../verification/test_firmware_ps2.py) | [firmware-ps2 20261011-054024-1623ac4](../verification/records/firmware-ps2/records/20261011-054024-1623ac4.md) |
| [`demo_roundtrip`](../firmware/asm/demo_roundtrip.asm) | none (assembler and load-phase round-trip coverage program) | n/a | 27 | 30 | [`test_firmware_roundtrip.py`](../verification/test_firmware_roundtrip.py) | [firmware-assembler-roundtrip 20261010-172335-f8428aa](../verification/records/firmware-assembler-roundtrip/records/20261010-172335-f8428aa.md) |
<!-- firmware-images:end -->

Notes, all from the cited records:

- UART: bit period exactly 50 cycles, 0.000 % drift against the 2 % bound
  (target-spec row 10), measured at the pin.
- SPI: SCLK period exactly 4 cycles on the ceiling burst in all four modes;
  both data streams decoded byte-exact by the independent model. Mode 1/3
  are one word longer than mode 0/2.
- I2C: every UM10204 Table 10 minimum is met in exact cycles by the
  reference model, `t_SU;STA` included (`_sr`: 30 cycles Fast, 235
  Standard); the `_sr` transfer decodes `data=[0x5a, 0xa1, 0xb4]`,
  `acks=[True, True, True, False]` and publishes `0xB4` on `uo_out`. The
  `_poll` rise phases are budget + 2 cycles by construction. Since issue
  #125 the reference model also bounds every data/ACK clock's complete
  period by Table 10's f_SCL maximum (10000 ns Standard, 2500 ns Fast at the
  nominal 20 ns clock), and the Standard programs pace 500-cycle clocks
  (they were 435 cycles, ~114.9 kHz at the nominal clock, until then);
  the kHz figures are arithmetic at the unconfirmed clock. The only
  data-dependent branches are the sanctioned ACK/poll handshakes, which the
  assembler reports as warnings (1 per write-only image, 10 per `_poll`
  image).
- The SPI images set `UIO_DIR` to `0x0B` (CS, MOSI and SCLK push-pull)
  right after writing their idle image; the I2C images set `UIO_OD` to
  `0x0C` (SCL and SDA open-drain) right after releasing both lines. The
  SPI and I2C benches run on a pad model
  ([`uio_pads.py`](../verification/uio_pads.py),
  [record](../verification/records/uio-pad-model/records/20261011-012813-428e12f.md))
  that resolves each line from the design's `uio_oe` and `uio_out`, a
  pull-up and the peripheral, and reads it back on `uio_in`; the lines the
  reference model grades are those. With `UIO_OD` left at reset the I2C
  images put no transfer on the bus, and the benches require that. See
  Pins.
- WS2812 (target-spec row 13; *dated note 2026-10-10, issue #141 part 2*):
  `ws2812` was written **after** the ISA was frozen (DR 0017, freeze merge
  `1696045b`; the protocol was chosen by DR 0018 in a commit of its own,
  before any WS2812 file existed), and no ISA-defining file changed to build
  it (it added no freeze amendment; the one on `main`, #234's DR 0013 note,
  is a `no-behaviour-change` that does not invalidate row-13 evidence). An independent WS2812B
  model measured every pulse on `uo_out[7]`: T0H 20, T1H 40, T0L 43 and T1L
  23 cycles, 63 per bit (400 / 800 / 860 / 460 / 1260 ns at the 20 ns
  target), each at least 140 ns inside its datasheet window, and a reset of
  at least 15,499 cycles. It decoded the loaded GRB frame, the committed 8
  pixels and seeded 1- to 73-pixel frames, at RTL and on the LibreLane
  netlist, zero-delay ([gate-level record](../verification/records/firmware-ws2812-gate-level/records/20261010-233534-21acbc8.md)). Three mutant programs (a
  short T1H, a dropped bit, a short reset) are rejected. This is primary-column
  evidence only, and row 13 stays Proposed and unmet. The stretch column (a
  role or pin direction the core protocols never use) is not done: issue #235.
  The write-up is [`submission/row13-ws2812.md`](submission/row13-ws2812.md).
- PS/2 device (target-spec row 13, **stretch column**; *dated note 2026-10-11,
  issue #235*): `ps2_device` plays a PS/2 keyboard/mouse device on `uio[2]`
  (CLK) and `uio[3]` (DATA), both open-drain with pull-ups, and a host drives
  the same two lines. It was written **after** the ISA was frozen (DR 0017,
  freeze merge `1696045b`; the protocol was chosen by a dated note in DR 0018
  in a commit of its own, before any PS/2 file existed), and no ISA-defining
  file changed to build it (`scripts/check_isa_freeze.py`: 2 amendments, the
  same as before). It does what the core protocols never do: it generates a
  clock on a line the host may hold low (it abandons a frame the host
  inhibits, releases DATA and sends the frame again after 50 µs of CLK high),
  it turns DATA around for the ACK of a host-to-device byte, and it reads a
  line the host drives on a clock it generates. An independent host model
  written from Chapweske's description graded every edge on the pads, at RTL
  ([record](../verification/records/firmware-ps2/records/20261011-054024-1623ac4.md)) and on the LibreLane netlist, zero-delay
  ([gate-level record](../verification/records/firmware-ps2-gate-level/records/20261011-061202-f90bef2.md)): CLK low 40.12 to 40.14 µs and CLK high 40.70
  to 41.66 µs (limits 30 to 50), data change 20.34 µs before the falling edge
  (5 to 25), hold-off 80.2 µs or more (50), all at the 20 ns target clock.
  Eight negative controls (no inhibit check, a short hold-off, no ACK, late
  and early data, even parity, push-pull pads, an unchecked host parity) are
  rejected. Only the timing on the two lines is graded; the keyboard and mouse
  command sets are not implemented, and the model does not cover a host that
  never releases DATA after the ACK. This is stretch-column evidence only:
  row 13 stays Proposed and unmet. The pins are the standard I2C Pmod row, so
  an I2C-wired board needs no jumper; the pad model has zero delay and ideal
  pull-ups, so no pull-up rise time is claimed.

## How to run a protocol

Prerequisites for the Python-only steps: Python 3 (>= 3.9), nothing else.
The simulation steps need `klt` at the `layout/toolchain.json` pin plus
Icarus, provisioned by `./scripts/setup-env.sh` (see
[`verification/README.md`](../verification/README.md)).

1. **Check the images are the ones built from source** (Python only):
   `python3 firmware/tools/check_firmware.py`. To rebuild one:
   `python3 firmware/tools/asm.py firmware/asm/uart_tx.asm`.
2. **The loader.** In simulation the benches load an image with their own
   cocotb coroutines: `load_program(dut, words)` in
   [`verification/test_protocol_emulator.py`](../verification/test_protocol_emulator.py)
   (the top-level reference; `test/test.py` has the same sequence) and
   `reset_release`/`load_words` in
   [`verification/test_firmware_roundtrip.py`](../verification/test_firmware_roundtrip.py)
   (module level); `_dut.py` has only `reset()`. Images are one 4-hex-digit
   word per line of `firmware/build/<image>.hex`. The load-phase protocol,
   for anyone wiring their own driver:
   - set `ui_in[7]` (MODE) high, `ui_in[0]` low; pulse `rst_n` low for
     10 clocks and release it;
   - clock one edge with MODE still high (the edge that latches MODE);
   - for each word in file order, for bit 15 down to 0, put the bit on
     `ui_in[0]` (keeping `ui_in[7]` high) and clock once;
   - **check the load** (optional, and the reason to do it is below). With
     `ui_in[7]` still high: set `ui_in[1]` low and read `uo_out`, the CRC's
     low byte; set `ui_in[1]` high and read `uo_out`, the high byte. No
     clock edge is needed between the two reads, since `ui_in[1]` selects
     the byte directly. Compare with the CRC-16/XMODEM of the image as
     big-endian bytes, word 0 first (polynomial `0x1021`, initial value 0,
     no reflection, no final XOR; in Python,
     `binascii.crc_hqx(image_bytes, 0)`). **On a mismatch, do not drop
     MODE:** pulse `rst_n` with MODE high and load again. Reset clears the
     CRC;
   - drop `ui_in[7]` to enter run phase, on its own edge. The first
     instruction retires two edges later (fetch-ahead, DR 0005); execution
     then follows the cycle report exactly.

   Reading the CRC with the clock stopped is simplest, and this load path
   already needs a host that drives `clk`. A host that cannot stop the
   clock has 15 edges after the last bit in which the readout is stable
   (the CRC moves only on the edge that commits a word); whatever is on
   `ui_in[0]` during those edges is a partial word, discarded when MODE
   drops. A 16th edge would commit one more word and change the CRC.

   What the check catches: a load that stopped early, and a clock edge the
   chip missed or saw twice, because either one shifts or shortens what
   was committed. `verification/test_load_integrity.py` tries every
   single-edge fault position of a 4-word image and seeded positions in
   16- to 256-word images. What it cannot promise: the CRC is 16 bits, so
   about one corrupted load in 65,536 reads as good; and because it starts
   from 0, an image that is all zero words reads `0x0000` at any length.
   One doubled edge is correctly reported as a match: a repeat of the last
   bit of the image (or of any bit in a run of equal bits reaching the end
   of the image) leaves every word intact, and the spare bit is discarded.

   While the load is in progress `uo_out` carries CRC bytes, not its reset
   value 0. Target-spec row 14(b) excepts the serial-load phase for exactly
   this (amended 2026-10-10 by the operator's ruling on issue #166).
   Anything wired to `uo_out` sees those bytes change every 16 clocks until
   MODE drops, at which point `uo_out` returns to 0 until the program's
   first `OUT`, so a peripheral on `uo_out` (a UART peer on `uo_out[0]`,
   for one) must tolerate them or be held off during a load. The boot ROM's
   paths (MODE low at reset) never show the readout.

   **Host-side generator (no simulator).**
   [`firmware/tools/loadseq.py`](../firmware/tools/loadseq.py) turns an image
   into exactly that pin sequence, stdlib Python only:

   ```
   python3 firmware/tools/loadseq.py firmware/build/uart_tx.hex                    # JSON
   python3 firmware/tools/loadseq.py firmware/build/uart_tx.hex --format python    # VERSION/WORDS/STEPS
   ```

   Format version 1, one step per clock cycle, `(ui_in, uio_in, rst_n, ena)`
   held while `clk` is low: 10 steps with MODE high and `rst_n` low, one
   MODE-latching step (`rst_n` high, no bit), 16 steps per word (MSB first,
   `ui_in = 0x80 | bit`), one MODE-drop step (`ui_in = 0`); `uio_in = 0`,
   `ena = 1` throughout, 12 + 16N steps, never padded. The input must hold
   1..256 words; blank lines are skipped and anything else that is not
   exactly four hex digits, an empty file, or more than 256 words is
   rejected (exit status 2, nothing emitted).
   [`firmware/tools/loadseq_playback.py`](../firmware/tools/loadseq_playback.py)
   (MicroPython-compatible, imports nothing) plays the steps on a board
   adapter with `set_ui_in`, `set_uio_in`, `set_rst_n`, `set_ena`,
   `set_clk` and `wait_us`; each step sets the inputs with `clk` low, waits
   `setup_us`, raises `clk`, waits `high_us`, lowers it, waits `low_us`
   (all configurable and positive). The adapter's owner must stop the
   board's automatic clock before playback and keep manual clock control
   through the MODE-drop step. After a re-select, replay the whole sequence
   (SRAM contents are not assumed to survive). `MockAdapter` shows the
   contract; no board binding ships.
   Evidence, RTL simulation only (Icarus 13.0 via `klt
   functional-verification`): `verification/request-loadseq.json` replays
   the generated operations (independently of the cocotb loaders above) on
   `protocol_program_memory` and reads every word of all 16 committed
   application images, a 1-word image, the 256-word boundary and a reload
   back through the fetch port; `verification/request-loadseq-top.json`
   checks the MODE/run transition on the submitted top. Also
   `python3 firmware/tools/test_loadseq.py`; `check_firmware.py` regenerates
   each application image's sequence in memory and replays it through an
   independent model of the load protocol.
3. **Run and grade a protocol in simulation** (klt flow). Each request
   loads the committed image through step 2's sequence and grades the pins
   against the independent reference model:
   - UART: `klt functional-verification verification/request-firmware-uart.json --format json`
   - SPI, all four modes: `klt functional-verification verification/request-firmware-spi.json --format json`
   - SPI, three bytes under one CS (mode 0): `klt functional-verification verification/request-firmware-spi-burst.json --format json`
   - I2C write, Fast and Standard: `klt functional-verification verification/request-firmware-i2c.json --format json`
   - I2C write/repeated-START/read and clock stretch: `klt functional-verification verification/request-firmware-i2c-sr.json --format json`
   - Assembler/load round trip: `klt functional-verification verification/request-firmware-roundtrip.json --format json`
4. **What to expect on the wire** (as graded by the records above):
   - UART: `uo_out[0]` idles high, then a start bit, 8 data bits LSB first
     and a stop bit, 50 cycles each, for 0x5A then 0xA5.
   - SPI: `uio[0]` CS falls, `uio[3]` SCLK idles at CPOL and toggles
     with a 4-cycle period carrying MOSI byte 0xA5 on `uio[1]`, then a
     10-cycle-per-bit burst carrying 0x3C; MISO is read from `uio[2]`;
     after CS releases the assembled received byte is echoed on `uo_out`.
   - I2C: START, address 0xA0 and ACK, data 0x5A and ACK, STOP (write-only
     images); the `_sr` images add repeated START, 0xA1, one read byte and
     a controller NACK, and publish the received byte on `uo_out`.

Not in this recipe: playback of the generated sequence on a physical chip
has not been demonstrated. `loadseq.py` produces and simulation-verifies the
pin sequence, but no board adapter ships and no silicon exists to run it on.

## Pins (PROVISIONAL)

**Status: provisional.** The pin-role decision record is still open
([issue #94](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/issues/94));
target-spec row 5 fixes only the template's pin *budget*, not roles. This
section documents what the committed firmware **observably uses** and the
RTL's current limitation. It is not a ratified pin plan, and the roles
below are the firmware's own choices, not proposals that anyone has
admitted. It will change when #94 and DR 0008 land.

Fixed by the RTL (`src/tt_um_2amlogic_protocol_emulator.v`), not provisional:

| Pin | Role |
|---|---|
| `ui_in[7]` | MODE: high across `rst_n` release selects load phase; low runs the boot ROM |
| `ui_in[6:5]` | straps, read once by the boot ROM's program when MODE is low at reset (`00`/`11` UART load, `01` SPI-flash boot, `10` warm start). The read is an ordinary `IN`, not strap hardware; a loaded program sees these as plain input bits |
| `ui_in[0]` | serial program data in load phase, MSB first (no run-phase role; UART RX is `ui_in[1]`) |
| `ui_in[1]` | serial-load phase (MODE high at reset, until it drops): selects which `PM_CRC` byte `uo_out` shows (0 = low, 1 = high). Otherwise an ordinary input read by `IN`; the boot ROM's UART load (strap `00`) uses it as RX |
| `uo_out[7:0]` | serial-load phase: the selected `PM_CRC` byte. Run phase (including the boot ROM, whose UART TX is `uo_out[0]`): written by `OUT`. 0 in reset |
| `uio_oe[7:0]` | set by firmware: `UIO_OD[n]` → open-drain (`uio_oe[n]` is the complement of the port-11 bit a program wrote with `OUT`), else `UIO_DIR[n]` → push-pull, else input. **0 after reset**: every bidirectional pin is an input until a program writes `UIO_DIR` or `UIO_OD` |
| `uio_out[7:0]` | the pad data: the port-11 register written by `OUT`, except on an open-drain pin, where it is tied to 0 so the pad can only pull low or release ([DR 0020](../spec/decision-records/0020-open-drain-pad-data-tied-low.md)). Reaches a pin only where `uio_oe` enables it |

Observed in committed firmware (provisional, per image family):

| Family | Signal | Pin | Reaches a pin in the current RTL? |
|---|---|---|---|
| UART | TX | `uo_out[0]` | yes (dedicated output) |
| SPI | CS (active low) | `uio[0]` | yes in RTL, push-pull (`UIO_DIR` = `0x0B`); verified through a logical pad model at RTL and on the gate-level netlist, zero delay |
| SPI | MOSI | `uio[1]` | as CS |
| SPI | MISO | `uio[2]` (`uio_in[2]`) | yes (input) |
| SPI | SCLK (Pmod SCK) | `uio[3]` | as CS |
| SPI, I2C `_sr` | result byte echo | `uo_out[7:0]` after the transfer | yes |
| I2C | SCL (1 = released) | `uio[2]` (port 11 bit 2) | yes in RTL, open-drain (`UIO_OD` = `0x0C`; the pad data is tied to 0 and `uio_oe` carries the bit, DR 0020); verified through a logical pad model at RTL, on the gate-level netlist at zero delay, and on the routed netlist with SDF delays (the repeated-START programs) |
| I2C | SDA (1 = released) | `uio[3]` (`uio_out[3]`) | as SCL |
| I2C | SCL / SDA sampled | `uio_in[2]` / `uio_in[3]` | yes (input) |

SPI and I2C are on the upper `uio` row as Tiny Tapeout's standard SPI and
I2C Pmods wire it (DR 0010's target plan, moved by issue #155). The two
rows overlap on `uio[2]` and `uio[3]`; one image, so one protocol, is loaded
per run, and each image sets its own pin modes.

Consequences, stated rather than papered over: the UART output is on a
dedicated output and needs no `uio_oe`. The SPI outputs are written to
`uio_out` and reach the pins as push-pull once the image's `WCTL UIO_DIR`
has run; the I2C outputs reach them as open-drain once the image's `WCTL
UIO_OD` has run, and an I2C bus needs external pull-ups, which this design
does not provide. What is verified today is the `uio_oe` logic
(`verification/test_control_space.py`) and, for the SPI and I2C images,
the lines that logic produces on a pad model: the benches resolve each
line from `uio_oe`/`uio_out`, the board's pulls and the peripheral, and
grade those lines (records above). That model is logical and zero-delay;
it is not a pad cell, and says nothing about rise time or drive strength.
No pin claim here is backed by silicon or by the LibreLane flow.

## Evidence not yet in hand

- **Tiny Tapeout LibreLane flow.** The routed-netlist SDF regression of the
  submitted core ([record](../verification/records/post-layout-sdf-regression/records/20261011-114800-e5a0bae.md),
  LibreLane run 38136727636, with DR 0015's P1 and P2, the UART-load boot ROM with its count-complement check, the load check's readout and DR 0020's open-drain pad data) passes at all three corners: 12 of the core
  bench's 13 tests pass and the white-box flag test is skipped (it reads
  core internals a flattened netlist does not have), so the C flag has no
  post-layout evidence. One of the 12 grades the load check's readout every
  cycle of a serial load: `uo_out` shows the `PM_CRC` byte `ui_in[1]`
  selects, and 0 in reset and after the MODE drop. The bench runs at the flow's own constraint: a
  20 ns clock, inputs changed 4 ns after each edge, outputs read 4 ns
  before the next. The SRAM runs as a zero-delay model there (its read
  timing is LibreLane STA evidence only), setup/hold is checked only
  against the cell models' 0 ns placeholder limits, not the SDF's
  characterised ones.
  Three firmware benches also run there with delays (same record): UART TX,
  SPI modes 0-3 and the I2C write / repeated-START / read / clock-stretch
  programs pass at all three corners, with every output transition measured
  0.5 to 1.6 ns after the clock pin edge. On the I2C run the open-drain pads
  only ever pull low. On the netlist before DR 0020 the same run fails at
  every corner: `uio_out` reached the pins 50 to 210 ps before `uio_oe` and
  the pads drove SCL and SDA high for that window on each release (issue
  #244). The boot programs, UART RX, PS/2 and WS2812 have not been run with
  delays, and no pad cell is in the simulation. The sign-off grader
  still renders T1 item 7 unmet, on provenance binding (see
  `manifests/README.md`). LibreLane timing and area evidence is in
  [`librelane-corner-timing`](../verification/records/librelane-corner-timing/records/20261011-144900-e5a0bae.md):
  zero setup, hold, max-slew and max-capacitance violations at all three corners at 20 ns, with the
  worst setup slack +5.8 ns at the slow corner (the binding path is an SRAM read into instruction
  decode) and the worst hold slack +0.08 ns at the fast corner. Before issue #246 the slow-corner
  margin was +1.9 ns with two max-slew violations on one internal net (+3.5 ns before the 232-word
  boot ROM of issue #211). Five LibreLane repair settings in `src/config.json` account for most of
  the change and a placement re-roll for the rest; the record's trial table separates the two. One
  class is not repaired: on the pre-#244 design the same settings left max-capacitance violations
  on two SRAM output pins, and the shipped design has none by placement, not by construction.
  The placed standard-cell area with P1, P2, the UART-load ROM, the load check's readout and the
  timing repair is 46,048 µm² (LibreLane flow), 58.5 %
  of the core with the macro against the 60 % target (44,965 µm², 57.7 %, before the timing repair; 45,057 µm² with the 223-word ROM; 44,295 µm², 57.2 %, without the readout; P1 and P2 alone, before the merge with the UART load: 41,827 µm²,
  55.2 %; 28,256 µm² without them). On the klt/Yosys flow P1 and P2 cost +10,848 µm²
  (synthesis only). DR 0015 estimated about 4,600 µm² for the two primitives; the measured cost is
  2.4 to 2.9 times that, which DR 0015's dated notes record. The load check's readout costs 16
  two-input muxes, +290 µm² on the klt/Yosys flow (+486 µm² in LibreLane's own synthesis), and its
  `ui_in[1]`-to-`uo_out` path is 0.58 to 1.40 ns pin to pin in LibreLane's post-route analysis,
  under the flow's assumed 4 ns input and output delays; no pad has been measured.
  Firmware, the control-space, boot-ROM, SPI-flash-boot, UART-load, primitive and load-integrity benches on that netlist at zero delay:
  [`firmware-gate-level`](../verification/records/firmware-gate-level/records/20261012-072500-243b6a4.md).
  Firmware with back-annotated delays: UART TX, SPI and I2C repeated START, as above; nothing else.
- **klt synthesis and timing.** `klt sta` does not yet support the SRAM
  macro, so the two flows do not agree on timing; per the project rule that
  mismatch is a finding, not a number to pick from.
- **Silicon:** none.
- **Pads.** The I2C results are on a logical, zero-delay pad model
  ([record](../verification/records/uio-pad-model/records/20261011-012813-428e12f.md)):
  they show which lines the design drives, and when, through `uio_oe`.
  They are not electrical evidence: no pad cell, pull-up rise time, pad
  delay or drive strength has been simulated or measured.
- DR 0001, DR 0005 and DR 0012 are `Proposed`, not ratified.

## External hardware

The chip has digital pins only: 3.3 V I/O on the Tiny Tapeout demo board, no
analog pads. Anything else goes on a Pmod
([Pmods and demo board](https://tinytapeout.com/specs/pcb-etr/)).

**Required for I2C:**

- A pull-up resistor from each of `uio[2]` (SCL) and `uio[3]` (SDA) to 3.3 V.
  A standard Tiny Tapeout I2C Pmod carries them. The design releases an I2C
  line by tri-stating the pad, so the line reads high only with a pull-up.
  No pull-up is assumed to exist on the demo board itself.
  (The RTL drives these two pads open-drain once an I2C image has written
  `0x0C` to DR 0012's runtime `UIO_OD` register; see Pins above. That is
  verified through a logical pad model with a pull-up on each line, at
  RTL and on the gate-level netlist; without the pull-ups the model's
  lines float, as a real bus would.)

**Wiring today.** Tiny Tapeout's
[recommended pinouts](https://tinytapeout.com/specs/pinouts/) cover two
things: a UART bridged to USB by the demo board's MCU (option A: RX
`ui_in[3]`, TX `uo_out[4]`; option B: RX `ui_in[1]`, TX `uo_out[0]`), and
Pmods that put UART, SPI or I2C on one four-pin `uio` row. Against those:

- **UART transmit** is on `uo_out[0]`, which is option B's TX. It reaches the
  host over the board's USB bridge with no extra wiring.
- **UART receive** is on `ui_in[1]`, option B's RX (moved from `ui_in[0]` in
  #178). It reaches the host over the same USB bridge with no extra wiring.
  `ui_in[0]` is the program-load pin only; the receiver never reads it.
- **SPI** (CS `uio[0]`, MOSI `uio[1]`, MISO `uio[2]`, SCK `uio[3]`) and
  **I2C** (SCL `uio[2]`, SDA `uio[3]`) are on the upper `uio` row exactly as
  the standard SPI and I2C Pmods wire it. An unmodified Pmod plugs in; no
  wire adapter is needed.

All three protocols now follow the recommended pinouts (DR 0010, "Target pin
plan"): SPI and I2C moved in #155 and UART receive in #178.

**Required for the SPI-flash boot (strap `01`):** a Tiny Tapeout QSPI
flash/PSRAM Pmod in the bidirectional header, with an image written to its
flash ([spi-flash-boot.md](spi-flash-boot.md)). The boot drives only
`uio[0]`, `uio[1]` and `uio[3]`; the Pmod's pull-ups hold the two PSRAM chip
selects (`uio[6]`, `uio[7]`) deselected. Without it, strap `01` reads zeros or
ones, rejects them and halts.

**Not required:** UART and SPI at 3.3 V with 3.3 V peers need no extra parts
beyond that wiring.

**Levels and other buses.** A 5 V peer needs level shifting on a Pmod. A
differential bus (USB D+/D-, 10BASE-T) needs a transceiver on a Pmod; neither
is in the submitted design (not built; DR 0015 holds the proposed verdict and
DR 0011 the current-ISA baseline).

**Pad speed is unverified.** CMOS5L has no silicon yet and no pad
characterization; Tiny Tapeout is checking whether SG13G2-derived numbers
exist. Any claim of a maximum toggle rate at the pins, including the SPI SCLK
ceiling of f_clk/4 (12.5 MHz at 50 MHz), holds for the core's cycle timing
only, not at the pad.

### One device on the `uio` header at a time (decided in #196, 2026-10-09)

The QSPI flash/PSRAM Pmod uses the whole `uio` header: `uio[0]` CS0 (flash),
`uio[1]` SD0/MOSI, `uio[2]` SD1/MISO, `uio[3]` SCK, `uio[4]` SD2, `uio[5]`
SD3, `uio[6]` CS1 (RAM A), `uio[7]` CS2 (RAM B). The SPI Pmod (CS `uio[0]`,
MOSI `uio[1]`, MISO `uio[2]`, SCK `uio[3]`) and the I2C Pmod (SCL `uio[2]`,
SDA `uio[3]`) sit on the same four pins. The rule is therefore **one device
on the `uio` header at a time**. With the flash Pmod fitted (strap `01`),
after the boot hands over:

- A **user SPI program talks to the flash**, not to a separate peripheral.
- **No I2C peripheral can share the header.** An I2C program toggles the
  flash's MISO and SCK lines; CS0 is held high by the Pmod pull-up, so the
  flash should ignore them, but the bus is not usable.
- **UART** (`ui_in[1]`, `uo_out[0]`) is unaffected.
- **A user SPI program can ERASE OR OVERWRITE THE BOOT IMAGE.** A write
  enable (`0x06`) followed by an erase or program opcode in a later CS-low
  burst rewrites the flash, including address 0. The shipped `spi_mode0`
  sends `0xA5` and `0x3C`, one byte per burst; neither is a write enable, so
  the shipped images cannot arm a write (opcodes recalled, not re-read from
  the flash datasheet).

To use a different SPI device, **remove the flash Pmod after boot** (or boot
with strap `00`/`10` instead): the SPI profile's CS is `uio[0]`, the same pin
as the flash's CS0, so driving it low also selects the flash, and holding CS0
high does not help. Holding CS0 high (or leaving it on the Pmod pull-up)
isolates the flash only from a program that does not drive `uio[0]`, such as
I2C on `uio[2..3]`; the flash's MISO and SCK lines are still on those pins,
so the bus is loaded by the Pmod and is not verified as usable. The SPI and I2C Pmods also come in a bottom-row variant
on `uio[4..7]`; moving a profile there is a possible future option and is
not done here. See [spi-flash-boot.md](spi-flash-boot.md).
