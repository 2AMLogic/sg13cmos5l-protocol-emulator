#!/usr/bin/env python3
"""Offline: check the "Current reading" digest atop spec/gap-to-submission.md.

The tracker's long row cells are an append-only history, so a short digest
sits above them (issue #282). A hand-written digest rots unless something
checks it; this does, with no network (`npm run lint` runs it).

What it checks
    1. A `## Current reading` section exists and holds a table.
    2. The main table (the first table under `## Spec rows`) has rows 1..N,
       numbered consecutively; N is derived from it, not hard-coded.
    3. Every row 1..N has exactly one digest line; no digest line names a
       row outside 1..N.
    4. Each digest line has a state in {met, unmet, proposed}, a non-empty
       blocking reason, an `Open issues` cell that is `none` or a comma
       list of `#N`, and a link whose text is `row <that number>` and whose
       target is the `## Spec rows` heading's anchor.

Whether the cited issues are still open needs the forge:
`scripts/check_docs_issue_states.py --digest` does that, on demand.

Usage: python3 scripts/check_gap_digest.py [PATH]
Exit codes: 0 ok, 1 problems found. Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "spec" / "gap-to-submission.md"
STATES = {"met", "unmet", "proposed"}
DIGEST_HEADING = "Current reading"
ROWS_HEADING_PREFIX = "Spec rows"
LINK_RE = re.compile(r"^\[([^\]]*)\]\(#([^)]*)\)$")
ISSUES_RE = re.compile(r"^#\d+(, #\d+)*$")


def slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation, spaces to hyphens."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def sections(text: str) -> dict[str, list[str]]:
    """Map each `## ` heading to the lines under it (until the next `## `)."""
    out: dict[str, list[str]] = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def first_table(lines: list[str]) -> list[list[str]]:
    """Cells of the first table's data rows (header and separator dropped)."""
    rows: list[list[str]] = []
    started = False
    for line in lines:
        if line.lstrip().startswith("|"):
            started = True
            rows.append(split_row(line))
        elif started:
            break
    return rows[2:]


def check(text: str) -> list[str]:
    errs: list[str] = []
    secs = sections(text)
    digest = secs.get(DIGEST_HEADING)
    if digest is None:
        return [f"no `## {DIGEST_HEADING}` section"]
    rows_heading = next((h for h in secs if h.startswith(ROWS_HEADING_PREFIX)), None)
    if rows_heading is None:
        return [f"no `## {ROWS_HEADING_PREFIX}` section"]
    anchor = slug(rows_heading)

    main_nums: list[int] = []
    for cells in first_table(secs[rows_heading]):
        if cells and cells[0].isdigit():
            main_nums.append(int(cells[0]))
        else:
            errs.append(f"main table: row number cell {cells[:1]!r} is not a number")
    if not main_nums:
        return errs + ["main table: no rows found"]
    n = len(main_nums)
    if main_nums != list(range(1, n + 1)):
        errs.append(f"main table: rows are {main_nums}, expected 1..{n} in order")

    lines = first_table(digest)
    if not lines:
        return errs + [f"`## {DIGEST_HEADING}` holds no table rows"]
    seen: dict[int, int] = {}
    for cells in lines:
        if len(cells) != 5:
            errs.append(f"digest line {cells[:1]}: expected 5 cells, found {len(cells)}")
            continue
        num_s, state, reason, issues, link = cells
        if not num_s.isdigit():
            errs.append(f"digest line {num_s!r}: row number is not a number")
            continue
        num = int(num_s)
        seen[num] = seen.get(num, 0) + 1
        if not 1 <= num <= n:
            errs.append(f"digest row {num}: outside the main table's rows 1..{n}")
        if state not in STATES:
            errs.append(f"digest row {num}: state {state!r} not one of {sorted(STATES)}")
        if not reason:
            errs.append(f"digest row {num}: empty blocking reason")
        if issues != "none" and not ISSUES_RE.match(issues):
            errs.append(f"digest row {num}: open issues {issues!r} is not `none` or `#N, #M`")
        m = LINK_RE.match(link)
        if not m or m.group(1) != f"row {num}":
            errs.append(f"digest row {num}: link {link!r} is not `[row {num}](#...)`")
        elif m.group(2) != anchor:
            errs.append(f"digest row {num}: link target #{m.group(2)} does not resolve to #{anchor}")
    for num in range(1, n + 1):
        if seen.get(num, 0) == 0:
            errs.append(f"digest row {num}: missing")
        elif seen[num] > 1:
            errs.append(f"digest row {num}: {seen[num]} lines, expected exactly one")
    return errs


def digest_issues(text: str) -> list[tuple[int, int]]:
    """(row, issue number) for every `#N` in the digest's `Open issues` cells."""
    out = []
    for cells in first_table(sections(text).get(DIGEST_HEADING, [])):
        if len(cells) == 5 and cells[0].isdigit():
            out += [(int(cells[0]), int(i)) for i in re.findall(r"#(\d+)", cells[3])]
    return out


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    errs = check(path.read_text(encoding="utf-8"))
    for e in errs:
        print(f"ERROR {path.name}: {e}")
    if errs:
        return 1
    print(f"ok: {path.name} current-reading digest covers every row")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
