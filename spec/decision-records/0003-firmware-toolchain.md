# 0003: Firmware Toolchain

Status: Proposed (pending ratification alongside `spec/target-spec.md`)
Date: 2026-09-14
Issue: #1

## Context

DR 0001 fixed the instruction set; programs written against it are the
actual protocol implementations ("UART/SPI/I2C are firmware," per
`CLAUDE.md`). Firmware needs a way to get from a human- or agent-authored
description of a protocol's inner loop to the exact 16-bit words that load
into program memory (DR 0001's "Program memory sizing and loading"), and
that path needs to preserve the cycle-accuracy that makes the ISA's timing
guarantee meaningful — a toolchain that gets the cycle count wrong defeats
the entire point of DR 0001.

Per `CLAUDE.md`'s "Verification is the product" and "Firmware is evidence"
principles: "a protocol claim ... is only true when a committed program, run
on the RTL under cocotb, passes against an independent reference model of
that protocol with the timing checked. The program is part of the evidence
record, byte for byte." That means the toolchain's output has to be
something that gets committed and cited, not regenerated ad hoc for each
test run.

## Decision

**A small text assembler, hand-written for this ISA, with mnemonics
matching DR 0001's opcode table exactly.** Source programs are `.asm` text
files; the assembler emits one committed artifact per program: a hex/binary
program image plus a cycle-accounting report (total instruction count, and
for any protocol-timing-critical section, the exact cycle count from entry
to exit of that section, computed statically per DR 0001's guarantee).

### Where programs live

```
firmware/
  asm/            hand-written .asm source, one file per protocol program
    uart_tx.asm
    spi_ctrl.asm
    i2c_ctrl.asm
  build/          assembler output (program images + cycle reports) --
                  committed, not gitignored (see "evidence record" below)
  tools/          the assembler itself
```

This directory does not exist yet — creating it and the assembler are
implementation work for a later issue (this decision record only fixes the
shape; per this issue's own acceptance criteria, "nothing in `rtl/` yet,"
and by the same "ratify, don't implement" logic, `firmware/` is not created
by issue #1 either).

### How a program becomes part of an evidence record

Per `CLAUDE.md`'s append-only philosophy: a program's assembled binary and
its cycle-accounting report are committed alongside the `.asm` source, not
regenerated silently at test time and discarded. A cocotb test that claims
"this program does UART TX at 1 Mbaud" cites the specific committed program
image (by path and, once there is history, by the commit that produced it)
that it ran against the RTL — the same way `spec/verification-plan.md`'s
records are meant to be append-only. A later change to the assembler or the
program that changes its cycle behavior is a new committed artifact, not an
edit that silently invalidates a prior recorded pass.

### Alternatives considered

**A Python/generator-based approach** (write protocol firmware as Python
that emits instruction words programmatically, e.g. via a small DSL or
direct list-of-tuples construction) — attractive for parameterized programs
(e.g., "generate the UART TX loop for any baud rate" without hand-writing
the loop-unrolling arithmetic from DR 0001's 9,600-baud sketch each time).
Not rejected outright: this is likely the *right* tool for exactly that
class of program (baud-rate-parameterized delay loops), layered **on top
of** the assembler rather than replacing it — a generator emits `.asm` (or
directly emits the assembler's intermediate form), and the assembler
remains the single place that performs cycle accounting and the final
encode-to-16-bit-words step. Kept as a firmware-authoring convenience
decision for a later issue, not this record's concern, precisely because
DR 0001 already surfaced a concrete case (UART at 9,600 baud) where hand-
deriving the exact loop trip count is exactly the kind of arithmetic a
generator should do instead of a human.

**Hardcaml-style embedding** (write firmware as a DSL embedded in a general-
purpose host language — e.g., OCaml/Hardcaml conventions — that constructs
and type-checks the instruction stream at the host language's compile
time). Rejected for this ISA's scope: Hardcaml-style embedding earns its
complexity when the thing being generated is itself parameterized hardware
or has significant structural variation; DR 0001's ISA is 16 fixed opcodes
over a flat, non-recursive instruction stream, and the actual firmware
programs (per the cycle-budget sketches) are on the order of tens of
instructions each. A general-purpose host language and its build
toolchain would be a heavier dependency than this problem's actual
complexity justifies, and would put a second language's toolchain and
correctness on this program's evidence-record critical path for no
capability the sketched programs actually need.

**No assembler — write raw hex/binary instruction words by hand.**
Rejected: directly contradicts "no claim without a testbench" in spirit —
hand-encoded 16-bit words are unauditable without re-deriving the encoding
from DR 0001's opcode table by hand every time, and a bit-encoding
transcription error would be invisible in review (a `.asm` mnemonic like
`OUT PIN_OUT, R0` is reviewable; `0xA400` is not, absent tooling that
decodes it back).

## Consequences

- The assembler is a small, focused piece of software with one job (text
  mnemonics -> DR 0001's 16-bit encoding + a cycle report) and is itself a
  future issue's scope, not this one's.
- Firmware programs are committed source (`.asm`) plus committed build
  output (image + cycle report), both under version control — the
  "evidence record, byte for byte" instruction is satisfied by "the
  committed files this repo's history contains," not by a build step that
  regenerates and discards.
- A future code-generator layer (for parameterized delay loops, e.g. "emit
  the loop for baud rate X") is left open as a firmware-authoring
  convenience on top of the assembler, not a replacement for it — it would
  still emit into the same `.asm`/encoding path so the assembler remains
  the single source of cycle-accounting truth.
