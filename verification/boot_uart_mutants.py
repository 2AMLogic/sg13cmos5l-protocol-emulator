#!/usr/bin/env python3
"""Negative controls for `test_boot_uart.py` (issue #139, DR 0013 layer 2).

A bench that cannot fail cannot cite its passes. Like
`boot_rom_mutants.py`, this runner copies the sources the bench needs into a
scratch tree, injects ONE defect into the copy of the *generated* boot ROM
(`rtl/protocol_boot_rom.v`) as a changed word, runs the bench on it through
`klt functional-verification`, and requires a test that is meant to catch
that defect to FAIL, by a parsed result and not by a crash. `rtl/`, `src/`
and `firmware/` in the repository are never edited. A ROM mutant also fails
the bench's image-chain test (the ROM no longer matches the committed
image) and that failure does not count.

Each mutant names the addresses it changes in the committed image
(`firmware/build/boot/boot_rom.cycles.txt` lists them) and must apply
exactly as many times as stated, so a later edit to the boot program cannot
silently turn a negative control into a second positive run.

To keep a run affordable each mutant is run against just the tests that are
meant to catch it (the request's `testcase` is narrowed in the copy); the
golden run is the whole bench (and, for a mutant whose catcher is in the
count-alias bench of issue #211, that whole bench too).

Usage:
    python3 verification/boot_uart_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH, like the bench itself;
`KLT_CMD` overrides the command (for example a `uvx --with cocotb ... klt`
line). Runs one simulation at a time.
Exit 0 = the golden run passed and every mutant was caught as required.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

from _mutant_runner import run
ROM = "rtl/protocol_boot_rom.v"
REQUEST = "verification/request-boot-uart.json"
ALIAS_REQUEST = "verification/request-boot-uart-count-alias.json"

T_NOMINAL = "test_nominal_load_runs_the_image"
T_BAD = "test_bad_images_never_run"
T_TOL = "test_row10_tolerance_edges"
T_ALIAS = "test_count_corruption_is_rejected"   # in test_boot_uart_count_alias.py


def word(addr, old, new):
    return (f"      8'h{addr:02X}: word = 16'h{old:04X};", f"      8'h{addr:02X}: word = 16'h{new:04X};", 1)


# (name, what the defect is, [(old, new, count)], tests that must catch it[, request])
# The request defaults to REQUEST; a mutant whose catcher lives in another
# bench names that bench's request.
MUTANTS = [
    ("verdict-always-accepts",
     "the trailer comparison's branch is a NOP: every frame is answered 0x06 and run",
     [word(0x3E, 0xE040, 0x0000)], {T_BAD}),
    ("trailer-high-byte-unchecked",
     "the trailer comparison ORs R0 with itself, so only the low CRC byte is compared",
     [word(0x3C, 0x6100, 0x6000)], {T_BAD}),
    ("crc-not-cleared-at-the-count",
     "the count handler no longer clears PM_CRC, so a retry after a rejected frame carries the "
     "old frame's residue",
     [word(0x7C, 0xA406, 0x0000)], {T_BAD}),
    ("rx-bit-period-wrong",
     "the receiver's bit period is 466 cycles, not 434",
     [word(0x25, 0xB0A3, 0xB0C3)], {T_NOMINAL}),
    ("rx-reads-ui-in-bit-0",
     "the receiver masks ui_in[0] instead of ui_in[1]",
     [word(0x0F, 0x1402, 0x1401)], {T_NOMINAL}),
    ("tx-stop-bit-too-short",
     "the reply's stop bit is padded for 82 cycles, not 171",
     [word(0x55, 0xB0AA, 0xB051)], {T_NOMINAL}),
    ("handover-drops-the-guard-last",
     "the hand-over clears uio_out before UIO_OD and UIO_DIR: for two cycles every uio pin drives low",
     [word(0x6A, 0xA000, 0xA300), word(0x6B, 0xA001, 0xA000), word(0x6C, 0xA300, 0xA001)],
     {T_NOMINAL}),
    ("complement-check-removed",
     "the count-complement check's branch is a NOP (issue #211): a count whose third byte is not "
     "its complement is taken, so the F8 frame with count 01 flipped to 00 is answered 0x06 and run",
     [word(0x83, 0xE040, 0x0000)], {T_ALIAS}, ALIAS_REQUEST),
]


def klt_command() -> list:
    return shlex.split(os.environ.get("KLT_CMD", "klt"))


def narrow_request(tree: Path, testcases, request: str = REQUEST) -> None:
    path = tree / request
    doc = json.loads(path.read_text(encoding="utf-8"))
    names = sorted(testcases)
    doc["testbench"]["testcase"] = names if len(names) > 1 else names[0]
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    # Every bench a mutant is run against passes whole on the unmodified copy.
    requests = [REQUEST] + sorted({m[4] for m in MUTANTS if len(m) > 4} - {REQUEST})
    return run(__doc__, argv, bench="verification/test_boot_uart.py", mutants=MUTANTS,
               request=REQUEST, file=ROM, goldens=requests,
               golden_label="golden (unmodified copy, {request})", record_request=True,
               skip_golden_option=True, klt=klt_command(), prepare=narrow_request,
               result_message="golden passes and every mutant is caught by a test meant to catch it")


if __name__ == "__main__":
    sys.exit(main())
