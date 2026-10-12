#!/usr/bin/env python3
"""Fail when a judge-facing document cites a superseded or missing record.

`docs/submission/*.md` is read by people who do not open the record tree. A
record id cited there must name a *live* record: one that no other record of
the same experiment lists in its `supersedes` field. Re-mints make older
records superseded (they are kept, append-only), so a document that cites one
quietly reports stale numbers (#238).

What counts as a citation: any record id (`YYYYMMDD-HHMMSS-<7 hex>`) in a
line of a `*.md` file directly under the docs directory. If the id is in a
link of the form `.../records/<experiment>/records/<id>.md` the experiment
comes from the link; otherwise the id must be live in every experiment that
has a record with that id.

A line that deliberately tells history (for example the story of a failed
record that was later superseded) may carry the marker
`<!-- superseded-ok: <reason> -->`; the marker covers superseded ids on that
line only, never an id that does not exist, and the reason must be non-empty.

Usage:
    python3 verification/check_docs_records.py [--docs DIR] [--records DIR]
Exit codes: 0 clean, 1 at least one bad citation.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS = REPO_ROOT / "docs" / "submission"
DEFAULT_RECORDS = REPO_ROOT / "verification" / "records"

ID_RE = re.compile(r"(?<![0-9A-Za-z-])(\d{8}-\d{6}-[0-9a-f]{7})(?![0-9A-Za-z-])")
LINK_RE = re.compile(r"records/([A-Za-z0-9_.-]+)/records/(\d{8}-\d{6}-[0-9a-f]{7})\.md")
OK_RE = re.compile(r"<!--\s*superseded-ok:\s*(\S.*?)\s*-->")
META_RE = re.compile(r"<!--\s*record-meta\s*(.*?)-->", re.DOTALL)


def load_records(records_root: Path):
    """Return (all_ids, superseded) as sets of (experiment, id)."""
    all_ids: set = set()
    superseded: set = set()
    for path in sorted(records_root.glob("*/records/*.md")):
        experiment = path.parent.parent.name
        all_ids.add((experiment, path.stem))
        m = META_RE.search(path.read_text(encoding="utf-8"))
        if not m:
            continue
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue  # check_records.py reports malformed records
        target = meta.get("supersedes")
        if isinstance(target, str) and target not in ("", "none"):
            superseded.add((experiment, target))
    return all_ids, superseded


def check_text(name: str, text: str, all_ids: set, superseded: set) -> list[str]:
    errors = []
    for lineno, line in enumerate(text.splitlines(), 1):
        ok = OK_RE.search(line)
        linked = {rid: exp for exp, rid in LINK_RE.findall(line)}
        for rid in dict.fromkeys(ID_RE.findall(line)):
            if rid in linked:
                homes = [linked[rid]]
            else:
                homes = sorted(e for e, i in all_ids if i == rid)
            homes = [e for e in homes if (e, rid) in all_ids]
            if not homes:
                errors.append(f"{name}:{lineno}: cites `{rid}`, which is not a record")
                continue
            for exp in homes:
                if (exp, rid) in superseded and not ok:
                    errors.append(
                        f"{name}:{lineno}: cites `{rid}` ({exp}), which a later "
                        f"record supersedes; cite the live record, or mark a "
                        f"deliberate historical citation with "
                        f"`<!-- superseded-ok: reason -->`"
                    )
        if "superseded-ok" in line and not ok:
            errors.append(f"{name}:{lineno}: `superseded-ok` marker needs a reason")
    return errors


def check(docs: Path, records: Path) -> list[str]:
    all_ids, superseded = load_records(records)
    errors: list[str] = []
    for path in sorted(docs.glob("*.md")):
        errors += check_text(path.name, path.read_text(encoding="utf-8"), all_ids, superseded)
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--docs", type=Path, default=DEFAULT_DOCS)
    ap.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    args = ap.parse_args()
    errors = check(args.docs, args.records)
    for e in errors:
        print(f"FAIL: {e}")
    if errors:
        print(f"\n{len(errors)} bad record citation(s) in {args.docs}")
        return 1
    print(f"PASS: every record cited under {args.docs} is live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
