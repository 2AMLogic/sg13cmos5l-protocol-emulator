#!/usr/bin/env python3
"""Self-test for scripts/characterization_report.py.

Run: python3 scripts/test_characterization_report.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import characterization_report as cr  # noqa: E402

REC = '<!-- record-meta\n{{"record_id": "{rid}", "supersedes": {sup}}}\n-->\n'


def make_repo(root: Path, digest_state="met", records=None, evidence=None):
    records = records if records is not None else [("20260101-000000-aaaaaaa", None)]
    for rid, sup in records:
        d = root / "verification/records/exp/records"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{rid}.md").write_text(REC.format(rid=rid, sup=json.dumps(sup)))
    (root / "spec").mkdir()
    (root / "spec/target-spec.md").write_text("| 1 | Row one | t |\n")
    (root / "spec/gap-to-submission.md").write_text(
        "## Current reading\n\n| # | S | R | I | L |\n|---|---|---|---|---|\n"
        f"| 1 | {digest_state} | why | none | [row 1](#x) |\n\n## Spec rows\n"
    )
    ev = evidence if evidence is not None else [{"experiment": "exp"}]
    src = {
        "rows": {"1": {"target": "t", "measured": "m", "conditions": "c", "evidence": ev}},
        "clock_ns": 20.0,
        "timing_flow": "f",
        "timing_record": {"experiment": "exp"},
        "corners": [{"corner": "c", "setup_slack_ns": 5.0, "hold_slack_ns": 0.1}],
        "klt_timing": {"flow": "klt", "status": "none", "evidence": [{"experiment": "exp"}]},
        "area": [],
        "power": {"value": "no evidence", "reason": "r", "evidence": [{"experiment": "exp"}]},
        "findings": [],
    }
    (root / "measurements").mkdir()
    (root / "measurements/characterization-sources.json").write_text(json.dumps(src))


class Report(unittest.TestCase):
    def build(self, **kw):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            make_repo(root, **kw)
            return cr.build(root)

    def test_pass_when_all_rows_met(self):
        report, env = self.build()
        self.assertEqual(json.loads(env)["status"], "pass")
        self.assertIn("66.7", report)  # 1000 / (20 - 5)

    def test_failing_row_forces_envelope_fail(self):
        _, env = self.build(digest_state="unmet")
        self.assertEqual(json.loads(env)["status"], "fail")

    def test_missing_record_rejected(self):
        with self.assertRaises(cr.Invalid):
            self.build(evidence=[{"experiment": "exp", "record_id": "nope"}])

    def test_superseded_record_rejected(self):
        recs = [("20260101-000000-aaaaaaa", None), ("20260102-000000-bbbbbbb", "20260101-000000-aaaaaaa")]
        with self.assertRaises(cr.Invalid):
            self.build(records=recs, evidence=[{"experiment": "exp", "record_id": "20260101-000000-aaaaaaa"}])

    def test_report_cites_latest_after_supersede(self):
        recs = [("20260101-000000-aaaaaaa", None), ("20260102-000000-bbbbbbb", "20260101-000000-aaaaaaa")]
        report, _ = self.build(records=recs)
        self.assertIn("20260102-000000-bbbbbbb", report)
        self.assertNotIn("20260101-000000-aaaaaaa", report)

    def test_met_without_evidence_rejected(self):
        with self.assertRaises(cr.Invalid):
            self.build(evidence=[])

    def test_unmet_without_evidence_is_no_evidence(self):
        report, env = self.build(digest_state="unmet", evidence=[])
        self.assertIn("no evidence: why", report)
        self.assertEqual(json.loads(env)["status"], "fail")

    def test_drift_detected_on_committed_tree(self):
        self.assertEqual(cr.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
