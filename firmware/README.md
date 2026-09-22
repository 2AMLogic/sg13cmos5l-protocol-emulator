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
    demo_roundtrip.asm   the assembler's round-trip coverage program (this
                         issue; the UART/SPI/I2C programs are issue #23)
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

# Verify the committed build artifacts still match the committed source
# (what CI runs — catches a stale committed image):
python3 firmware/tools/asm.py firmware/asm/demo_roundtrip.asm --check
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
