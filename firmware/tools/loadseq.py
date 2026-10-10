#!/usr/bin/env python3
"""Host-side generator of the direct program-load pin sequence (issue #118).

Reads a committed `.hex` image and emits the exact per-clock pin states of
the MODE-high serial load protocol (DR 0001 "Program memory sizing and
loading"; `docs/info.md` "How to run a protocol"). This is the *direct pin*
loader; UART/SPI boot are separate transports. Stdlib only.

Image format: one 4-hex-digit word per line, in file order. Blank (or
whitespace-only) lines are skipped; nothing else is tolerated (no comments,
no `0x`, no short or long words). 1..256 words; an empty, malformed or
257-word input is rejected with exit status 2 before anything is emitted.
No padding word is ever appended.

Sequence (format VERSION 1), one step per clock cycle, each step is
(ui_in, uio_in, rst_n, ena) held while clk is low, then one rising edge:

    10 steps   ui_in=0x80 (MODE high, serial low), rst_n=0
     1 step    ui_in=0x80, rst_n=1  -- the MODE-latching edge, shifts no bit
    16*N steps ui_in=0x80|bit, rst_n=1, bit 15 first of each word
     1 step    ui_in=0x00, rst_n=1  -- the MODE-drop edge (run phase begins)

with uio_in=0 and ena=1 throughout. Total 12 + 16*N steps.

    loadseq.py IMAGE.hex                    # JSON on stdout
    loadseq.py IMAGE.hex --format python    # VERSION/WORDS/STEPS module text
    loadseq.py IMAGE.hex -o OUT
    loadseq.py --check IMAGE.hex [...]      # read-only validation, no output
    loadseq.py IMAGE.hex --uart -o FRAME    # the UART boot frame (issue #139)
    loadseq.py IMAGE.hex --uart --format hex|python

`--check` regenerates in memory and replays the steps through
`simulate_load`, a small behavioural model of the load protocol written
from the RTL contract and sharing no code with `generate_steps`.

UART frame (`--uart`, issue #139, DR 0013 layer 2 strap `00`). The other
transport: instead of the pin sequence, the bytes a PC sends to the boot ROM's
UART load (`firmware/asm/boot/boot_rom.asm`, block `uart_load`) over the demo
board's USB-UART bridge, Tiny Tapeout option B (RX `ui_in[1]`, TX `uo_out[0]`):

    0xA5   N-1   2N image bytes, each word high byte first   CRC-16/XMODEM

The CRC covers the 2N image bytes only (not the `0xA5`, not the count);
polynomial 0x1021, initial value 0x0000, no reflection, no final XOR; sent
high byte first. The chip answers `0x06` (accepted) or `0x15` (rejected) and
its own CRC of what it wrote, high byte first, and runs the image only on
`0x06`. Line settings: 8N1, 434 core cycles per bit (115,200 baud at the 50 MHz
row-4 clock, which is unconfirmed; 50e6 / 434 = 115,207 baud), no flow control.
The first byte may be sent as soon as the chip is out of reset and bytes may
go back to back. Formats with `--uart`: `bin` (the raw frame, the default),
`hex` (one byte per line, two hex digits) and `python` (a `bytes` literal).
The bench's host model (`verification/uart_boot_host.py`) frames
independently of this file and `verification/test_boot_uart.py` asserts the two
agree byte for byte.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loadseq_playback as pb  # noqa: E402

VERSION = pb.VERSION
UART_MAGIC = 0xA5
UART_ACK = 0x06
UART_NAK = 0x15
MAX_WORDS = 256
RESET_CLOCKS = 10
MODE = 0x80

_WORD = re.compile(r"[0-9A-Fa-f]{4}")


class LoadSeqError(ValueError):
    pass


def parse_words(text, source="<input>"):
    words = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if not _WORD.fullmatch(line):
            raise LoadSeqError(
                "%s:%d: want exactly 4 hex digits, got %r" % (source, number, line))
        words.append(int(line, 16))
    if not words:
        raise LoadSeqError("%s: image holds no words" % source)
    if len(words) > MAX_WORDS:
        raise LoadSeqError("%s: %d words exceeds the %d-word program memory"
                           % (source, len(words), MAX_WORDS))
    return words


def generate_steps(words):
    if not 1 <= len(words) <= MAX_WORDS:
        raise LoadSeqError("need 1..%d words, got %d" % (MAX_WORDS, len(words)))
    for w in words:
        if not 0 <= w <= 0xFFFF:
            raise LoadSeqError("word %r out of 16-bit range" % (w,))
    steps = [(MODE, 0, 0, 1)] * RESET_CLOCKS
    steps.append((MODE, 0, 1, 1))  # MODE-latching edge, no bit shifted
    for w in words:
        for b in range(15, -1, -1):
            steps.append((MODE | ((w >> b) & 1), 0, 1, 1))
    steps.append((0x00, 0, 1, 1))  # MODE drop
    return steps


def simulate_load(steps):
    """Behavioural model of the load protocol; returns the committed words.

    Raises LoadSeqError on any deviation from the VERSION 1 shape (ena or
    uio_in not constant, MODE not high until the single final drop, reset
    release without MODE, bits after the drop, mid-word end)."""
    n = len(steps)
    words, shreg, nbits = [], 0, 0
    state = "reset"
    for i, (ui_in, uio_in, rst_n, ena) in enumerate(steps):
        if ena != 1 or uio_in != 0:
            raise LoadSeqError("step %d: ena/uio_in must be 1/0" % i)
        if state == "reset":
            if not ui_in & MODE or ui_in & ~MODE & 0xFF:
                raise LoadSeqError("step %d: want exactly MODE high" % i)
            if rst_n == 1:
                if i != RESET_CLOCKS:
                    raise LoadSeqError("reset released at step %d, want %d" % (i, RESET_CLOCKS))
                state = "load"  # this edge latched MODE high, shifts nothing
        elif state == "load":
            if rst_n != 1:
                raise LoadSeqError("step %d: reset re-asserted mid-load" % i)
            if not ui_in & MODE:
                if ui_in != 0 or i != n - 1:
                    raise LoadSeqError("step %d: bad MODE drop" % i)
                state = "run"
            else:
                if ui_in & 0x7E:
                    raise LoadSeqError("step %d: stray ui_in bits" % i)
                shreg = ((shreg << 1) | (ui_in & 1)) & 0xFFFF
                nbits += 1
                if nbits == 16:
                    if len(words) < MAX_WORDS:
                        words.append(shreg)
                    nbits = 0
    if state != "run" or nbits:
        raise LoadSeqError("sequence does not end in a clean MODE drop")
    return words


def encode_steps(steps):
    return pb.encode_steps(steps)


def to_json(words, steps):
    return json.dumps({
        "version": VERSION,
        "words": len(words),
        "fields": ["ui_in", "uio_in", "rst_n", "ena"],
        "steps": [list(s) for s in steps],
    }, indent=None, separators=(",", ":")) + "\n"


def crc16_xmodem(data, crc=0x0000):
    """CRC-16/XMODEM, bit by bit: poly 0x1021, no reflection, no final XOR."""
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def uart_frame(words):
    """The DR 0013 UART frame for `words` (1..256 16-bit words)."""
    if not 1 <= len(words) <= MAX_WORDS:
        raise LoadSeqError("a frame carries 1..%d words, got %d" % (MAX_WORDS, len(words)))
    for w in words:
        if not 0 <= w <= 0xFFFF:
            raise LoadSeqError("word %r out of 16-bit range" % (w,))
    body = b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)
    crc = crc16_xmodem(body)
    return bytes((UART_MAGIC, len(words) - 1)) + body + bytes((crc >> 8, crc & 0xFF))


def render_uart(frame, fmt):
    if fmt == "bin":
        return frame
    if fmt == "hex":
        return "".join("%02x\n" % b for b in frame).encode("ascii")
    if fmt == "python":
        return ("FRAME = bytes.fromhex(\n    \"%s\"\n)\n" % frame.hex()).encode("ascii")
    raise LoadSeqError("format %r is not a UART frame format" % fmt)


def to_python(words, steps):
    return ("# loadseq format version %d: %d words, %d steps\n"
            "# step = (ui_in, uio_in, rst_n, ena); see loadseq_playback.py\n"
            "VERSION = %d\nWORDS = %d\nSTEPS = %r\n"
            % (VERSION, len(words), len(steps), VERSION, len(words),
               encode_steps(steps)))


def check_image(path):
    """Read-only validation of one image; returns a list of problems."""
    words = parse_words(Path(path).read_text(encoding="utf-8"), str(path))
    steps = generate_steps(words)
    problems = []
    if steps != generate_steps(words):
        problems.append("generation is not deterministic")
    if len(steps) != 12 + 16 * len(words):
        problems.append("step count %d, want %d" % (len(steps), 12 + 16 * len(words)))
    if pb.decode_steps(encode_steps(steps)) != [tuple(s) for s in steps]:
        problems.append("encode/decode round trip differs")
    try:
        got = simulate_load(steps)
        if got != words:
            problems.append("model replay loads different words")
    except LoadSeqError as exc:
        problems.append("model replay: %s" % exc)
    frame = uart_frame(words)
    if (len(frame) != 2 * len(words) + 4 or frame[0] != UART_MAGIC or frame[1] != len(words) - 1
            or crc16_xmodem(frame[2:]) != 0):
        problems.append("UART frame has the wrong shape or a nonzero CRC residue")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("images", nargs="+", metavar="IMAGE.hex")
    ap.add_argument("--format", choices=("json", "python", "bin", "hex"), default=None,
                    help="direct-load: json (default) or python; with --uart: bin (default), hex or python")
    ap.add_argument("--uart", action="store_true",
                    help="emit the DR 0013 UART boot frame instead of the direct-load pin sequence")
    ap.add_argument("-o", "--output")
    ap.add_argument("--check", action="store_true",
                    help="read-only validation; emits nothing")
    args = ap.parse_args(argv)
    try:
        if args.check:
            bad = 0
            for img in args.images:
                for p in check_image(img):
                    print("FAIL %s: %s" % (img, p))
                    bad += 1
            print("loadseq --check: %d image(s), %d problem(s)" % (len(args.images), bad))
            return 1 if bad else 0
        if len(args.images) != 1:
            ap.error("exactly one image unless --check")
        words = parse_words(Path(args.images[0]).read_text(encoding="utf-8"),
                            args.images[0])
        if args.uart:
            data = render_uart(uart_frame(words), args.format or "bin")
            if args.output:
                Path(args.output).write_bytes(data)
            else:
                sys.stdout.buffer.write(data)
            return 0
        if args.format in ("bin", "hex"):
            raise LoadSeqError("--format %s is a UART frame format: add --uart" % args.format)
        steps = generate_steps(words)
    except (LoadSeqError, OSError) as exc:
        print("loadseq: error: %s" % exc, file=sys.stderr)
        return 2
    text = (to_json if (args.format or "json") == "json" else to_python)(words, steps)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
