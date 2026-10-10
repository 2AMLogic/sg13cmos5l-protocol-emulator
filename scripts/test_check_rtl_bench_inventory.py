#!/usr/bin/env python3
"""Fixture tests for scripts/check_rtl_bench_inventory.py (issue #225)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_rtl_bench_inventory as chk  # noqa: E402


def make_tree(inventory: str, requests: list[str]) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "scripts").mkdir()
    (root / "verification").mkdir()
    (root / chk.INVENTORY).write_text(inventory)
    for r in requests:
        (root / "verification" / f"request-{r}.json").write_text("{}")
    return root


class InventoryTests(unittest.TestCase):
    def test_clean(self):
        root = make_tree("include a\nexclude b :: slow, formal-adjacent\n", ["a", "b"])
        inc, errs = chk.check(root)
        self.assertEqual((inc, errs), (["a"], []))

    def test_unclassified_request_fails(self):
        root = make_tree("include a\n", ["a", "new"])
        _, errs = chk.check(root)
        self.assertEqual(len(errs), 1)
        self.assertIn("request-new.json", errs[0])

    def test_stale_entry_fails(self):
        root = make_tree("include a\ninclude gone\n", ["a"])
        _, errs = chk.check(root)
        self.assertTrue(any("'gone'" in e for e in errs))

    def test_stale_exclusion_fails(self):
        root = make_tree("include a\nexclude gone :: why\n", ["a"])
        _, errs = chk.check(root)
        self.assertTrue(any("'gone'" in e for e in errs))

    def test_exclusion_needs_reason(self):
        root = make_tree("include a\nexclude b ::\n", ["a", "b"])
        _, errs = chk.check(root)
        self.assertTrue(errs)

    def test_duplicate_fails(self):
        root = make_tree("include a\nexclude a :: why\n", ["a"])
        _, errs = chk.check(root)
        self.assertTrue(any("more than once" in e for e in errs))

    def test_unknown_directive_fails(self):
        root = make_tree("run a\ninclude a\n", ["a"])
        _, errs = chk.check(root)
        self.assertTrue(any("unrecognised" in e for e in errs))

    def test_missing_inventory_fails(self):
        root = Path(tempfile.mkdtemp())
        _, errs = chk.check(root)
        self.assertTrue(errs)

    def test_real_tree_passes(self):
        _, errs = chk.check(chk.DEFAULT_ROOT)
        self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
