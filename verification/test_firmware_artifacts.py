#!/usr/bin/env python3
"""Simulator-free tests for `firmware_artifacts.py` (issue #115).

Run directly or under pytest. Covers parser edge cases and that every
committed UART/roundtrip/SPI/I2C artifact parses to the same values via the
shared readers and via each bench's own wrapper (per-mode selection).
"""

import re
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import firmware_artifacts as fa  # noqa: E402

BUILD = REPO / "firmware" / "build"
SPI_MODES = (0, 1, 2, 3)
I2C_STEMS = ("i2c_std", "i2c_fast")


def _write(text):
    d = Path(tempfile.mkdtemp())
    p = d / "x.hex"
    p.write_text(text, encoding="utf-8")
    return p


def test_hex_blank_and_whitespace_lines():
    p = _write("\n  1a2B \n\n\t0000\r\n   \nffff\n")
    assert fa.parse_hex_image(p) == [0x1A2B, 0, 0xFFFF]


def test_hex_malformed_names_file_and_line():
    p = _write("1234\nzzzz\n")
    with pytest.raises(ValueError, match=r"x\.hex:2.*zzzz"):
        fa.parse_hex_image(p)


@pytest.mark.parametrize("text", ["", "\n  \n\t\n"])
def test_hex_empty_rejected(text):
    p = _write(text)
    with pytest.raises(AssertionError, match="empty"):
        fa.parse_hex_image(p)


REPORT = """\
; header noise
CYCLES name=a start=0 end=3 cycles=4 branches=false
CYCLES name=b start=4 end=9 cycles=12 branches=true
  CYCLES name=indented start=1 end=2 cycles=3 branches=true
CYCLES name=bad start=x end=2 cycles=3 branches=true
CYCLES name=trail start=1 end=2 cycles=3 branches=true extra
CYCLES name=a start=10 end=11 cycles=2 branches=true
TOTAL-CYCLES 18
"""


def test_sections_fields_tokens_and_ignored_lines():
    s = fa.parse_cycle_sections(REPORT)
    assert set(s) == {"a", "b"}
    assert s["b"] == (4, 9, 12, "true")
    assert isinstance(s["b"][3], str)


def test_sections_duplicate_last_wins():
    assert fa.parse_cycle_sections(REPORT)["a"] == (10, 11, 2, "true")


def test_sections_empty():
    assert fa.parse_cycle_sections("") == {}


def test_total_cycles():
    assert fa.total_cycles(REPORT) == 18


def test_total_cycles_missing_is_assertion():
    with pytest.raises(AssertionError, match="TOTAL-CYCLES"):
        fa.total_cycles("CYCLES name=a start=0 end=1 cycles=2 branches=false\n")
    with pytest.raises(AssertionError):
        fa.total_cycles("  TOTAL-CYCLES 5\nTOTAL-CYCLES x\n")


def _committed_pairs():
    return sorted(BUILD.glob("*.cycles.txt"))


@pytest.mark.parametrize("report", _committed_pairs(), ids=lambda p: p.name)
def test_committed_reports_parse(report):
    text = report.read_text(encoding="utf-8")
    sections = fa.parse_cycle_sections(text)
    for start, end, cycles, branches in sections.values():
        assert branches in ("true", "false")
        assert 0 <= start <= end and cycles > 0
    assert fa.total_cycles(text) > 0
    hexfile = report.with_name(report.name.replace(".cycles.txt", ".hex"))
    assert len(fa.parse_hex_image(hexfile)) == int(
        re.search(r"^WORDS (\d+)$", text, re.M).group(1)
    )


def test_per_mode_selection_uses_each_modes_own_files():
    sys.path.insert(0, str(HERE))
    # Import the bench modules only for their pure wrappers (needs cocotb
    # importable; skip otherwise).
    pytest.importorskip("cocotb")
    import test_firmware_spi as spi
    import test_firmware_i2c as i2c
    import test_firmware_uart as uart
    import test_firmware_roundtrip as rt

    for m in SPI_MODES:
        text = (BUILD / f"spi_mode{m}.cycles.txt").read_text(encoding="utf-8")
        assert spi.committed_total_cycles(m) == fa.total_cycles(text)
        assert spi.parse_cycle_sections(m) == fa.parse_cycle_sections(text)
        assert spi.load_hex(m) == fa.parse_hex_image(BUILD / f"spi_mode{m}.hex")
    for mode in i2c.MODES:
        text = (REPO / mode.cycles).read_text(encoding="utf-8")
        assert i2c.parse_cycle_sections(mode) == fa.parse_cycle_sections(text)
        assert i2c.committed_total_cycles(mode) == fa.total_cycles(text)
        assert i2c.load_committed_image(mode) == fa.parse_hex_image(REPO / mode.hex)

    text = (BUILD / "uart_tx.cycles.txt").read_text(encoding="utf-8")
    assert uart.parse_cycle_sections() == fa.parse_cycle_sections(text)
    assert uart.committed_total_cycles() == fa.total_cycles(text)
    assert uart.load_committed_image() == fa.parse_hex_image(BUILD / "uart_tx.hex")

    text = (BUILD / "demo_roundtrip.cycles.txt").read_text(encoding="utf-8")
    shared = fa.parse_cycle_sections(text)
    local = rt.parse_cycle_sections()
    assert local == {k: v[:3] for k, v in shared.items()}
    assert all(len(v) == 3 for v in local.values())
    start, end, cycles = local["banner"]
    assert rt.load_committed_image() == fa.parse_hex_image(
        BUILD / "demo_roundtrip.hex"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
