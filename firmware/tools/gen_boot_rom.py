#!/usr/bin/env python3
"""Generate the boot ROM's Verilog from the committed boot image (issue #138).

DR 0013 layer 2 (`spec/decision-records/0013-program-loading.md`): the boot
ROM's "contents are a program in this ISA, assembled by the DR 0003
assembler and committed byte for byte like any other firmware image. The ROM
netlist is generated from that image."

The chain, each link with its own freshness check:

    firmware/asm/boot/boot_rom.asm
        --(asm.py --out-dir firmware/build/boot)-->   asm.py --check
    firmware/build/boot/boot_rom.hex
        --(this script)-->                            this script --check
    rtl/protocol_boot_rom.v

`firmware/tools/check_firmware.py` runs both checks, so a stale image or a
stale ROM fails the same command CI and `npm run lint` already run.

The ROM is a `case` over the fetch address, registered once: synthesized as
logic, with the same one-cycle read as the program-memory macro. Addresses
past the end of the image read as `HALT`, so a boot program that jumps off
its own end stops with every pin as it was. The image may not exceed
`ROM_WORDS_MAX` words; a longer one is an error here. DR 0013 proposed a cap
of 128 and said "anything over the cap returns to this record". The UART
load (issue #139) did not fit under 128 (finding F2 in that record), so the
constant is the fetch address space, 256, until the record decides; see
`ROM_WORDS_MAX` below.

Output is deterministic: no timestamps and no absolute paths, so `--check`
is a byte comparison.

    python3 firmware/tools/gen_boot_rom.py            # (re)write the ROM
    python3 firmware/tools/gen_boot_rom.py --check    # exit 1 on drift

Exit codes: 0 written / fresh; 1 bad image or drift; 2 usage error.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent.parent
HEX_PATH = ROOT / "firmware" / "build" / "boot" / "boot_rom.hex"
ASM_PATH = ROOT / "firmware" / "asm" / "boot" / "boot_rom.asm"
OUT_PATH = ROOT / "rtl" / "protocol_boot_rom.v"

# DR 0013 layer 2 proposed "capped at 128 words". The UART load alone is over
# that (DR 0013, finding F2, issue #139), so this is the 8-bit fetch address
# space instead, the most the ROM's `case` can address. It is a stopgap, not a
# decision: the cap returns to the record, as DR 0013 open item 3 says.
ROM_WORDS_MAX = 256
HALT_WORD = 0xF000    # DR 0001 opcode 1111, operands 0

_WORD_RE = re.compile(r"^[0-9A-Fa-f]{4}$")


class RomError(Exception):
    pass


def parse_hex(text: str) -> List[int]:
    """Parse an asm.py image: one 4-digit hex word per line, nothing else."""
    words = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not _WORD_RE.match(line):
            raise RomError(f"line {line_no}: {line!r} is not a 4-digit hex word")
        words.append(int(line, 16))
    if not words:
        raise RomError("the boot image is empty")
    if len(words) > ROM_WORDS_MAX:
        raise RomError(
            f"the boot image is {len(words)} words; the boot ROM is capped at "
            f"{ROM_WORDS_MAX} words (DR 0013 finding F2). A larger ROM is a change to that record, not to this tool."
        )
    return words


def render(words: List[int], hex_text: str) -> str:
    """The generated module, as text."""
    digest = hashlib.sha256(hex_text.encode("utf-8")).hexdigest()
    rel_hex = HEX_PATH.relative_to(ROOT).as_posix()
    rel_asm = ASM_PATH.relative_to(ROOT).as_posix()
    out = [
        "/*",
        " * Copyright (c) 2026 2AMLogic",
        " * SPDX-License-Identifier: Apache-2.0",
        " *",
        " * GENERATED FILE -- DO NOT EDIT. Written by firmware/tools/gen_boot_rom.py",
        f" * from {rel_hex}, which firmware/tools/asm.py",
        f" * assembles from {rel_asm}. To change the ROM, edit",
        " * the .asm, re-assemble, and re-run the generator;",
        " * firmware/tools/check_firmware.py fails on any stale link in that chain.",
        " *",
        f" *   image words  : {len(words)} (cap {ROM_WORDS_MAX}: the fetch address space, DR 0013 finding F2)",
        f" *   image sha256 : {digest}",
        " *",
        " * The boot ROM of spec/decision-records/0013-program-loading.md layer 2",
        " * (issue #138): the program the core fetches when `rst_n` is released with",
        " * MODE low. It is logic, not a macro -- a `case` over the fetch address --",
        " * and it is registered once, so a word appears on `data` in the cycle after",
        " * its address was presented: the program-memory macro's one-cycle read",
        " * (DR 0005), which is what lets the core take either source through one",
        " * fetch stage. Addresses outside the image read as HALT (16'hF000).",
        " *",
        " * `data` resets to 16'h0000 (NOP). The value is never executed -- the core",
        " * ignores the fetched word until one real fetch has completed -- but a",
        " * reset value means this register is not one more flop that powers up",
        " * unknown (target-spec row 14).",
        " */",
        "",
        "`default_nettype none",
        "",
        "module protocol_boot_rom (",
        "    input  wire        clk,    // clock",
        "    input  wire        rst_n,  // reset_n - low to reset",
        "    input  wire [7:0]  addr,   // the core's fetch-ahead address",
        "    output reg  [15:0] data    // the word at the address presented one cycle earlier",
        ");",
        "",
        "  reg [15:0] word;",
        "",
        "  always @(*) begin",
        "    case (addr)",
    ]
    for index, word in enumerate(words):
        out.append(f"      8'h{index:02X}: word = 16'h{word:04X};")
    out += [
        f"      default: word = 16'h{HALT_WORD:04X};  // outside the image: HALT",
        "    endcase",
        "  end",
        "",
        "  always @(posedge clk or negedge rst_n) begin",
        "    if (!rst_n) begin",
        "      data <= 16'h0000;",
        "    end else begin",
        "      data <= word;",
        "    end",
        "  end",
        "",
        "endmodule",
        "",
        "`default_nettype wire",
    ]
    return "\n".join(out) + "\n"


def main(argv: List[str]) -> int:
    check = False
    for arg in argv:
        if arg == "--check":
            check = True
        else:
            print("usage: gen_boot_rom.py [--check]", file=sys.stderr)
            return 2
    rel_hex = HEX_PATH.relative_to(ROOT)
    rel_out = OUT_PATH.relative_to(ROOT)
    if not HEX_PATH.exists():
        print(f"error: {rel_hex} does not exist (assemble the boot program first)",
              file=sys.stderr)
        return 1
    hex_text = HEX_PATH.read_text(encoding="utf-8")
    try:
        words = parse_hex(hex_text)
    except RomError as err:
        print(f"error: {rel_hex}: {err}", file=sys.stderr)
        return 1
    rendered = render(words, hex_text)
    if check:
        if not OUT_PATH.exists():
            print(f"drift: {rel_out} is missing", file=sys.stderr)
            return 1
        if OUT_PATH.read_text(encoding="utf-8") != rendered:
            print(
                f"drift: {rel_out} does not match {rel_hex}\n"
                "Re-run: python3 firmware/tools/gen_boot_rom.py and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {rel_out} matches {rel_hex} ({len(words)} of {ROM_WORDS_MAX} words)")
        return 0
    OUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"{rel_hex}: {len(words)} of {ROM_WORDS_MAX} words -> {rel_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
