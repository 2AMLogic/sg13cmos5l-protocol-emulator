#!/usr/bin/env python3
"""loadseq -- host-side program-loading artifacts from a committed `.hex`.

DR 0013 layer 3 (`spec/decision-records/0013-program-loading.md`): "loadseq
(issue #118) produces both host artifacts from a committed .hex: the layer-1
pin sequence for the demo board's MCU, with the CRC check, and the layer-2
UART frame for a PC." This file starts that tool with the layer-2 half, the
subcommand `uart` (issue #139). The layer-1 pin sequence (`serial`) is
issue #118's and is not here.

    python3 firmware/tools/loadseq.py uart IMAGE.hex [-o FRAME] [--format F]

`IMAGE.hex` is an `asm.py` image: one 4-digit hex word per line, 1 to 256
words. The frame is what the on-chip boot program's UART load receives (DR
0013 strap `00`; `firmware/asm/boot/boot_rom.asm`):

    0xA5   N-1   2N image bytes, each word high byte first   CRC-16/XMODEM

and the CRC covers the 2N image bytes only (not the `0xA5`, not the count).
CRC-16/XMODEM: polynomial 0x1021, initial value 0x0000, no reflection, no
final XOR; sent high byte first. The chip answers `0x06` (accepted) or
`0x15` (rejected) followed by its own CRC of what it wrote, high byte first;
it runs the image only on `0x06`. Line settings: 8N1, 434 core cycles per
bit (115,200 baud at the 50 MHz row-4 clock; 50e6 / 434 = 115,207 baud, +0.006
%), no flow control. The first byte may be sent as soon as the chip is out of
reset; bytes may be sent back to back.

Formats (`--format`): `bin` (the raw frame, the default; written to `-o` or,
without it, to stdout's buffer), `hex` (one byte per line, two hex digits,
`$readmemh`-compatible), `python` (a `bytes` literal for a MicroPython or
pyserial host).

Stdlib only; deterministic output. Nothing here is shared with the bench's
host model (`verification/uart_boot_host.py`), which frames independently;
`verification/test_boot_uart.py` asserts the two agree byte for byte.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List

MAGIC = 0xA5
ACK = 0x06
NAK = 0x15
MAX_WORDS = 256
CYCLES_PER_BIT = 434

_WORD_RE = re.compile(r"^[0-9A-Fa-f]{4}$")


class LoadseqError(Exception):
    pass


def crc16_xmodem(data: bytes, crc: int = 0x0000) -> int:
    """CRC-16/XMODEM, bit by bit: poly 0x1021, no reflection, no final XOR."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_hex(text: str) -> List[int]:
    """The words of an `asm.py` image (4 hex digits per line, blanks skipped)."""
    words = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if not _WORD_RE.match(line):
            raise LoadseqError(f"line {number}: {line!r} is not a 4-digit hex word")
        words.append(int(line, 16))
    if not words:
        raise LoadseqError("the image is empty")
    if len(words) > MAX_WORDS:
        raise LoadseqError(f"the image is {len(words)} words; program memory holds {MAX_WORDS}")
    return words


def uart_frame(words: List[int]) -> bytes:
    """The DR 0013 UART frame for `words` (1..256 16-bit words)."""
    if not 1 <= len(words) <= MAX_WORDS:
        raise LoadseqError(f"a frame carries 1 to {MAX_WORDS} words, not {len(words)}")
    body = b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)
    crc = crc16_xmodem(body)
    return bytes((MAGIC, len(words) - 1)) + body + bytes((crc >> 8, crc & 0xFF))


def render(frame: bytes, fmt: str) -> bytes:
    if fmt == "bin":
        return frame
    if fmt == "hex":
        return "".join(f"{b:02x}\n" for b in frame).encode("ascii")
    if fmt == "python":
        return ("FRAME = bytes.fromhex(\n    \"" + frame.hex() + "\"\n)\n").encode("ascii")
    raise LoadseqError(f"unknown format {fmt!r}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loadseq", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    uart = sub.add_parser("uart", help="emit the DR 0013 layer-2 UART frame for a .hex image")
    uart.add_argument("image", type=Path)
    uart.add_argument("-o", "--out", type=Path, help="write here instead of stdout")
    uart.add_argument("--format", choices=("bin", "hex", "python"), default="bin")
    args = parser.parse_args(argv)
    try:
        words = parse_hex(args.image.read_text(encoding="utf-8"))
        data = render(uart_frame(words), args.format)
    except (LoadseqError, OSError) as exc:
        print(f"loadseq: {exc}", file=sys.stderr)
        return 1
    if args.out is not None:
        args.out.write_bytes(data)
        print(f"loadseq: {len(words)} words -> {len(data)} bytes ({args.format}) in {args.out}")
    else:
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
