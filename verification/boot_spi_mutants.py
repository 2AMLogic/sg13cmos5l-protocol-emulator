#!/usr/bin/env python3
"""Negative controls for `test_boot_spi.py` (issue #140, DR 0013 strap 01).

A bench that cannot fail cannot cite its passes. Like `boot_rom_mutants.py`,
this runner copies the sources the bench needs into a scratch tree, injects
ONE defect into the copy, and runs the unmodified bench on it through `klt
functional-verification`, requiring a parsed result with at least one failed
test. `rtl/`, `src/` and `firmware/` in the repository are never edited.

The defect goes into the boot program's SOURCE (`firmware/asm/boot/
boot_rom.asm`) in the copy, and the copy's chain is rebuilt from it
(`asm.py`, then `gen_boot_rom.py`), so the copy's image, ROM and the ISA
model the bench runs are all the mutant. The bench therefore cannot catch a
mutant merely because the DUT disagrees with a stale model: it has to see
the defect in what the flash model records, in the pins, or in the outcome.
Each mutant names the tests that exist to catch it, and one of those must
fail. Each substitution must apply exactly as many times as stated, so a
later edit to the boot program cannot silently turn a negative control into
a second positive run.

Usage:
    python3 verification/boot_spi_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH, like the bench itself.
Runs one simulation at a time (about 2.5 minutes each). Writes
`summary.json` and one directory per mutant under --out (default: a
temporary directory, removed on exit). Exit 0 = the golden run passed and
every mutant was caught as required.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _mutant_runner import run
ASM = "firmware/asm/boot/boot_rom.asm"
REQUEST = "verification/request-boot-spi.json"

T_CHAIN = "test_model_chain_and_prediction"
T_GOOD = "test_good_flash_boots_a_program_that_starts_in_the_reset_state"
T_PROTO = "test_protocol_programs_boot_from_flash_and_pass_reference_models"
T_BLANK = "test_blank_or_absent_flash_never_runs"
T_CORRUPT = "test_corrupt_flash_never_runs"
T_ZERO = "test_zero_signature_is_refused"

VERDICT = ("        OR    R0, R1                ; Z <=> PM_CRC == 0 <=> word 255 is the CRC of "
           "words 0..254\n        BNZ   spi_fail")

# (name, what the defect is, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("command-is-0x00",
     "the command's two 1 bits are sent as 0: the flash is sent opcode 0x00, not READ",
     [("        LDI   R0, 0x06\n        OUT   UIO_OUT, R3           ; CS0 falls",
       "        LDI   R0, 0x04\n        OUT   UIO_OUT, R3           ; CS0 falls", 1)],
     {T_GOOD, T_PROTO}),
    ("address-is-25-bits",
     "one extra address clock: the flash's data is a bit late",
     [("        LDI   R1, 96                ; 24 address bits, all zero",
       "        LDI   R1, 100               ; MUTANT: 25 address bits", 1)],
     {T_GOOD, T_PROTO}),
    ("cs-left-to-the-pull-up",
     "CS0 is never driven high at the end: the flash is deselected only because the pad is released "
     "and the Pmod pulls it up",
     [("        OUT   UIO_OUT, R2           ; CS0 rises (SCK already low)",
       "        NOP                         ; MUTANT: CS0 not driven high", 1)],
     {T_GOOD, T_PROTO}),
    ("cs-falls-with-sck-high",
     "the first CS0 fall happens with SCK high (the image 0x08), not low: mode 3 idle, off by a clock",
     [("        OUT   UIO_OUT, R3           ; CS0 falls (SCK low, MOSI 0)",
       "        OUT   UIO_OUT, R2           ; MUTANT: CS0 falls with SCK high", 1)],
     {T_GOOD, T_PROTO}),
    ("high-byte-latched-at-bit-9",
     "the high byte is latched after the ninth bit, not the eighth",
     [("        LDI   R2, 32                ; after the 8th bit",
       "        LDI   R2, 28                ; MUTANT: after the 9th bit", 1)],
     {T_GOOD, T_PROTO}),
    ("verdict-skipped",
     "the branch on the CRC verdict is a NOP: every image whose signature word is not zero is run",
     [(VERDICT, VERDICT.replace("BNZ   spi_fail", "NOP"), 1)],
     {T_BLANK, T_CORRUPT}),
    ("verdict-ignores-crc-high-byte",
     "the verdict tests PM_CRC_LO only",
     [(VERDICT, VERDICT.replace("OR    R0, R1  ", "OR    R1, R1  "), 1)],
     {T_CORRUPT}),
    ("verdict-ignores-crc-low-byte",
     "the verdict tests PM_CRC_HI only",
     [(VERDICT, VERDICT.replace("OR    R0, R1  ", "OR    R0, R0  "), 1)],
     {T_CORRUPT}),
    ("zero-signature-accepted",
     "the refusal of signature 0x0000 is a NOP: a dead MISO line (all zeros) is run",
     [("        BZ    spi_fail", "        NOP", 1)],
     {T_ZERO, T_BLANK}),
    ("signature-read-from-word-0",
     "the zero-signature check reads word 0 instead of word 255",
     [("        LDI   R2, 0xFF\n        WCTL  PM_ADDR, R2", "        LDI   R2, 0x00\n        WCTL  PM_ADDR, R2", 1)],
     {T_ZERO, T_BLANK}),
    ("pins-not-released",
     "UIO_DIR is not cleared at the end: the flash pins stay outputs, on a failed boot and after RUN",
     [("        WCTL  UIO_DIR, R0           ; every uio pin an input again ...",
       "        NOP                         ; MUTANT: UIO_DIR not cleared", 1)],
     {T_GOOD, T_BLANK}),
    ("psram-cs-driven",
     "UIO_DIR also enables uio[7], a PSRAM chip select",
     [("        LDI   R2, 0x0B\n        WCTL  UIO_DIR, R2", "        LDI   R2, 0x8B\n        WCTL  UIO_DIR, R2", 1)],
     {T_GOOD, T_BLANK}),
]


def rebuild_chain(tree: Path) -> None:
    for cmd in (
        [sys.executable, "firmware/tools/asm.py", ASM, "--out-dir", "firmware/build/boot"],
        [sys.executable, "firmware/tools/gen_boot_rom.py"],
    ):
        proc = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"{cmd}: {proc.stderr[-400:]}")


def main(argv=None) -> int:
    return run(__doc__, argv, bench="verification/test_boot_spi.py", mutants=MUTANTS,
               request=REQUEST, file=ASM, rebuild=rebuild_chain,
               rebuild_label="the mutated boot program",
               result_message="golden passes and every mutant is caught by a test meant to catch it")


if __name__ == "__main__":
    sys.exit(main())
