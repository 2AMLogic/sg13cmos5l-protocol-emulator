#!/usr/bin/env python3
"""Self-test for scripts/check_gap_digest.py.

Run: python3 scripts/test_check_gap_digest.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_gap_digest as cgd  # noqa: E402

ANCHOR = "spec-rows-spectarget-specmd"


def line(n, state="unmet", reason="why", issues="none", link=None):
    link = link or f"[row {n}](#{ANCHOR})"
    return f"| {n} | {state} | {reason} | {issues} | {link} |"


def doc(digest_lines, main_rows=(1, 2, 3)):
    main = "\n".join(f"| {n} | P | S | long cell |" for n in main_rows)
    return (
        "# t\n\n## Current reading\n\nintro\n\n"
        "| # | State | Blocking reason | Open issues | Row |\n|---|---|---|---|---|\n"
        + "\n".join(digest_lines)
        + "\n\n## Spec rows (`spec/target-spec.md`)\n\n| # | P | S | G |\n|---|---|---|---|\n"
        + main + "\n\n## Decision records\n\n| Record | Status |\n|---|---|\n| 0001 | x |\n"
    )


GOOD = [line(1), line(2, "met"), line(3, "proposed", issues="#5, #6")]


class GapDigest(unittest.TestCase):
    def errs(self, d):
        return cgd.check(d)

    def test_pass(self):
        self.assertEqual(self.errs(doc(GOOD)), [])

    def test_missing_row(self):
        e = self.errs(doc(GOOD[:2]))
        self.assertTrue(any("row 3: missing" in x for x in e), e)

    def test_duplicate_row(self):
        e = self.errs(doc(GOOD + [line(2)]))
        self.assertTrue(any("row 2: 2 lines" in x for x in e), e)

    def test_bad_state(self):
        e = self.errs(doc([line(1), line(2, "done"), line(3)]))
        self.assertTrue(any("state 'done'" in x for x in e), e)

    def test_extra_row(self):
        e = self.errs(doc(GOOD + [line(4)]))
        self.assertTrue(any("row 4: outside" in x for x in e), e)

    def test_empty_reason(self):
        e = self.errs(doc([line(1), line(2, reason=""), line(3)]))
        self.assertTrue(any("empty blocking reason" in x for x in e), e)

    def test_bad_issues_cell(self):
        e = self.errs(doc([line(1), line(2, issues="282"), line(3)]))
        self.assertTrue(any("open issues" in x for x in e), e)

    def test_bad_link(self):
        e = self.errs(doc([line(1), line(2, link="[row 2](#nowhere)"), line(3)]))
        self.assertTrue(any("does not resolve" in x for x in e), e)
        e = self.errs(doc([line(1), line(2, link=f"[row 3](#{ANCHOR})"), line(3)]))
        self.assertTrue(any("is not `[row 2]" in x for x in e), e)

    def test_main_table_grows(self):
        e = self.errs(doc(GOOD, main_rows=(1, 2, 3, 4)))
        self.assertTrue(any("row 4: missing" in x for x in e), e)

    def test_no_digest(self):
        self.assertTrue(self.errs("## Spec rows\n\n| # |\n|---|\n| 1 |\n"))

    def test_slug(self):
        self.assertEqual(cgd.slug("Spec rows (`spec/target-spec.md`)"), ANCHOR)

    def test_digest_issues(self):
        self.assertEqual(cgd.digest_issues(doc(GOOD)), [(3, 5), (3, 6)])

    def test_committed_file(self):
        self.assertEqual(cgd.check(cgd.DEFAULT_PATH.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
