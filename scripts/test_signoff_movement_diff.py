#!/usr/bin/env python3
"""Self-test for scripts/signoff_movement_diff.py.

Run: python3 scripts/test_signoff_movement_diff.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signoff_movement_diff as smd  # noqa: E402

HELPER = Path(__file__).resolve().parent / "signoff_movement_diff.py"


def item(tier="T1", id_=1, text="alpha beta", notes=None, **extra):
    row = {"tier": tier, "id": id_, "title": f"item {id_}", "text": text,
           "notes": notes if notes is not None else []}
    row.update(extra)
    return row


def report(items=None, source_doc="docs/design-evidence-tiers.md",
           content_hash="sha256:aaaa"):
    return {
        "schema_version": 1,
        "block": "b",
        "t1_met_count": 0,
        "source_doc": source_doc,
        "source_doc_content_hash": content_hash,
        "build": {"version": "0.8.0", "git_commit": "c1"},
        "items": items if items is not None else [item()],
    }


def run_cli(*paths):
    return subprocess.run(
        [sys.executable, str(HELPER), *map(str, paths)],
        capture_output=True, text=True,
    )


class Compare(unittest.TestCase):
    def out(self, old, new):
        return "\n".join(smd.compare(old, new))

    def test_identical_reports_no_movement(self):
        self.assertEqual(self.out(report(), report()), smd.NO_MOVEMENT)

    def test_graded_only_changes_are_not_movement(self):
        new = report(items=[item(status="met", reason="why",
                                 citation="sha256:x", detail="d")],
                     )
        new["t1_met_count"] = 5
        new["build"] = {"version": "0.9.0", "git_commit": "c2"}
        self.assertEqual(self.out(report(), new), smd.NO_MOVEMENT)

    def test_source_doc_and_hash_reported_with_values(self):
        new = report(source_doc="other.md", content_hash="sha256:bbbb")
        out = self.out(report(), new)
        self.assertIn("moved source_doc: docs/design-evidence-tiers.md -> other.md", out)
        self.assertIn("moved source_doc_content_hash: sha256:aaaa -> sha256:bbbb", out)

    def test_item_text_change_counts(self):
        old = report(items=[item(id_=3, text="a " * 10)])
        new = report(items=[item(id_=3, text="a " * 10 + "b c")])
        out = self.out(old, new)
        self.assertIn("moved T1 item 3 text: 20 -> 23 chars", out)
        self.assertIn("+ b c", out)

    def test_item_notes_change_counts(self):
        old = report(items=[item(id_=6, notes=[])])
        new = report(items=[item(id_=6, notes=["one two", "three"])])
        out = self.out(old, new)
        self.assertIn("moved T1 item 6 notes: 0 -> 2 note(s), 0 -> 13 chars", out)

    def test_row_order_independent(self):
        old = report(items=[item(id_=1), item(id_=2, text="x")])
        new = report(items=[item(id_=2, text="x"), item(id_=1)])
        self.assertEqual(self.out(old, new), smd.NO_MOVEMENT)

    def test_null_ids_distinct_by_tier(self):
        rows = [item(tier="T2", id_=None, text="t2"),
                item(tier="T3", id_=None, text="t3"),
                item(tier="T4", id_=None, text="t4")]
        new_rows = [item(tier="T2", id_=None, text="t2"),
                    item(tier="T3", id_=None, text="t3 changed"),
                    item(tier="T4", id_=None, text="t4")]
        out = self.out(report(items=rows), report(items=new_rows))
        self.assertIn("moved T3 row (id null) text:", out)
        self.assertNotIn("T2", out.replace("T3", ""))
        self.assertNotIn("T4", out)

    def test_added_removed_items(self):
        old = report(items=[item(id_=1), item(id_=2)])
        new = report(items=[item(id_=1), item(id_=3)])
        out = self.out(old, new)
        self.assertIn("removed T1 item 2 (item 2)", out)
        self.assertIn("added T1 item 3 (item 3)", out)

    def test_excerpt_clipped(self):
        old = report(items=[item(id_=1, text=" ".join(f"w{i}" for i in range(200)))])
        new = report(items=[item(id_=1, text=" ".join(f"w{i}" for i in range(200)) + " tail")])
        for line in self.out(old, new).splitlines():
            if line.startswith("  "):
                self.assertLessEqual(len(line), smd.EXCERPT_WIDTH + 3)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, doc):
        p = self.dir / name
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
        return p

    def test_zero_movement_exit_0(self):
        a = self.write("a.json", report())
        b = self.write("b.json", report())
        r = run_cli(a, b)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), smd.NO_MOVEMENT)

    def test_movement_exit_0(self):
        a = self.write("a.json", report())
        b = self.write("b.json", report(content_hash="sha256:cccc"))
        r = run_cli(a, b)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("moved source_doc_content_hash", r.stdout)

    def test_missing_file_exit_1(self):
        a = self.write("a.json", report())
        r = run_cli(a, self.dir / "nope.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot read", r.stderr)

    def test_invalid_json_exit_1(self):
        a = self.write("a.json", report())
        b = self.write("bad.json", "{not json")
        r = run_cli(a, b)
        self.assertEqual(r.returncode, 1)
        self.assertIn("invalid JSON", r.stderr)

    def test_no_items_exit_1(self):
        a = self.write("a.json", report())
        b = self.write("noitems.json", {"schema_version": 1})
        r = run_cli(a, b)
        self.assertEqual(r.returncode, 1)
        self.assertIn("'items'", r.stderr)

    def test_usage_error_exit_1(self):
        r = run_cli()
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
