#!/usr/bin/env python3
"""Self-test for `firmware/tools/mkflash.py` (issue #140): the flash image
the SPI-flash boot loads. Stdlib only. Exit 0 = all pass."""

from __future__ import annotations

import binascii
import contextlib
import io
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import mkflash  # noqa: E402

REPO = SCRIPT_DIR.parent.parent
FAILURES = []


def check(name, fn):
    try:
        fn()
    except (AssertionError, SystemExit) as err:
        FAILURES.append(name)
        print(f"FAIL {name}: {err}")
    else:
        print(f"ok   {name}")


def expect_exit(fn, needle):
    try:
        fn()
    except SystemExit as err:
        assert needle in str(err), f"{err!r} does not mention {needle!r}"
        return
    raise AssertionError(f"expected a refusal mentioning {needle!r}")


def t_layout():
    words = [0x1234, 0xABCD, 0x0001]
    data = mkflash.build(words)
    assert len(data) == 512
    assert data[:6] == bytes([0x12, 0x34, 0xAB, 0xCD, 0x00, 0x01]), "words are high byte first"
    assert data[6:510] == bytes(504), "default filler is zero words"
    assert int.from_bytes(data[510:], "big") == binascii.crc_hqx(data[:510], 0), "word 255 = CRC of words 0..254"
    assert binascii.crc_hqx(data, 0) == 0, "the whole image runs the CRC to zero (what the boot checks)"
    assert mkflash.check(data) == []


def t_filler():
    data = mkflash.build([0x1111], filler=0xBEEF)
    assert data[2:4] == bytes([0xBE, 0xEF]) and data[508:510] == bytes([0xBE, 0xEF])
    assert mkflash.check(data) == []


def t_committed_images():
    for hex_path in sorted((REPO / "firmware" / "build").glob("*.hex")):
        words = mkflash.read_hex(hex_path)
        if len(words) > mkflash.BODY_WORDS:
            continue
        assert mkflash.check(mkflash.build(words)) == [], hex_path


def t_too_long():
    expect_exit(lambda: mkflash.build([0] * 256), "at most 255")
    mkflash.build([0x0001] * 255)


def t_zero_signature_refused():
    # find a one-word program whose padded image has CRC 0x0000
    for value in range(0x10000):
        body = [value] + [0] * 254
        if mkflash.crc16(body) == 0:
            expect_exit(lambda: mkflash.build([value]), "0x0000")
            break
    else:
        raise AssertionError("no word gives a zero signature")
    data = bytearray(mkflash.build([0x4242]))
    data[510:] = b"\x00\x00"
    assert any("0x0000" in p or "signature" in p for p in mkflash.check(bytes(data)))


def t_check_catches_damage():
    data = bytearray(mkflash.build([0x1234, 0x5678]))
    for index in (0, 100, 509, 511):
        bad = bytearray(data)
        bad[index] ^= 0x10
        assert mkflash.check(bytes(bad)), f"damage at byte {index} not seen"
    assert mkflash.check(bytes(data[:-1])), "a short image passed"
    assert mkflash.check(bytes(data) + b"\x00"), "a long image passed"


def t_cli():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "p.hex"
        src.write_text("1234\nabcd\n\n", encoding="utf-8")
        out = Path(tmp) / "p.bin"
        with contextlib.redirect_stdout(io.StringIO()):
            assert mkflash.main([str(src), "-o", str(out)]) == 0
            assert mkflash.main(["--check", str(out)]) == 0
        assert out.read_bytes()[:4] == bytes([0x12, 0x34, 0xAB, 0xCD])
        out.write_bytes(out.read_bytes()[:-1] + b"\x00")
        with contextlib.redirect_stderr(io.StringIO()):
            assert mkflash.main(["--check", str(out)]) == 1
        src.write_text("12zz\n", encoding="utf-8")
        expect_exit(lambda: mkflash.read_hex(src), "malformed")


for name, fn in sorted(globals().items()):
    if name.startswith("t_"):
        check(name[2:], fn)
if FAILURES:
    print(f"{len(FAILURES)} FAILED")
    sys.exit(1)
print("all passed")
