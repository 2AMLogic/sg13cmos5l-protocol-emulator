#!/usr/bin/env python3
"""Non-graded-field movement comparison for `klt signoff` reports (issue #403).

The committed 0.8.0 and 0.9.0 reports share a `source_doc` path, but the
hash changed, T1 items 3, 4, 5, 6, 8 and 11 changed text, and only item 6
changed notes. T1 item 7 also went from unmet to met, raising `t1_met_count`
from 4 to 5. The exit status of `klt signoff --check` tracks graded drift.
Some versions also report wording changes through `doc_drift_fields`.
This helper reads the two reports directly to produce the checklist
comparison required by manifests/README.md's refresh disclosure rule.
Run it on two files or via scripts/signoff-report.sh --diff-vs.

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


def field_text(value: str | list[str]) -> str:
    if isinstance(value, str):
        return value
    return "\n".join(note for note in value if isinstance(note, str))


def excerpt(old: str | list[str], new: str | list[str]) -> list[str]:
    """Show word changes, or the literal formatting when the words match."""
    old_words = field_text(old).split()
    new_words = field_text(new).split()
    if old_words == new_words:
        # JSON displays whitespace escapes and the boundaries between notes.
        # Start near the difference even when the common prefix is long.
        before, after = (json.dumps(value, ensure_ascii=False) for value in (old, new))
        first = next((i for i, (a, b) in enumerate(zip(before, after)) if a != b),
                     min(len(before), len(after)))
        start = max(0, first - 20)
        prefix = "…" if start else ""
        return ["  - " + clip(prefix + before[start:]),
                "  + " + clip(prefix + after[start:])]

    sm = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    lines: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal" or len(lines) >= 2 * EXCERPT_SEGMENTS:
            continue
        if i1 != i2:
            lines.append("  - " + clip(" ".join(old_words[i1:i2])))
        if j1 != j2:
            lines.append("  + " + clip(" ".join(new_words[j1:j2])))
    return lines


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
            old_nt, new_nt = field_text(old_n), field_text(new_n)
            lines.append(
                f"moved {label} notes: {len(old_n)} -> {len(new_n)} note(s), "
                f"{len(old_nt)} -> {len(new_nt)} chars"
            )
            lines.extend(excerpt(old_n, new_n))
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
