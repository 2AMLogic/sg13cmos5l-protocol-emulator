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
    i2c_fast.asm         bit-banged I2C controller, Fast-mode 400 kHz
                         phase budget (issue #73, the I2C third of #23)
    i2c_std.asm          the same controller on the Standard-mode
                         100 kHz phase budget (issue #73)
  build/          assembler output (program images + cycle reports) —
                  COMMITTED, not gitignored: a program's image and cycle
                  report are part of the evidence record, byte for byte
  tools/          the assembler itself
    asm.py        the assembler (Python 3 stdlib only, no dependencies)
    test_asm.py   its unit tests (all 16 opcodes + malformed input)
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
python3 firmware/tools/asm.py firmware/asm/demo_roundtrip.asm --check
python3 firmware/tools/asm.py firmware/asm/uart_tx.asm --check
python3 firmware/tools/asm.py firmware/asm/i2c_fast.asm --check
python3 firmware/tools/asm.py firmware/asm/i2c_std.asm --check
```

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

**Open-drain caveat, stated rather than papered over:** `uio_oe` is
fixed to 0 at the top level, so on silicon no firmware drive reaches a
physical pin. The DUT-facing bench composes the wired-AND bus
(line = controller `uio_out` AND peripheral `uio_in`) and grades that
against the independent reference model — proving the firmware's cycle
timing and protocol behavior at the point the core drives and samples,
with the ACK flowing through the core's real `IN` path. A silicon-true
open-drain SDA/SCL needs a pin-plan decision record (DR 0001's own
flagged open question); tracked in its own issue, not worked around
here.

Run the DUT-facing bench with:

```bash
klt functional-verification verification/request-firmware-i2c.json --format json
```

Its result is committed as an append-only evidence record under
`verification/records/firmware-i2c/`.

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
