#!/usr/bin/env python3
"""Self-test for `firmware/tools/loadseq.py` (issue #139). Stdlib only.

The frame is checked against `binascii.crc_hqx` (the standard library's
CRC-16/XMODEM), not against loadseq's own arithmetic, and against the fixed
shape DR 0013 gives: 0xA5, N-1, 2N bytes big-endian, CRC high byte first.
"""

import binascii
import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loadseq  # noqa: E402

FAILED = []


def case(fn):
    try:
        fn()
        print(f"pass {fn.__name__}")
    except Exception as exc:  # noqa: BLE001 - report every failing case
        FAILED.append(fn.__name__)
        print(f"FAIL {fn.__name__}: {exc!r}")
    return fn


@case
def test_crc_matches_the_standard_library():
    assert loadseq.crc16_xmodem(b"123456789") == 0x31C3  # the CRC-16/XMODEM check value
    for data in (b"", b"\x00", b"\xff" * 5, bytes(range(256)), b"\xa5\x00\x12\x34"):
        assert loadseq.crc16_xmodem(data) == binascii.crc_hqx(data, 0), data


@case
def test_frame_shape():
    frame = loadseq.uart_frame([0x1234, 0xABCD, 0x0001])
    assert frame[:2] == bytes((0xA5, 2))
    assert frame[2:8] == bytes((0x12, 0x34, 0xAB, 0xCD, 0x00, 0x01))
    crc = binascii.crc_hqx(frame[2:8], 0)
    assert frame[8:] == bytes((crc >> 8, crc & 0xFF)) and len(frame) == 10


@case
def test_one_word_and_256_words():
    assert len(loadseq.uart_frame([0x0000])) == 2 + 2 + 2
    assert loadseq.uart_frame([0x0000])[1] == 0
    full = loadseq.uart_frame([0xF000] * 256)
    assert full[1] == 0xFF and len(full) == 2 + 512 + 2


@case
def test_the_whole_body_plus_crc_has_zero_residue():
    """The property the chip's check leans on: a message followed by its own
    CRC, high byte first, has CRC zero."""
    frame = loadseq.uart_frame([0x9000, 0x1460, 0xD00B])
    assert binascii.crc_hqx(frame[2:], 0) == 0


@case
def test_bad_sizes_and_bad_hex():
    for words in ([], [0] * 257):
        try:
            loadseq.uart_frame(words)
        except loadseq.LoadseqError:
            continue
        raise AssertionError(f"{len(words)} words were accepted")
    for text in ("", "12\n", "12345\n", "GGGG\n", "0x12\n"):
        try:
            loadseq.parse_hex(text)
        except loadseq.LoadseqError:
            continue
        raise AssertionError(f"{text!r} was accepted")
    assert loadseq.parse_hex("9000\n\nF000\n") == [0x9000, 0xF000]


@case
def test_formats_and_cli():
    frame = loadseq.uart_frame([0x1234])
    assert loadseq.render(frame, "bin") == frame
    assert loadseq.render(frame, "hex").decode().split() == [f"{b:02x}" for b in frame]
    assert bytes.fromhex(loadseq.render(frame, "python").decode().split('"')[1]) == frame
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp, "p.hex"), Path(tmp, "p.bin")
        src.write_text("1234\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            assert loadseq.main(["uart", str(src), "-o", str(out)]) == 0
        assert out.read_bytes() == frame
        src.write_text("zz\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            assert loadseq.main(["uart", str(src)]) == 1
        assert "not a 4-digit hex word" in err.getvalue()


if FAILED:
    print(f"\n{len(FAILED)} case(s) FAILED: {', '.join(FAILED)}")
    sys.exit(1)
print("\nall loadseq cases passed")
