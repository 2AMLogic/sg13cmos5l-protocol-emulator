#!/usr/bin/env python3
"""Non-graded-field movement comparison for `klt signoff` reports (issue #403).

`klt signoff --check` compares only graded fields (item status/reason,
citation, `t1_met_count`, ...) and excludes the build block, so a klt move
that changes the checklist a verdict was graded against -- the tiers doc
(`source_doc` / `source_doc_content_hash`), an item's `text`, or an item's
`notes` -- is invisible to the drift gate: the 0.8.0 -> 0.9.0 refresh moved
all of those while every graded field reproduced. This helper computes that
comparison directly from two rendered reports, so a refresh author can
disclose the movement in the signoff-baseline record (the rule is in
manifests/README.md, "The vendored tiers doc -- provenance and refresh
rule") instead of noticing it by hand. scripts/signoff-report.sh --diff-vs
is the wrapper; this module is also runnable directly on two files.

Only non-graded fields are compared: `source_doc`,
`source_doc_content_hash`, per-item `text` and `notes`, and item
presence. Grades, citations, details, counts and the build block are
deliberately ignored -- a pair differing only in those prints the
no-movement line.

Standard library only.

Usage:
    python3 scripts/signoff_movement_diff.py OLD_REPORT.json NEW_REPORT.json

Exit codes:
    0  comparison printed (fields moved or matched -- movement is
       information, not a gate)
    1  usage error, missing/unreadable file, invalid JSON, or a report
       whose `items` cannot be keyed by (tier, id)
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

NO_MOVEMENT = (
    "no non-graded movement: source_doc, source_doc_content_hash, "
    "item text and item notes all unchanged"
)
EXCERPT_SEGMENTS = 3
EXCERPT_WIDTH = 120


class MovementDiffError(Exception):
    """Unusable input -- reported to stderr, exit 1."""


def load_report(path: str) -> dict:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise MovementDiffError(f"cannot read {path}: {e}") from e
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise MovementDiffError(f"{path}: invalid JSON: {e}") from e
    if not isinstance(doc, dict):
        raise MovementDiffError(f"{path}: not a JSON object (a signoff report is)")
    items = doc.get("items")
    if not isinstance(items, list):
        raise MovementDiffError(f"{path}: no 'items' list (not a signoff report?)")
    return doc


def key_items(path: str, report: dict) -> dict[tuple, dict]:
    keyed: dict[tuple, dict] = {}
    for n, item in enumerate(report["items"]):
        if not isinstance(item, dict) or not isinstance(item.get("tier"), str):
            raise MovementDiffError(
                f"{path}: items[{n}] has no string 'tier' (not a signoff report?)"
            )
        tier, id_ = item["tier"], item.get("id")
        if (tier, id_) in keyed:
            show = "id null" if id_ is None else f"id {id_!r}"
            raise MovementDiffError(f"{path}: duplicate item key ({tier}, {show})")
        keyed[(tier, id_)] = item
    return keyed


def item_label(key: tuple) -> str:
    tier, id_ = key
    return f"{tier} item {id_}" if id_ is not None else f"{tier} row (id null)"


def clip(s: str, width: int = EXCERPT_WIDTH) -> str:
    return s if len(s) <= width else s[: width - 1] + "…"

def excerpt(old: str, new: str) -> list[str]:
    """Short word-level diff excerpt; a few changed segments, clipped."""
    sm = difflib.SequenceMatcher(None, old.split(), new.split(), autojunk=False)
    lines: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or len(lines) >= 2 * EXCERPT_SEGMENTS:
            continue
        removed = " ".join(old.split()[i1:i2])
        added = " ".join(new.split()[j1:j2])
        if removed:
            lines.append("  - " + clip(removed))
        if added:
            lines.append("  + " + clip(added))
    return lines


def notes_text(item: dict) -> str:
    notes = item.get("notes") or []
    return "\n".join(n for n in notes if isinstance(n, str))


def compare(old: dict, new: dict) -> list[str]:
    """Output lines for the non-graded movement between two reports."""
    lines: list[str] = []
    for field in ("source_doc", "source_doc_content_hash"):
        a, b = old.get(field), new.get(field)
        if a != b:
            lines.append(f"moved {field}: {a} -> {b}")
    old_items, new_items = key_items("old report", old), key_items("new report", new)

    def sort_key(key: tuple):
        tier, id_ = key
        return (tier, id_ is None, id_ if id_ is not None else 0)

    for key in sorted(set(old_items) & set(new_items), key=sort_key):
        a, b = old_items[key], new_items[key]
        label = item_label(key)
        if a.get("text") != b.get("text"):
            old_t, new_t = a.get("text") or "", b.get("text") or ""
            lines.append(
                f"moved {label} text: {len(old_t)} -> {len(new_t)} chars"
            )
            lines.extend(excerpt(old_t, new_t))
        old_n, new_n = a.get("notes") or [], b.get("notes") or []
        if old_n != new_n:
            old_nt, new_nt = notes_text(a), notes_text(b)
            lines.append(
                f"moved {label} notes: {len(old_n)} -> {len(new_n)} note(s), "
                f"{len(old_nt)} -> {len(new_nt)} chars"
            )
            lines.extend(excerpt(old_nt, new_nt))
    for key in sorted(set(old_items) - set(new_items), key=sort_key):
        lines.append(f"removed {item_label(key)} ({old_items[key].get('title', '?')})")
    for key in sorted(set(new_items) - set(old_items), key=sort_key):
        lines.append(f"added {item_label(key)} ({new_items[key].get('title', '?')})")
    return lines or [NO_MOVEMENT]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] in ("-h", "--help"):
        print(__doc__.strip(), file=sys.stderr)
        return 0 if args and args[0] in ("-h", "--help") else 1
    try:
        old, new = load_report(args[0]), load_report(args[1])
        lines = compare(old, new)
    except MovementDiffError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
