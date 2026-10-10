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
    boot/boot_rom.asm    the on-chip boot ROM's program (issue #138, DR
                         0013 layer 2). Not loaded into program memory:
                         the ROM in rtl/protocol_boot_rom.v is generated
                         from its image. See "The boot ROM" below.
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
    test_gen_boot_rom.py  its unit tests (the 128-word cap, determinism,
                          stale and hand-edited ROMs)
    check_firmware.py     every freshness check in one command
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
refuses an image over **128 words** (DR 0013's cap); the image is **30**.

What the program does: its first instruction reads the straps `ui_in[6:5]`.
Strap `10` is the **warm start**: it reads every word of program memory and
commits it back unchanged, which runs all 256 words through `PM_CRC` (the
hardware CRC only sees commits), and executes `WCTL RUN` to address 0 only
if the result is zero, that is, only if word 255 is the CRC-16/XMODEM of
words 0–254. It first restores `R0`–`R3`, `Z` and `C` to their reset
values, so a warm-started program starts in the state a serial-loaded one
does, except that it reads `BOOT_STATUS = 0x00`. One pass of the loop is 9
cycles (`.cyclesec warm_word`), and word 0 of a verified image executes
exactly 2,323 cycles after the boot program's first instruction. Straps
`00`, `01` and `11` are **stubs** (one `HALT` each) until the UART load
(#139) and the SPI-flash boot (#140) land; a failed warm start falls
through to the UART stub. A stub drives nothing.

The assembler reports three data-dependent-branch warnings for this
program, all intended: the two strap branches and the CRC verdict. None
paces a pin.

Known weak case, recorded in DR 0013: 256 zero words carry their own valid
signature (the CRC starts at 0), so a warm start runs them. They are `NOP`s.

Bench: `verification/test_boot_rom.py`
(`verification/request-boot-rom.json`), negative controls
`verification/boot_rom_mutants.py`, evidence in
`verification/records/boot-rom/`.

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

**Receiver shape.** RX = `UI_IN` bit 0 (idle high). A 3-cycle poll
(`IN`/`AND`/`BNZ`) finds the start edge; the first sample lands at the
centre of data bit 0 (1.5 bit periods after the edge, within the poll's
3-cycle granularity); later samples are exactly one period apart with no
branch between them. The byte is assembled by shifting and emitted on
`UO_OUT`; `UIO_OUT` bit 0 is a sample mark (the bench reads the real
sample instants off it) and bit 1 a framing-error flag (stop bit read 0).
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
Standard-mode budget (low = 235, high = 200 — both Table 10 floors to
the cycle; the floor-paced bus runs at the Standard-mode maximum, ~114.9
kHz at the unconfirmed nominal clock). Each program performs one write
transfer: START, address 0xA0 (0x50 << 1 | W), ACK slot, data byte 0x5A,
ACK slot, STOP.

**Pin plan** (these programs' own; the ratified pin-role decision record
is still open per target-spec row 5): SCL = `UIO_OUT` bit 0, SDA =
`UIO_OUT` bit 7, open-drain convention (1 = released, 0 = asserted).
Each I2C program makes that convention real on the pins with one
instruction in its setup, `WCTL UIO_OD, R3` with `R3 = 0x81` (DR 0012:
SCL and SDA become open-drain, `uio_oe[n] = ~uio_out[n]`). It comes
**after** the `OUT UIO_OUT` of `0x81`, because `uio_out` resets to 0 and
enabling open-drain first would pull both lines low for a cycle. It sits in
the idle setup, outside every `.cyclesec`, so no phase length changed.
The 0x80 mask register does double duty — bit extraction and the
ACK-slot "SDA released" pin value — because SDA sits on bit 7.

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
each byte is 65 instructions of straight-line phases, and a whole
program is 181 words. That fits DR 0001's 256-word memory for one
protocol with headroom, but it challenges the sketch's "all three core
protocols coexist with room for a dispatch table" sizing narrative —
recorded as an ISA finding in the evidence record, not a spec change.

Cycle accounting per phase (DR 0001's opcode table; `.cyclesec` sections
state each phase's exact length — the bench cross-checks all 41):

| Phase (Fast / Standard) | Instructions | Cycles |
|---|---|---|
| data-clock low | `OUT`+`WAIT 62`/`232`+`OR` | **65 / 235** |
| data-clock high | `OUT`+`SHF`+`WAIT 55`/`195`+`MOV`+`AND` | **60 / 200** |
| ACK low (incl. the `IN` sample) | `OUT`+`WAIT`+`IN`+`WAIT`+`AND`+`LDI` | **65 / 235** |
| START hold (t_HD;STA) | `OUT`+`WAIT`+`LDI`+`MOV`+`AND` | **65 / 205** |
| STOP setup (t_SU;STO) | `OUT`+`WAIT`+`LDI` | **60 / 205** |

The measured quantities are those **cycle counts**; the 400 kHz / 100
kHz names are arithmetic at target-spec row 4's unconfirmed clock (same
stance as `uart_tx.asm`).

**Open-drain, and what the bench does about it.** The programs' first
instructions release both lines (`OUT` of `0x81`) and then write `0x81`
to DR 0012's `UIO_OD` control register, so SCL (`uio[0]`) and SDA
(`uio[7]`) are open-drain pads: `uio_oe[n] = ~uio_out[n]`. The
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

**Pin map** (the fixed pin-port table, no new port codes; `uio_oe` stays 0
so all bidirectional pins remain inputs and MISO is simply read on the
input side):

| Pin | uo_out/uio_in bit | Role |
|---|---|---|
| CS | `uo_out[0]` | active low |
| SCLK | `uo_out[1]` | idles at CPOL |
| MOSI | `uo_out[2]` | controller-driven |
| MISO | `uio_in[0]` | peripheral-driven, sampled by `IN` |

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
2. **Functional burst** — 8 cycles/bit (under the ceiling;
   `.cyclesec spi_mode*_func`, 64 cycles), the same full-duplex shape plus
   MISO extraction and assembly (`IN`+`AND`+`SHF`+`OR` per bit — the
   extraction cannot fit the 4-cycle budget), after which the assembled
   byte is echoed on `uo_out[7:0]` once CS releases.

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
minimum (30 cycles Fast, 235 Standard). The bit loops keep a counter, so
the programs are 131 words (`_sr`) and 171 words (`_sr_poll`) of the
256-word store, against 181 words for the unrolled write-only programs.
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
