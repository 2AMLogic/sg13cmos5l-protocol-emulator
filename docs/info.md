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
admitted yet (see the "Pins (PROVISIONAL)" section below).

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
corners, [record](../verification/records/sta-corner-sweep/records/20260930-195410-ead870a.md)),
so no wall-clock rate is claimed here. Nothing in this table was run on
the Tiny Tapeout LibreLane flow or on silicon (see the
"Evidence not yet in hand" section below).

The table is mechanically checked against `firmware/asm/`,
`firmware/build/` and the cited paths by `scripts/check_datasheet.py`
(run in CI); a program added or removed without a row here fails the build.

<!-- firmware-images:begin -->
| Image | Protocol and mode | Rate (cycles, klt-flow RTL sim) | Words | Total cycles | Bench | Record |
|---|---|---|---|---|---|---|
| [`uart_tx`](../firmware/asm/uart_tx.asm) | UART TX, 8N1, frames 0x5A then 0xA5 | 50 per bit | 34 | 979 | [`test_firmware_uart.py`](../verification/test_firmware_uart.py) | [firmware-uart 20261002-165640-ebecf28](../verification/records/firmware-uart/records/20261002-165640-ebecf28.md) |
| [`uart_rx`](../firmware/asm/uart_rx.asm) | UART RX, 8N1 | 50 per bit | 132 | 488 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261009-084132-d79b51d](../verification/records/firmware-uart-rx/records/20261009-084132-d79b51d.md) |
| [`uart_rx_115200`](../firmware/asm/uart_rx_115200.asm) | UART RX, 8N1, 115200-baud class | 434 per bit | 168 | 3878 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261009-084132-d79b51d](../verification/records/firmware-uart-rx/records/20261009-084132-d79b51d.md) |
| [`uart_rx_9600`](../firmware/asm/uart_rx_9600.asm) | UART RX, 8N1, 9600-baud class (nested `WAIT`) | 5208 per bit | 168 | 2791 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261009-084132-d79b51d](../verification/records/firmware-uart-rx/records/20261009-084132-d79b51d.md) |
| [`uart_tx_9600`](../firmware/asm/uart_tx_9600.asm) | UART TX, 8N1, 9600-baud class (nested `WAIT`), frames 0x5A then 0xA5 | 5208 per bit | 177 | 6578 | [`test_firmware_uart_rx.py`](../verification/test_firmware_uart_rx.py) | [firmware-uart-rx 20261009-084132-d79b51d](../verification/records/firmware-uart-rx/records/20261009-084132-d79b51d.md) |
| [`spi_mode0`](../firmware/asm/spi_mode0.asm) | SPI controller, CPOL 0 / CPHA 0 | 4 per SCLK period (ceiling burst), 8 per bit (functional burst) | 119 | 181 | [`test_firmware_spi.py`](../verification/test_firmware_spi.py) | [firmware-spi 20261002-212640-061b65d](../verification/records/firmware-spi/records/20261002-212640-061b65d.md) |
| [`spi_mode1`](../firmware/asm/spi_mode1.asm) | SPI controller, CPOL 0 / CPHA 1 | 4 per SCLK period (ceiling burst), 8 per bit (functional burst) | 120 | 182 | [`test_firmware_spi.py`](../verification/test_firmware_spi.py) | [firmware-spi 20261002-212640-061b65d](../verification/records/firmware-spi/records/20261002-212640-061b65d.md) |
| [`spi_mode2`](../firmware/asm/spi_mode2.asm) | SPI controller, CPOL 1 / CPHA 0 | 4 per SCLK period (ceiling burst), 8 per bit (functional burst) | 119 | 181 | [`test_firmware_spi.py`](../verification/test_firmware_spi.py) | [firmware-spi 20261002-212640-061b65d](../verification/records/firmware-spi/records/20261002-212640-061b65d.md) |
| [`spi_mode3`](../firmware/asm/spi_mode3.asm) | SPI controller, CPOL 1 / CPHA 1 | 4 per SCLK period (ceiling burst), 8 per bit (functional burst) | 120 | 182 | [`test_firmware_spi.py`](../verification/test_firmware_spi.py) | [firmware-spi 20261002-212640-061b65d](../verification/records/firmware-spi/records/20261002-212640-061b65d.md) |
| [`i2c_fast`](../firmware/asm/i2c_fast.asm) | I2C controller, Fast-mode budget, write only | 125 per SCL clock (low 65 + high 60) | 181 | 3345 | [`test_firmware_i2c.py`](../verification/test_firmware_i2c.py) | [firmware-i2c 20261002-212508-25a0237](../verification/records/firmware-i2c/records/20261002-212508-25a0237.md) |
| [`i2c_std`](../firmware/asm/i2c_std.asm) | I2C controller, Standard-mode budget, write only | 435 per SCL clock (low 235 + high 200) | 181 | 9695 | [`test_firmware_i2c.py`](../verification/test_firmware_i2c.py) | [firmware-i2c 20261002-212508-25a0237](../verification/records/firmware-i2c/records/20261002-212508-25a0237.md) |
| [`i2c_fast_sr`](../firmware/asm/i2c_fast_sr.asm) | I2C controller, Fast-mode budget, write + repeated START + read, no pin-dependent branch | 125 per SCL clock (low 65 + high 60) | 131 | 1868 | [`test_firmware_i2c_sr.py`](../verification/test_firmware_i2c_sr.py) | [firmware-i2c 20261009-091929-48a4cc4](../verification/records/firmware-i2c/records/20261009-091929-48a4cc4.md) |
| [`i2c_fast_sr_poll`](../firmware/asm/i2c_fast_sr_poll.asm) | as `i2c_fast_sr`, polls SCL (tolerates clock stretching) | 127 per SCL clock unstretched (low 65 + high 62) | 171 | 1888 | [`test_firmware_i2c_sr.py`](../verification/test_firmware_i2c_sr.py) | [firmware-i2c 20261009-091929-48a4cc4](../verification/records/firmware-i2c/records/20261009-091929-48a4cc4.md) |
| [`i2c_std_sr`](../firmware/asm/i2c_std_sr.asm) | I2C controller, Standard-mode budget, write + repeated START + read, no pin-dependent branch | 435 per SCL clock (low 235 + high 200) | 131 | 5318 | [`test_firmware_i2c_sr.py`](../verification/test_firmware_i2c_sr.py) | [firmware-i2c 20261009-091929-48a4cc4](../verification/records/firmware-i2c/records/20261009-091929-48a4cc4.md) |
| [`i2c_std_sr_poll`](../firmware/asm/i2c_std_sr_poll.asm) | as `i2c_std_sr`, polls SCL (tolerates clock stretching) | 437 per SCL clock unstretched (low 235 + high 202) | 171 | 5338 | [`test_firmware_i2c_sr.py`](../verification/test_firmware_i2c_sr.py) | [firmware-i2c 20261009-091929-48a4cc4](../verification/records/firmware-i2c/records/20261009-091929-48a4cc4.md) |
| [`demo_roundtrip`](../firmware/asm/demo_roundtrip.asm) | none (assembler and load-phase round-trip coverage program) | n/a | 27 | 30 | [`test_firmware_roundtrip.py`](../verification/test_firmware_roundtrip.py) | [firmware-assembler-roundtrip 20260930-195410-ead870a](../verification/records/firmware-assembler-roundtrip/records/20260930-195410-ead870a.md) |
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
  `_poll` rise phases are budget + 2 cycles by construction. The only
  data-dependent branches are the sanctioned ACK/poll handshakes, which the
  assembler reports as warnings (1 per write-only image, 10 per `_poll`
  image).
- The I2C benches compose the open-drain bus in the testbench
  (`line = uio_out AND peripheral`) because `uio_oe` is 0; see Pins.

## How to run a protocol

Prerequisites for the Python-only steps: Python 3 (>= 3.9), nothing else.
The simulation steps need `klt` at the `layout/toolchain.json` pin plus
Icarus, provisioned by `./scripts/setup-env.sh` (see
[`verification/README.md`](../verification/README.md)).

1. **Check the images are the ones built from source** (Python only):
   `python3 firmware/tools/check_firmware.py`. To rebuild one:
   `python3 firmware/tools/asm.py firmware/asm/uart_tx.asm`.
2. **The loader.** The shipped loader is `load_program(dut, words)` in
   [`verification/_dut.py`](../verification/_dut.py) (the same sequence as
   the one in `test/test.py`); the benches read an image with the small
   parser in `verification/test_firmware_uart.py` (`load_committed_image`:
   one 4-hex-digit word per line of `firmware/build/<image>.hex`). The
   load-phase protocol it drives, for anyone wiring their own driver:
   - set `ui_in[7]` (MODE) high, `ui_in[0]` low; pulse `rst_n` low for
     10 clocks and release it;
   - clock one edge with MODE still high (the edge that latches MODE);
   - for each word in file order, for bit 15 down to 0, put the bit on
     `ui_in[0]` (keeping `ui_in[7]` high) and clock once;
   - drop `ui_in[7]` to enter run phase. The first instruction retires two
     edges later (fetch-ahead, DR 0005); execution then follows the
     cycle report exactly.
3. **Run and grade a protocol in simulation** (klt flow). Each request
   loads the committed image through step 2's sequence and grades the pins
   against the independent reference model:
   - UART: `klt functional-verification verification/request-firmware-uart.json --format json`
   - SPI, all four modes: `klt functional-verification verification/request-firmware-spi.json --format json`
   - I2C write, Fast and Standard: `klt functional-verification verification/request-firmware-i2c.json --format json`
   - I2C write/repeated-START/read and clock stretch: `klt functional-verification verification/request-firmware-i2c-sr.json --format json`
   - Assembler/load round trip: `klt functional-verification verification/request-firmware-roundtrip.json --format json`
4. **What to expect on the wire** (as graded by the records above):
   - UART: `uo_out[0]` idles high, then a start bit, 8 data bits LSB first
     and a stop bit, 50 cycles each, for 0x5A then 0xA5.
   - SPI: `uo_out[0]` CS falls, `uo_out[1]` SCLK idles at CPOL and toggles
     with a 4-cycle period carrying MOSI byte 0xA5 on `uo_out[2]`, then an
     8-cycle-per-bit burst carrying 0x3C; MISO is read from `uio_in[0]`;
     after CS releases the assembled received byte is echoed on `uo_out`.
   - I2C: START, address 0xA0 and ACK, data 0x5A and ACK, STOP (write-only
     images); the `_sr` images add repeated START, 0xA1, one read byte and
     a controller NACK, and publish the received byte on `uo_out`.

Not in this recipe: there is no host-side command that streams an image
into a physical chip (the loader is a cocotb coroutine), and no silicon
exists to run it on.

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
| `ui_in[7]` | MODE: high across `rst_n` release selects load phase |
| `ui_in[0]` | serial program data in load phase, MSB first |
| `uio_oe[7:0]` | **fixed 0**: every bidirectional pin is an input |
| `uio_out[7:0]` | written by `OUT`, but not driven onto a pin while `uio_oe` is 0 |

Observed in committed firmware (provisional, per image family):

| Family | Signal | Pin | Reaches a pin in the current RTL? |
|---|---|---|---|
| UART | TX | `uo_out[0]` | yes (dedicated output) |
| SPI | CS (active low) | `uo_out[0]` | yes |
| SPI | SCLK | `uo_out[1]` | yes |
| SPI | MOSI | `uo_out[2]` | yes |
| SPI | MISO | `uio_in[0]` | yes (input) |
| SPI, I2C `_sr` | result byte echo | `uo_out[7:0]` after the transfer | yes |
| I2C | SCL (1 = released) | `uio_out[0]` | **no**: `uio_oe` = 0 |
| I2C | SDA (1 = released) | `uio_out[7]` | **no**: `uio_oe` = 0 |
| I2C | SCL / SDA sampled | `uio_in[0]` / `uio_in[7]` | yes (input) |

Consequences, stated rather than papered over: the SPI and UART outputs
are on dedicated outputs and need no `uio_oe`; the I2C outputs are written
to `uio_out`, which is not enabled, so a physical I2C bus cannot be driven
by this RTL as it stands. The I2C benches therefore model the wired-AND
bus in the testbench (records above). `uio_in[0]` is MISO in the SPI
images and SCL-sense in the I2C images, so the families do not share one
fixed plan; reconciling that is #94's job. No pin claim here is backed by
silicon or by the LibreLane flow.

## Evidence not yet in hand

- **Tiny Tapeout LibreLane flow.** The routed-netlist SDF regression of the
  submitted core ([record](../verification/records/post-layout-sdf-regression/records/20261009-103407-9716a9e.md),
  LibreLane run 37911842396) is a **recorded FAIL** at all three corners (1
  of 13 core-bench tests passed) and ran only the core bench, not the
  firmware above. LibreLane timing evidence is in
  [`librelane-corner-timing`](../verification/records/librelane-corner-timing/records/20261002-095445-21a2a63.md).
  Firmware run on the routed netlist: none.
- **klt synthesis and timing.** `klt sta` does not yet support the SRAM
  macro, so the two flows do not agree on timing; per the project rule that
  mismatch is a finding, not a number to pick from.
- **Silicon:** none.
- DR 0001 and DR 0005 are `Proposed`, not ratified.

## External hardware

The chip has digital pins only: 3.3 V I/O on the Tiny Tapeout demo board, no
analog pads. Anything else goes on a Pmod
([Pmods and demo board](https://tinytapeout.com/specs/pcb-etr/)).

**Required for I2C:**

- A pull-up resistor from each of `uio[0]` (SCL) and `uio[7]` (SDA) to 3.3 V.
  The design releases an I2C line by tri-stating the pad, so the line reads
  high only with a pull-up. No pull-up is assumed to exist on the board.
  (Today's RTL fixes `uio_oe` to 0, so the pad is never driven at all; see
  Pins above. The pull-ups are needed once DR 0008's wiring lands.)
- The pins as listed under Pins are a custom plan. They do **not** match
  Tiny Tapeout's [recommended Pmod pinouts](https://tinytapeout.com/specs/pinouts/)
  (which put UART, SPI and I2C on one `uio` row, e.g. I2C SCL `uio[2]`/`uio[6]`,
  SDA `uio[3]`/`uio[7]`), so an off-the-shelf Pmod needs a wire adapter
  (DR 0010, "Alignment with Tiny Tapeout's recommended Pmod pinouts").

**Not required:** UART, SPI at 3.3 V with 3.3 V peers need no extra parts
beyond wiring.

**Levels and other buses.** A 5 V peer needs level shifting on a Pmod. A
differential bus (USB D+/D-, 10BASE-T) needs a transceiver on a Pmod; neither
is in the submitted design (DR 0011 defers them).

**Pad speed is unverified.** CMOS5L has no silicon yet and no pad
characterization; Tiny Tapeout is checking whether SG13G2-derived numbers
exist. Any claim of a maximum toggle rate at the pins, including the SPI SCLK
ceiling of f_clk/4 (12.5 MHz at 50 MHz), holds for the core's cycle timing
only, not at the pad.
