#!/usr/bin/env python3
"""Self-test for `firmware/tools/gen_boot_rom.py` (issue #138).

The generator is the hex -> Verilog link of DR 0013 layer 2's chain
(`spec/decision-records/0013-program-loading.md`: "The ROM netlist is
generated from that image", "capped at 128 words" (see F2)). These cases check the
link itself: what it accepts, what it refuses, that its output is a pure
function of the image, and that `--check` reports a stale ROM. Whether the
generated ROM *behaves* is `verification/test_boot_rom.py`'s subject.

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 firmware/tools/test_gen_boot_rom.py
Exit codes: 0 all cases pass, 1 at least one failed.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_boot_rom as gen  # noqa: E402  (path-shimmed sibling import)

FAILURES = []


def check(name, fn):
    try:
        fn()
    except AssertionError as err:
        FAILURES.append(name)
        print(f"FAIL {name}: {err}")
    except Exception as err:  # noqa: BLE001 - a crash is a failure
        FAILURES.append(name)
        print(f"FAIL {name}: unexpected {type(err).__name__}: {err}")
    else:
        print(f"pass {name}")


def hex_of(words):
    return "".join(f"{w:04X}\n" for w in words)


def table_of(verilog):
    """address -> word, read back out of a rendered module."""
    return {int(a, 16): int(w, 16)
            for a, w in re.findall(r"8'h([0-9A-F]{2}): word = 16'h([0-9A-F]{4});", verilog)}


def expect_rom_error(text, needle):
    try:
        gen.parse_hex(text)
    except gen.RomError as err:
        assert needle in str(err), f"error {str(err)!r} missing {needle!r}"
        return
    raise AssertionError(f"expected a RomError containing {needle!r}")


def run_main(argv):
    """main() with its output captured: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = gen.main(argv)
    return rc, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def scratch_paths(words):
    """Point the generator at a scratch image and ROM, restoring it after."""
    saved = (gen.ROOT, gen.HEX_PATH, gen.ASM_PATH, gen.OUT_PATH)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "firmware" / "build" / "boot").mkdir(parents=True)
        (root / "rtl").mkdir()
        gen.ROOT = root
        gen.HEX_PATH = root / "firmware" / "build" / "boot" / "boot_rom.hex"
        gen.ASM_PATH = root / "firmware" / "asm" / "boot" / "boot_rom.asm"
        gen.OUT_PATH = root / "rtl" / "protocol_boot_rom.v"
        if words is not None:
            gen.HEX_PATH.write_text(hex_of(words), encoding="utf-8")
        try:
            yield root
        finally:
            gen.ROOT, gen.HEX_PATH, gen.ASM_PATH, gen.OUT_PATH = saved


def test_parse_accepts_an_image():
    assert gen.parse_hex("9000\nF000\nabcd\n") == [0x9000, 0xF000, 0xABCD]


def test_parse_rejects_malformed_lines():
    expect_rom_error("9000\nF00\n", "line 2")          # 3 digits
    expect_rom_error("9000\n0xF000\n", "line 2")       # a prefix
    expect_rom_error("9000\n\nF000\n", "line 2")       # a blank line
    expect_rom_error("9000 F000\n", "line 1")          # two words on a line
    expect_rom_error("GHIJ\n", "line 1")


def test_parse_rejects_an_empty_image():
    expect_rom_error("", "empty")


def test_cap_is_the_fetch_address_space():
    """DR 0013 proposed 128; the UART load does not fit (finding F2, issue
    #139), so the cap is the 8-bit fetch address space until the record
    decides. 256 is in, 257 is out."""
    assert gen.ROM_WORDS_MAX == 256
    assert len(gen.parse_hex(hex_of([0x0000] * 256))) == 256
    expect_rom_error(hex_of([0x0000] * 257), "capped at 256")


def test_render_carries_every_word_at_its_address():
    words = [0x9000, 0x1460, 0xD00B, 0xF000, 0xA805]
    table = table_of(gen.render(words, hex_of(words)))
    assert table == dict(enumerate(words)), table


def test_render_outside_the_image_is_halt():
    words = [0x0000, 0x0000]
    text = gen.render(words, hex_of(words))
    assert "default: word = 16'hF000;" in text
    assert gen.HALT_WORD == 0xF000  # DR 0001 opcode 1111


def test_render_is_registered_once_with_a_reset():
    text = gen.render([0x0000], hex_of([0x0000]))
    assert text.count("always @(posedge clk or negedge rst_n)") == 1
    assert "data <= 16'h0000;" in text and "data <= word;" in text
    assert "module protocol_boot_rom (" in text


def test_render_is_deterministic_and_pathless():
    words = [0x1234, 0xF000]
    first = gen.render(words, hex_of(words))
    assert first == gen.render(list(words), hex_of(words))
    assert str(gen.ROOT) not in first, "the generated ROM names an absolute path"
    assert "GENERATED FILE -- DO NOT EDIT" in first


def test_render_changes_with_the_image():
    a = gen.render([0x1234], hex_of([0x1234]))
    b = gen.render([0x1235], hex_of([0x1235]))
    assert a != b and table_of(a) != table_of(b)


def test_write_then_check_round_trip():
    with scratch_paths([0x9000, 0xF000]):
        rc, out, _ = run_main([])
        assert rc == 0 and "2 of 256 words" in out, (rc, out)
        assert table_of(gen.OUT_PATH.read_text()) == {0: 0x9000, 1: 0xF000}
        rc, out, _ = run_main(["--check"])
        assert rc == 0 and out.startswith("OK:"), (rc, out)


def test_check_reports_a_stale_rom():
    """The image changed and the ROM was not regenerated."""
    with scratch_paths([0x9000, 0xF000]):
        assert run_main([])[0] == 0
        gen.HEX_PATH.write_text(hex_of([0x9000, 0x0000]), encoding="utf-8")
        rc, _, err = run_main(["--check"])
        assert rc == 1 and "does not match" in err, (rc, err)


def test_check_reports_a_hand_edited_rom():
    with scratch_paths([0x9000, 0xF000]):
        assert run_main([])[0] == 0
        text = gen.OUT_PATH.read_text()
        gen.OUT_PATH.write_text(text.replace("16'h9000", "16'h9001"), encoding="utf-8")
        rc, _, err = run_main(["--check"])
        assert rc == 1 and "does not match" in err, (rc, err)


def test_check_reports_a_missing_rom_and_a_missing_image():
    with scratch_paths([0x9000]):
        rc, _, err = run_main(["--check"])
        assert rc == 1 and "is missing" in err, (rc, err)
    with scratch_paths(None):
        rc, _, err = run_main([])
        assert rc == 1 and "does not exist" in err, (rc, err)


def test_an_oversized_image_writes_nothing():
    with scratch_paths([0x0000] * 257):
        rc, _, err = run_main([])
        assert rc == 1 and "capped at 256" in err, (rc, err)
        assert not gen.OUT_PATH.exists(), "an over-cap image still produced a ROM"


def test_usage_error():
    rc, _, err = run_main(["--bogus"])
    assert rc == 2 and "usage" in err


def test_committed_rom_is_fresh():
    """The repository's own chain, hex -> Verilog."""
    rc, out, err = run_main(["--check"])
    assert rc == 0, err
    words = gen.parse_hex(gen.HEX_PATH.read_text(encoding="utf-8"))
    assert table_of(gen.OUT_PATH.read_text(encoding="utf-8")) == dict(enumerate(words))


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            check(name, fn)
    total = sum(1 for n, f in globals().items() if n.startswith("test_") and callable(f))
    if FAILURES:
        print(f"\n{len(FAILURES)} of {total} cases FAILED: {', '.join(FAILURES)}")
        return 1
    print(f"\nall {total} cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
