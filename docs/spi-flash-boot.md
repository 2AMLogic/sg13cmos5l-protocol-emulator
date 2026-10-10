# Booting from the Tiny Tapeout QSPI Pmod flash (strap `01`)

This is the host-side guide for DR 0013's SPI-flash boot
([`spec/decision-records/0013-program-loading.md`](../spec/decision-records/0013-program-loading.md),
**Proposed**; issue #140). With a flash Pmod fitted and the straps set, a
reset is all it takes to load and run a program: no host drives `clk`, no
PC or microcontroller is in the loop. The boot program is ordinary firmware
([`firmware/asm/boot/boot_rom.asm`](../firmware/asm/boot/boot_rom.asm), label
`spi_boot`); nothing here is a hardware SPI block.

## What you need

- The Tiny Tapeout demo board with this design selected, and a
  [QSPI flash/PSRAM Pmod](https://github.com/mole99/qspi-pmod) in the
  **bidirectional (`uio`) Pmod header**. The Pmod's pins map to the design as
  `PMOD1` CS0 = `uio[0]`, `PMOD2` MOSI = `uio[1]`, `PMOD3` MISO = `uio[2]`,
  `PMOD4` SCK = `uio[3]` (the standard SPI Pmod pinout; the same table is in
  [Tiny Tapeout's pinouts](https://tinytapeout.com/specs/pinouts/)).
- The two input DIP switches that drive `ui_in[6:5]` set to **`01`**
  (`ui_in[5]` high, `ui_in[6]` low), and `ui_in[7]` (MODE) **low**. The boot
  program samples `ui_in[6:5]` once, on the third clock edge after `rst_n`
  is released, so hold them from before reset until after it.
- A flash image at address 0 (below).

Nothing else is driven. The program makes exactly `uio[0]`, `uio[1]` and
`uio[3]` outputs (`UIO_DIR = 0x0B`). `uio[2]` (MISO), `uio[4]`/`uio[5]`
(SD2/SD3) and `uio[6]`/`uio[7]` (the PSRAM chip selects) stay inputs.

### What the PSRAM chip selects do

Left as inputs they float to the Pmod's default, which is **deselected**
(high). The Pmod's schematic
([`qspi-pmod.kicad_sch`](https://github.com/mole99/qspi-pmod/blob/main/qspi-pmod.kicad_sch),
read 2026-10-10) has three 10 k resistors (`R1`-`R3`) from +3.3 V to the
`PMOD1`, `PMOD7` and `PMOD8` nets (`uio[0]`, `uio[6]`, `uio[7]`), and the
README says the same ("a 1k resistor pulls up the chip's /CS" after the
trace is cut; the schematic value is 10 k: the two disagree, and neither
was measured). Either way the default is high, so neither PSRAM is selected
while the flash is read, and no bus contention on MISO is possible. This
holds only if nothing else on the board drives those pins; whether the demo
board's microcontroller leaves its side of the `uio` header undriven in the
user's setup was not checked here. If a CS trace on the Pmod is cut, the
pull-up on the chip side still holds that chip off.

`uio[4]`/`uio[5]` have no pull-up on the Pmod. They are quad-mode data pins
of the flash and `0x03` (single-bit READ) does not use them, **provided the
flash's Quad Enable bit is set**, which is how the first-party Pmod ships.
With QE clear the flash's `/WP` and `/HOLD` use those pins, and a floating
`/HOLD` can stall the part. If a read returns nothing, set QE once with
Tiny Tapeout's "Configuring Quad SPI mode" script (see the guide linked
below).

## Make the image

The image is the program's words, **high byte first**, padded with `NOP`
words (`0x0000`) to word 254, then word 255 = the **CRC-16/XMODEM** of
words 0-254 (polynomial `0x1021`, initial value `0x0000`, no reflection, no
final XOR, high byte of each word first). That is the warm start's
signature format, so one image works for strap `01` and strap `10`.
`firmware/tools/mkflash.py` builds it from any committed `.hex`:

```bash
python3 firmware/tools/mkflash.py firmware/build/uart_tx.hex -o uart_tx.flash.bin
python3 firmware/tools/mkflash.py --check uart_tx.flash.bin     # ok (512 bytes, signature matches)
```

It refuses a program over 255 words, and a signature of `0x0000` (about 1
image in 65,536; add `--filler 0x1234` or change the program). The boot
program refuses a `0x0000` signature on purpose: a flash that answers `0x00`
to everything, or no Pmod at all with MISO pulled low, reads as 256 zero
words, which are their own valid CRC (DR 0013, Finding F1). The warm start
accepts that image because running 256 `NOP`s is harmless; the flash boot
treats it as a dead line.

The independent check of the format is Python's `binascii.crc_hqx`, used
by `mkflash.py` and by the cocotb bench alike: `binascii.crc_hqx(image, 0)
== 0` over the whole 512 bytes.

## Put the image on the flash

The flash is a Winbond W25Q128JV (16 MiB). The image goes at **address 0**;
nothing after byte 511 is read.

**With Tiny Tapeout's tooling** (what the QSPI Pmod ships with support for):
plug the Pmod into the demo board's bidirectional header, connect the board
to a PC and open the
[Tiny Tapeout Flasher](https://tinytapeout.com/guides/configure-flash-qspi-pmod/)
(Chromium-based browser; the page needs WebSerial). Connect, check that the
reported Flash ID is `ef7018`, choose "your own `.bin`", select
`uart_tx.flash.bin` and flash. The flasher is expected to write from address 0; confirm that on its page.
(This guide is Tiny Tapeout's; this repository has not run it.)

**With a generic SPI programmer** (a CH341A, a Raspberry Pi, a Bus Pirate,
any 3.3 V programmer): connect it to the flash (lift the Pmod from the demo
board so the design's pins do not fight the programmer; the design leaves
its pins as inputs outside a boot, but the chip is selected and may be
running). Pad the 512-byte image to the chip size and write it. For example,
with `flashrom` (chip name `W25Q128.V`; not run here, check `flashrom -L`
for your version):

```bash
{ cat uart_tx.flash.bin; head -c $((16*1024*1024 - 512)) /dev/zero | tr '\0' '\377'; } > full.bin
flashrom -p ch341a_spi -c W25Q128.V -w full.bin
flashrom -p ch341a_spi -c W25Q128.V -r readback.bin
head -c 512 readback.bin > readback512.bin
python3 firmware/tools/mkflash.py --check readback512.bin
```

Any tool that writes the 512 bytes to address 0 of the flash works; the
boot program only issues the standard `0x03` READ with a 24-bit address.

## Boot it

Set the switches (`ui_in[7]` low, `ui_in[6:5]` = `01`), then pulse `rst_n`.
After reset the program:

1. releases CS0 high, then makes CS0, MOSI and SCK outputs;
2. runs one SPI mode 0 transaction: CS0 low, command `0x03`, 24-bit address
   `0x000000`, 512 data bytes clocked out, SCK low, CS0 high;
3. writes each word to program memory with `PM_DATA_HI`/`PM_DATA_LO` (so
   `PM_CRC` runs over it) and checks that `PM_CRC` is `0x0000` and that the
   signature word is not `0x0000`;
4. makes every `uio` an input again (`UIO_DIR = 0`, `UIO_OUT = 0`);
5. on a pass restores `R0`-`R3`, `Z` and `C` to their reset values and
   executes `RUN 0`, so the image starts exactly as after a serial load,
   except that `BOOT_STATUS` reads `0x00`; on a fail it halts with every pin
   an input.

From its first instruction the boot program reaches the image's first
instruction after **58,793 core cycles** (measured by the bench, and
predicted by the ISA model); at the unconfirmed 50 MHz row-4 clock that is
1.18 ms. SCK runs at no more than f_clk/14 (3.6 MHz at 50 MHz).

**A failed boot looks like a design that does nothing**: `uo_out` stays
`0x00` and every `uio` is an input. To tell a failed boot from a missing
program, look at CS0 (`uio[0]`) with a logic analyser: a boot makes a single
low pulse of about 1.2 ms with 4,128 SCK rising edges in it. No pulse means
the straps are not `01` (or `MODE` is high); a pulse with no data means the
flash did not answer (no Pmod, QE clear, wrong address); a pulse followed by
nothing means the image failed its check, so re-make it with `mkflash.py`.

## What is verified, and what is not

- `verification/test_boot_spi.py` (RTL, Icarus + cocotb) boots images from an
  independent flash model that answers `0x03` and checks SPI mode 0 on every
  edge; see `verification/records/boot-spi/`. It covers a blank flash, no
  Pmod, corrupted images, a zero signature, the committed `uart_tx` and
  `spi_mode0` programs graded by their protocol reference models, and the
  rule that only `uio[0]`, `uio[1]` and `uio[3]` are ever driven.
- **An SPI program booted from this Pmod talks to the flash.** The shipped
  SPI profile uses the SPI Pmod pins (CS `uio[0]`, MOSI `uio[1]`, MISO
  `uio[2]`, SCLK `uio[3]`, DR 0010's target plan), and on the QSPI Pmod
  those are the flash's own CS0, MOSI, MISO and SCK. So once `spi_mode0`
  starts, its bursts select the flash, not a separate peripheral. The bench
  stops modelling the flash at the hand-over and grades the program's pins
  with its own peripheral in the flash's place. What a real flash does with
  those bursts is not modelled. An SPI application that needs both the
  flash and a peripheral needs a pin plan that keeps them apart.
- The flash model's timing limits are the W25Q128JV's as recalled by the
  author, not re-read from the datasheet (see
  `verification/reference_models/spi_flash.py`). Check them before relying
  on them.
- No real flash, Pmod, demo board or silicon has been involved. The pad
  model is logical and zero-delay.
