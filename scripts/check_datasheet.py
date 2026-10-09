#!/usr/bin/env python3
"""Drift check: docs/info.md "Protocols as firmware" table vs the firmware tree (issue #110).

Fails (exit 1) when the image table between the
`<!-- firmware-images:begin -->` / `<!-- firmware-images:end -->` markers
disagrees with the repository:

  1. the set of table images must equal the set of `firmware/asm/*.asm`
     stems, and each must have `firmware/build/<stem>.hex` and
     `firmware/build/<stem>.cycles.txt` (and no build artefact may exist
     without a source);
  2. each row's Words / Total cycles must equal the committed
     `<stem>.cycles.txt` header (`WORDS n`, `TOTAL-CYCLES n`);
  3. every relative link in a row (source, bench, record) must resolve to an
     existing file, and the row's source link must point at its own .asm.

It never rewrites anything. Stdlib only. Same style as the other scripts/
checkers (exit 0 clean, 1 on drift, messages on stderr/stdout).

    python3 scripts/check_datasheet.py [--root DIR]
"""
import argparse
import re
import sys
from pathlib import Path

BEGIN = "<!-- firmware-images:begin -->"
END = "<!-- firmware-images:end -->"
LINK = re.compile(r"\]\(([^)]+)\)")
IMAGE = re.compile(r"^\|\s*\[`([^`]+)`\]\(([^)]+)\)")


def check(root: Path) -> list:
    """Return a list of human-readable drift errors (empty = in step)."""
    errs = []
    info = root / "docs" / "info.md"
    if not info.is_file():
        return [f"{info}: missing"]
    text = info.read_text()
    if BEGIN not in text or END not in text or text.index(BEGIN) > text.index(END):
        return [f"{info}: firmware-images begin/end markers missing or misordered"]
    block = text[text.index(BEGIN) + len(BEGIN):text.index(END)]
    rows = {}
    for line in block.splitlines():
        m = IMAGE.match(line.strip())
        if not m:
            continue
        name = m.group(1)
        if name in rows:
            errs.append(f"table: image `{name}` listed more than once")
        rows[name] = (m.group(2), [c.strip() for c in line.strip().strip("|").split("|")], line)

    asm = {p.stem for p in (root / "firmware" / "asm").glob("*.asm")}
    build = root / "firmware" / "build"
    hexes = {p.stem for p in build.glob("*.hex")}
    reports = {p.name[: -len(".cycles.txt")] for p in build.glob("*.cycles.txt")}

    for n in sorted(asm - set(rows)):
        errs.append(f"firmware/asm/{n}.asm is committed but has no row in docs/info.md")
    for n in sorted(set(rows) - asm):
        errs.append(f"docs/info.md lists `{n}` but firmware/asm/{n}.asm does not exist")
    for n in sorted(asm):
        if n not in hexes:
            errs.append(f"firmware/build/{n}.hex missing")
        if n not in reports:
            errs.append(f"firmware/build/{n}.cycles.txt missing")
    for n in sorted((hexes | reports) - asm):
        errs.append(f"firmware/build artefact for `{n}` has no firmware/asm/{n}.asm")

    for n, (src_link, cells, line) in sorted(rows.items()):
        if Path(src_link).name != f"{n}.asm":
            errs.append(f"`{n}`: source link {src_link} does not point at {n}.asm")
        for link in LINK.findall(line):
            if link.startswith(("http://", "https://", "#")):
                continue
            if not (info.parent / link).resolve().is_file():
                errs.append(f"`{n}`: link target {link} does not exist")
        rep = build / f"{n}.cycles.txt"
        if not rep.is_file():
            continue
        words = re.search(r"^WORDS (\d+)$", rep.read_text(), re.M)
        total = re.search(r"^TOTAL-CYCLES (\d+)$", rep.read_text(), re.M)
        # cells: image, protocol, rate, words, total cycles, bench, record
        if len(cells) < 7:
            errs.append(f"`{n}`: expected 7 columns, found {len(cells)}")
            continue
        if not words or cells[3] != words.group(1):
            errs.append(f"`{n}`: Words {cells[3]} != cycle report {words and words.group(1)}")
        if not total or cells[4] != total.group(1):
            errs.append(f"`{n}`: Total cycles {cells[4]} != cycle report {total and total.group(1)}")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args(argv)
    errs = check(args.root)
    for e in errs:
        print(f"check_datasheet: {e}", file=sys.stderr)
    print(f"check_datasheet: {len(errs)} drift error(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
