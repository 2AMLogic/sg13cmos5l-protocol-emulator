#!/usr/bin/env python3
"""mkflash.py -- turn a committed program image into the 512-byte flash image
that the SPI-flash boot (DR 0013 strap `01`, issue #140) loads.

    python3 firmware/tools/mkflash.py firmware/build/uart_tx.hex -o uart_tx.flash.bin
    python3 firmware/tools/mkflash.py --check uart_tx.flash.bin

The flash image is the program's 16-bit words, high byte first (the order
every image in this repository is laid out in, and the order the boot
program reads them), padded with a filler word up to word 254, then word 255
= the CRC-16/XMODEM (poly 0x1021, init 0x0000, no reflection, no final XOR)
of words 0..254, high byte first of each word. That is the signature format
of the warm start (strap `10`) too. Write the file to the QSPI Pmod's flash
at address 0; see docs/spi-flash-boot.md.

Refused, because the boot program would refuse the image:
  * a program longer than 255 words (word 255 is the signature);
  * a signature of 0x0000 (the SPI boot treats that as a dead MISO line --
    see the boot source); change the filler (`--filler 0x1234`) or the
    program and try again. Prints how likely that is: about 1 in 65,536.

Needs only the Python 3 standard library. The CRC comes from
`binascii.crc_hqx`, not from this repository's own code.
"""

from __future__ import annotations

import argparse
import binascii
import sys
from pathlib import Path

WORDS = 256
BODY_WORDS = WORDS - 1


def read_hex(path: Path) -> list:
    words = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            value = int(line, 16)
        except ValueError:
            raise SystemExit(f"{path}:{number}: malformed hex word {line!r}")
        if not 0 <= value <= 0xFFFF:
            raise SystemExit(f"{path}:{number}: {line!r} is not a 16-bit word")
        words.append(value)
    if not words:
        raise SystemExit(f"{path}: no words")
    return words


def words_to_bytes(words) -> bytes:
    return b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)


def crc16(words) -> int:
    return binascii.crc_hqx(words_to_bytes(words), 0x0000)


def build(words, filler=0x0000) -> bytes:
    if len(words) > BODY_WORDS:
        raise SystemExit(
            f"program is {len(words)} words; at most {BODY_WORDS} fit (word 255 is the signature)"
        )
    if not 0 <= filler <= 0xFFFF:
        raise SystemExit("filler must be a 16-bit word")
    body = list(words) + [filler] * (BODY_WORDS - len(words))
    signature = crc16(body)
    if signature == 0:
        raise SystemExit(
            "the signature of this image is 0x0000, which the SPI boot refuses "
            "(it cannot tell it from a dead MISO line). Change --filler or the program."
        )
    return words_to_bytes(body + [signature])


def check(data: bytes) -> list:
    """Problems with a flash image, [] if the SPI boot would accept it."""
    problems = []
    if len(data) != 2 * WORDS:
        problems.append(f"{len(data)} bytes, expected {2 * WORDS}")
        return problems
    words = [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]
    want = crc16(words[:BODY_WORDS])
    if words[BODY_WORDS] != want:
        problems.append(f"signature word is 0x{words[BODY_WORDS]:04x}, the CRC of words 0..254 is 0x{want:04x}")
    if words[BODY_WORDS] == 0:
        problems.append("signature word is 0x0000: the SPI boot refuses it")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", help="a .hex image (one 16-bit word per line), or with --check a flash .bin")
    ap.add_argument("-o", "--output", help="flash image to write (default: <input stem>.flash.bin)")
    ap.add_argument("--filler", type=lambda s: int(s, 0), default=0x0000,
                    help="word that pads the program up to word 254 (default 0x0000, a NOP)")
    ap.add_argument("--check", action="store_true", help="verify a flash image instead of building one")
    args = ap.parse_args(argv)
    src = Path(args.input)
    if args.check:
        problems = check(src.read_bytes())
        for p in problems:
            print(f"{src}: {p}", file=sys.stderr)
        if not problems:
            print(f"{src}: ok (512 bytes, signature matches)")
        return 1 if problems else 0
    words = read_hex(src)
    data = build(words, args.filler)
    out = Path(args.output) if args.output else src.with_suffix(".flash.bin")
    out.write_bytes(data)
    print(f"{src}: {len(words)} words + {BODY_WORDS - len(words)} filler -> {out} (512 bytes, signature "
          f"0x{(data[-2] << 8) | data[-1]:04x})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
