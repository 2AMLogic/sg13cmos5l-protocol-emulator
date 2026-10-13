#!/usr/bin/env python3
"""Self-test for scripts/check_ratification_batch.py.

Run: python3 scripts/test_check_ratification_batch.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_ratification_batch as crb  # noqa: E402


def batch(*rows):
    head = "| Item | Status today | Dep | Note | Blockers | Recommendation |\n|---|---|---|---|---|---|\n"
    return "# b\n\n" + head + "\n".join(f"| {i} | s | d | n | none | {r} |" for i, r in rows) + "\n"


STATES = {"0001": "ratified", "0005": "proposed", "0012": "proposed", "0006": "other"}


class Batch(unittest.TestCase):
    def test_pass(self):
        b = batch(("DR 0005", "ratify"), ("DR 0012", "amend first"), ("row 13", "defer"))
        self.assertEqual(crb.check(b, STATES, {"0001": {"a"}, "0005": {"a"}}), [])

    def test_cited_unlisted_proposed_fails(self):
        e = crb.check(batch(("DR 0005", "ratify"), ("DR 0012", "ratify")), STATES, {"0005": {"x.v"}, "0012": {"y.v"}})
        self.assertEqual(e, [])
        e = crb.check(batch(("DR 0005", "ratify")), STATES, {"0012": {"y.v"}})
        self.assertTrue(any("DR 0012 is cited" in x and "not listed" in x for x in e), e)

    def test_cited_ratified_needs_no_listing(self):
        e = crb.check(batch(("DR 0005", "ratify"), ("DR 0012", "ratify")), STATES, {"0001": {"y.v"}})
        self.assertEqual(e, [])

    def test_uncited_proposed_must_be_listed(self):
        e = crb.check(batch(("DR 0005", "ratify")), STATES, {})
        self.assertTrue(any("DR 0012 is Proposed" in x for x in e), e)

    def test_recorded_dr_needs_no_key_unless_rtl_cites_it(self):
        b = batch(("DR 0005", "ratify"), ("DR 0012", "ratify"))
        self.assertEqual(crb.check(b, STATES, {}), [])
        e = crb.check(b, STATES, {"0006": {"y.v"}})
        self.assertTrue(any("DR 0006 is cited" in x for x in e), e)

    def test_bad_recommendation(self):
        e = crb.check(batch(("DR 0005", "maybe"), ("DR 0012", "ratify")), STATES, {})
        self.assertTrue(any("'maybe'" in x for x in e), e)

    def test_unknown_and_duplicate(self):
        e = crb.check(batch(("DR 0005", "ratify"), ("DR 0005", "ratify"), ("DR 0012", "defer"), ("DR 0099", "defer")), STATES, {})
        self.assertTrue(any("DR 0099: no such" in x for x in e), e)
        self.assertTrue(any("DR 0005: listed 2" in x for x in e), e)

    def test_cited_missing_record(self):
        e = crb.check(batch(("DR 0005", "ratify"), ("DR 0012", "ratify")), STATES, {"0099": {"y.v"}})
        self.assertTrue(any("DR 0099 is cited" in x for x in e), e)


class Parsing(unittest.TestCase):
    def test_citation_forms(self):
        t = "// DR 0012 and DR-0005, DRs 0001, 0013 and 0015\n decision record 0020 spec/decision-records/0008-x.md"
        self.assertEqual(crb.rtl_citations(t), {"0012", "0005", "0001", "0013", "0015", "0020", "0008"})

    def test_no_false_positive(self):
        self.assertEqual(crb.rtl_citations("issue #1234, width 0012, addr 0005"), set())

    def test_status(self):
        s = crb.dr_state
        self.assertEqual(s("# t\nStatus: **Ratified** - by"), "ratified")
        self.assertEqual(s("# t\nStatus: **Proposed 2026-10-09.** x"), "proposed")
        self.assertEqual(s("# t\nStatus: **Recorded 2026-10-11**"), "other")
        self.assertEqual(s("# t\nStatus: not ratified"), "other")


class Repo(unittest.TestCase):
    def test_committed_batch_passes(self):
        text = crb.DEFAULT_BATCH.read_text(encoding="utf-8")
        errs = crb.check(text, crb.load_states(crb.DR_DIR), crb.load_citations(crb.REPO_ROOT))
        self.assertEqual(errs, [])

    def test_rtl_cites_something(self):
        self.assertTrue(crb.load_citations(crb.REPO_ROOT))


if __name__ == "__main__":
    unittest.main()
