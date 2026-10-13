#!/usr/bin/env python3
"""Offline: keep the second ratification batch honest (issue #299).

`spec/ratification-batch-2.md` lists every still-`Proposed` decision record
and the unratified rows, each with a ratify / amend first / defer
recommendation. It is a worksheet for the human two-key act, not a ratifier:
this script never reads or writes a `Status:` line other than to classify it.

What it checks
    1. Every DR cited by number in the RTL (`rtl/*.v`, `src/*.v`, symlinks
       resolved once) is `Ratified` or has a `DR NNNN` line in the batch file.
       A citation is `DR 0012`, `DR-0012`, `DRs 0001, 0005 and 0012`,
       `decision record 0012` or a `decision-records/0012-...` path.
    2. Every `Proposed` DR under `spec/decision-records/` has a line in the
       batch file (records whose Status is `Recorded` need no key).
    3. Every batch line's item names an existing DR (or `row N`), appears
       once, and its recommendation is `ratify`, `amend first` or `defer`.

Whether the prose in the cells is true is the reviewer's job.

Usage: python3 scripts/check_ratification_batch.py [BATCH_PATH]
Exit codes: 0 ok, 1 problems found. Standard library only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BATCH = REPO_ROOT / "spec" / "ratification-batch-2.md"
DR_DIR = REPO_ROOT / "spec" / "decision-records"
RTL_GLOBS = ("rtl/*.v", "src/*.v")
RECOMMENDATIONS = {"ratify", "amend first", "defer"}

CITE_LIST_RE = re.compile(r"\bDRs?[\s-]*(\d{4}(?:\s*(?:,|/|and|&)\s*\d{4})*)")
CITE_PROSE_RE = re.compile(r"\bdecision[\s-]records?\s+(\d{4})", re.IGNORECASE)
CITE_PATH_RE = re.compile(r"decision-records/(\d{4})-")
NEGATION_RE = re.compile(r"\b(not|never|un-?)\s*ratified\b|\bnot in force\b")


def rtl_citations(text: str) -> set[str]:
    out: set[str] = set()
    for m in CITE_LIST_RE.finditer(text):
        out.update(re.findall(r"\d{4}", m.group(1)))
    out.update(CITE_PROSE_RE.findall(text))
    out.update(CITE_PATH_RE.findall(text))
    return out


def dr_state(text: str) -> str:
    """`ratified`, `proposed` or `other` from the record's first `Status:` line."""
    m = re.search(r"^Status:[ \t]*(.*)$", text, re.MULTILINE)
    if not m:
        return "other"
    value = re.sub(r"[*_`]", "", m.group(1)).strip().lower()
    if value.startswith("ratified") and not NEGATION_RE.search(value):
        return "ratified"
    if value.startswith("proposed"):
        return "proposed"
    return "other"


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def batch_items(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """(item, recommendation) for each table row whose item is `DR N` or `row N`."""
    errs: list[str] = []
    items: list[tuple[str, str]] = []
    rec_col = None
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            rec_col = None
            continue
        cells = split_row(line)
        if cells and cells[0].lower() == "item":
            lowered = [c.lower() for c in cells]
            rec_col = lowered.index("recommendation") if "recommendation" in lowered else None
            if rec_col is None:
                errs.append("table with an `Item` column has no `Recommendation` column")
            continue
        if re.fullmatch(r"-+", cells[0].replace(":", "")) or rec_col is None:
            continue
        if re.fullmatch(r"(DR \d{4}|row \d+)", cells[0]):
            rec = cells[rec_col].lower() if len(cells) > rec_col else ""
            items.append((cells[0], rec))
    return items, errs


def check(batch_text: str, dr_states: dict[str, str], cited: dict[str, set[str]]) -> list[str]:
    """`cited` maps DR number -> files citing it; `dr_states` maps number -> state."""
    items, errs = batch_items(batch_text)
    seen: dict[str, int] = {}
    listed: set[str] = set()
    for item, rec in items:
        seen[item] = seen.get(item, 0) + 1
        if rec not in RECOMMENDATIONS:
            errs.append(f"{item}: recommendation {rec!r} is not one of {sorted(RECOMMENDATIONS)}")
        if item.startswith("DR "):
            num = item[3:]
            listed.add(num)
            if num not in dr_states:
                errs.append(f"{item}: no such decision record")
    for item, n in seen.items():
        if n > 1:
            errs.append(f"{item}: listed {n} times, expected once")
    for num in sorted(cited):
        if num not in dr_states:
            errs.append(f"DR {num} is cited in {sorted(cited[num])} but no such record exists")
        elif dr_states[num] != "ratified" and num not in listed:
            errs.append(
                f"DR {num} is cited in {sorted(cited[num])} but is not Ratified "
                f"and is not listed in the batch file"
            )
    for num, state in sorted(dr_states.items()):
        if state == "proposed" and num not in listed and num not in cited:
            errs.append(f"DR {num} is Proposed but is not listed in the batch file")
    return errs


def load_states(dr_dir: Path) -> dict[str, str]:
    return {
        p.name[:4]: dr_state(p.read_text(encoding="utf-8"))
        for p in sorted(dr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    }


def load_citations(root: Path) -> dict[str, set[str]]:
    cited: dict[str, set[str]] = {}
    seen: set[Path] = set()
    for pattern in RTL_GLOBS:
        for p in sorted(root.glob(pattern)):
            real = p.resolve()
            if real in seen:
                continue
            seen.add(real)
            for num in rtl_citations(real.read_text(encoding="utf-8")):
                cited.setdefault(num, set()).add(str(real.relative_to(root.resolve())))
    return cited


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_BATCH
    errs = check(path.read_text(encoding="utf-8"), load_states(DR_DIR), load_citations(REPO_ROOT))
    for e in errs:
        print(f"ERROR {path.name}: {e}")
    if errs:
        return 1
    print(f"ok: {path.name} lists every Proposed DR and every non-Ratified DR the RTL cites")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
