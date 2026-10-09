"""Pure readers for committed firmware artifacts (hex images, cycle reports).

Shared by the firmware benches. cocotb-independent and stateless: callers
choose which file to read; this module only parses.
"""

import re
from pathlib import Path

_CYCLES_LINE = re.compile(
    r"^CYCLES name=(\S+) start=(\d+) end=(\d+) cycles=(\d+) branches=(\S+)$"
)
_TOTAL_LINE = re.compile(r"^TOTAL-CYCLES (\d+)$", re.M)


def parse_hex_image(path) -> list:
    """Parse a hex image: one hexadecimal word per line, blanks skipped.

    Raises ValueError (naming the file and line) on malformed hexadecimal
    and AssertionError if the image holds no words.
    """
    path = Path(path)
    words = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            words.append(int(line, 16))
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: malformed hex word {line!r}") from exc
    assert words, f"committed image {path} is empty"
    return words


def parse_cycle_sections(text: str) -> dict:
    """Map section name -> (start, end, cycles, branches).

    `branches` stays the report's string token ("true"/"false"). Lines that
    do not match the anchored CYCLES format are ignored; a repeated name
    keeps its last entry.
    """
    sections = {}
    for line in text.splitlines():
        match = _CYCLES_LINE.match(line)
        if match:
            name, start, end, cycles, branches = match.groups()
            sections[name] = (int(start), int(end), int(cycles), branches)
    return sections


def total_cycles(text: str) -> int:
    """Extract the report's TOTAL-CYCLES value; absence is an assertion failure."""
    match = _TOTAL_LINE.search(text)
    assert match, "committed report is missing a TOTAL-CYCLES line"
    return int(match.group(1))
