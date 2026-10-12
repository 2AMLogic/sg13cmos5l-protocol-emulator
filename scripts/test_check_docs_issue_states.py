#!/usr/bin/env python3
"""Offline tests for scripts/check_docs_issue_states.py's text heuristics (#238).

Only the parsing and the state comparison are tested; nothing here calls `gh`.

    python3 scripts/test_check_docs_issue_states.py
"""
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_docs_issue_states as c  # noqa: E402

REPO = "2AMLogic/sg13cmos5l-protocol-emulator"


def claims(text):
    return [(n, claim) for _, n, claim, _ in c.claims_in_text(text, REPO)]


class Claims(unittest.TestCase):
    def test_state_after_and_before(self):
        self.assertEqual(claims("#217 is still open"), [(217, "open")])
        self.assertEqual(claims("open PR #248 for issue #211"), [(248, "open"), (211, "open")])
        self.assertEqual(claims("PR #84 is unmerged"), [(84, "not-merged")])
        self.assertEqual(claims("#85 is no longer open"), [(85, "closed")])

    def test_asides(self):
        self.assertEqual(claims("#244 (routed glitch) and #217 (no SDF) are still open"),
                         [(244, "open"), (217, "open")])
        self.assertEqual(claims("an open finding (F8, #211)"), [(211, "open")])
        self.assertEqual(claims("the stretch column (issue #235) is closed"), [(235, "closed")])
        self.assertEqual(claims("(for example #160, #207), so agent sessions under the account also open PRs"),
                         [])

    def test_not_state_words(self):
        self.assertEqual(claims("open-drain pins on #244"), [])
        self.assertEqual(claims("an open drain pin, #244"), [])
        self.assertEqual(claims("DR 0012's open items, #135"), [])
        self.assertEqual(claims("opened 2026-10-09 for issue #134"), [])

    def test_breaks(self):
        self.assertEqual(claims("#211 is fixed. The other one is open"), [])
        self.assertEqual(claims("| #211 | open |"), [])
        self.assertEqual(claims("**Updated (#238):** #155 closed"), [(155, "closed")])

    def test_skips(self):
        self.assertEqual(claims("klayout-tools#2635 is still open"), [])
        self.assertEqual(claims("still open: [#2635](https://github.com/2AMLogic/klayout-tools/issues/2635)"), [])
        self.assertEqual(claims(f"open [#44](https://github.com/{REPO}/issues/44)"), [(44, "open")])
        self.assertEqual(claims("#217 is still open <!-- state-ok: dated 2026-10-10 text -->"), [])

    def test_units_join_wrapped_lines(self):
        text = "- #217 is still\n  open, and\n- #44 closed\n\n| #85 | merged |\n"
        units = [" ".join(l.strip() for _, l in u) for u in c.units(text)]
        self.assertEqual(units, ["- #217 is still open, and", "- #44 closed", "| #85 | merged |"])


class Mismatch(unittest.TestCase):
    def test_compare(self):
        closed_issue = {"kind": "issue", "state": "closed", "merged": False}
        merged_pr = {"kind": "pr", "state": "closed", "merged": True}
        open_pr = {"kind": "pr", "state": "open", "merged": False}
        self.assertTrue(c.mismatch("open", closed_issue))
        self.assertFalse(c.mismatch("closed", closed_issue))
        self.assertFalse(c.mismatch("merged", merged_pr))
        self.assertTrue(c.mismatch("merged", open_pr))
        self.assertTrue(c.mismatch("not-merged", merged_pr))
        self.assertFalse(c.mismatch("merged", closed_issue))


class Digest(unittest.TestCase):
    TEXT = (
        "## Current reading\n\n| # | State | Blocking reason | Open issues | Row |\n|---|---|---|---|---|\n"
        "| 1 | unmet | r | #10, #11 | [row 1](#x) |\n"
        "| 2 | unmet | r | #12, #13 | [row 2](#x) |\n"
        "| 3 | met | r | none | [row 3](#x) |\n\n## Spec rows\n"
    )

    def test_flags_closed_pr_and_missing(self):
        live = {
            10: {"kind": "issue", "state": "open", "merged": False},
            11: {"kind": "issue", "state": "closed", "merged": False},
            12: {"kind": "pr", "state": "open", "merged": False},
        }
        self.assertEqual(
            c.digest_problems(self.TEXT, live.get),
            [(1, 11, "is closed"), (2, 12, "is a pull request"), (2, 13, "does not exist")],
        )

    def test_committed_digest_parses(self):
        text = c.check_gap_digest.DEFAULT_PATH.read_text(encoding="utf-8")
        self.assertTrue(c.check_gap_digest.digest_issues(text))


if __name__ == "__main__":
    unittest.main(verbosity=1)
