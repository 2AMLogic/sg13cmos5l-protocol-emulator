#!/usr/bin/env python3
"""Self-test for scripts/characterization_report.py.

Run: python3 scripts/test_characterization_report.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import characterization_report as cr  # noqa: E402

MANIFEST = "manifests/sg13cmos5l-protocol-emulator.json"

REC = '<!-- record-meta\n{{"record_id": "{rid}", "supersedes": {sup}}}\n-->\n'


def write_records(root: Path, exp: str, records) -> None:
    d = root / "verification/records" / exp / "records"
    d.mkdir(parents=True, exist_ok=True)
    for rid, sup in records:
        (d / f"{rid}.md").write_text(REC.format(rid=rid, sup=json.dumps(sup)))


def make_repo(root: Path, digest_state="met", records=None, evidence=None, owner=None):
    write_records(root, "exp", records if records is not None else [("20260101-000000-aaaaaaa", None)])
    (root / "spec").mkdir()
    (root / "spec/target-spec.md").write_text("| 1 | Row one | t |\n")
    (root / "spec/gap-to-submission.md").write_text(
        "## Current reading\n\n| # | S | R | I | L |\n|---|---|---|---|---|\n"
        f"| 1 | {digest_state} | why | none | [row 1](#x) |\n\n## Spec rows\n"
    )
    ev = evidence if evidence is not None else [{"experiment": "exp"}]
    row = {"target": "t", "measured": "m", "conditions": "c", "evidence": ev}
    if owner is not None:
        row["owner"] = owner
    src = {
        "rows": {"1": row},
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


def write_manifest(root: Path, pin: str | None) -> None:
    cite = {"file": cr.ENVELOPE, "content_hash": pin} if pin is not None else {}
    manifest = {"evidence": {}} if not cite else {"evidence": {"8": cite}}
    (root / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")


def make_current(root: Path, pin: str | None = "auto", **kw) -> str:
    """Fixture tree whose generated outputs are fresh; returns the envelope hash.

    pin="auto" writes the matching item 8 pin; None omits the citation; any
    other value is written verbatim (a stale pin).
    """
    make_repo(root, **kw)
    report, env = cr.build(root)
    (root / cr.REPORT).write_text(report)
    (root / cr.ENVELOPE).parent.mkdir(parents=True, exist_ok=True)
    (root / cr.ENVELOPE).write_text(env)
    want = json.loads(env)["provenance"]["input"]["content_hash"]
    write_manifest(root, want if pin == "auto" else pin)
    return want


def check(root: Path) -> tuple[int, str]:
    with mock.patch.object(cr, "REPO", root), redirect_stderr(io.StringIO()) as err:
        code = cr.main(["--check"])
    return code, err.getvalue()


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
        _, env = self.build(digest_state="unmet", owner={"issues": [42]})
        self.assertEqual(json.loads(env)["status"], "fail")

    def test_missing_record_rejected(self):
        with self.assertRaises(cr.Invalid):
            self.build(evidence=[{"experiment": "exp", "record_id": "nope"}])

    def test_unknown_experiment_rejected(self):
        for exp in ("nope", 42, None):
            with self.assertRaises(cr.Invalid) as cm:
                self.build(evidence=[{"experiment": exp}])
            self.assertIn(f"experiment {exp!r} has no live record", str(cm.exception))

    def test_superseded_record_rejected(self):
        recs = [("20260101-000000-aaaaaaa", None), ("20260102-000000-bbbbbbb", "20260101-000000-aaaaaaa")]
        with self.assertRaises(cr.Invalid):
            self.build(records=recs, evidence=[{"experiment": "exp", "record_id": "20260101-000000-aaaaaaa"}])

    def test_record_named_in_supersedes_list_rejected(self):
        # #472: a list-form supersedes makes every named record superseded.
        recs = [
            ("20260101-000000-aaaaaaa", None),
            ("20260101-000005-bbbbbbb", None),
            ("20260102-000000-ccccccc", ["20260101-000000-aaaaaaa", "20260101-000005-bbbbbbb"]),
        ]
        with self.assertRaises(cr.Invalid):
            self.build(records=recs, evidence=[{"experiment": "exp", "record_id": "20260101-000005-bbbbbbb"}])

    def test_only_valid_siblings_are_superseded(self):
        a, b, c = ("20260101-000000-aaaaaaa", "20260101-000005-bbbbbbb", "20260102-000000-ccccccc")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root, records=[(a, [b]), (b, None), (c, [a, b, b, c, None])])
            self.assertEqual(set(cr.live_records(root, ["exp"])["exp"]), {b, c})

    def test_report_cites_latest_after_supersede(self):
        recs = [("20260101-000000-aaaaaaa", None), ("20260102-000000-bbbbbbb", "20260101-000000-aaaaaaa")]
        report, _ = self.build(records=recs)
        self.assertIn("20260102-000000-bbbbbbb", report)
        self.assertNotIn("20260101-000000-aaaaaaa", report)

    def test_report_cites_latest_after_list_supersede(self):
        recs = [
            ("20260101-000000-aaaaaaa", None),
            ("20260101-000005-bbbbbbb", None),
            ("20260102-000000-ccccccc", ["20260101-000000-aaaaaaa", "20260101-000005-bbbbbbb"]),
        ]
        report, _ = self.build(records=recs)
        self.assertIn("20260102-000000-ccccccc", report)
        self.assertNotIn("20260101-000000-aaaaaaa", report)
        self.assertNotIn("20260101-000005-bbbbbbb", report)

    def test_met_without_evidence_rejected(self):
        with self.assertRaises(cr.Invalid):
            self.build(evidence=[])

    def test_unmet_without_evidence_is_no_evidence(self):
        report, env = self.build(digest_state="unmet", evidence=[], owner={"waits": "DR 9 ratification"})
        self.assertIn("no evidence: why", report)
        self.assertEqual(json.loads(env)["status"], "fail")

    def test_failing_row_without_owner_rejected(self):
        with self.assertRaises(cr.Invalid) as cm:
            self.build(digest_state="unmet")
        self.assertIn("row 1: failing row carries no owner", str(cm.exception))

    def test_failing_row_with_empty_owner_rejected(self):
        with self.assertRaises(cr.Invalid):
            self.build(digest_state="unmet", owner={})
        with self.assertRaises(cr.Invalid):
            self.build(digest_state="unmet", owner={"issues": []})
        with self.assertRaises(cr.Invalid):
            self.build(digest_state="unmet", owner={"issues": [0]})
        with self.assertRaises(cr.Invalid):
            self.build(digest_state="unmet", owner={"issues": [7, 7]})
        with self.assertRaises(cr.Invalid):
            self.build(digest_state="unmet", owner={"issues": "x"})
        with self.assertRaises(cr.Invalid):
            self.build(digest_state="unmet", owner={"waits": "  "})

    def test_owner_issues_render_as_clickable_links(self):
        report, env = self.build(digest_state="unmet", owner={"issues": [42, 43]})
        self.assertIn(
            f"[#42](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/issues/42)", report
        )
        self.assertIn(
            f"[#43](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/issues/43)", report
        )
        self.assertEqual(json.loads(env)["status"], "fail")

    def test_named_wait_renders(self):
        report, _ = self.build(digest_state="unmet", owner={"waits": "DR 0005 (SRAM macro) ratification"})
        self.assertIn("waits on DR 0005 (SRAM macro) ratification", report)

    def test_owner_issues_and_wait_render_together(self):
        report, _ = self.build(
            digest_state="unmet", owner={"issues": [7], "waits": "DR 0005 ratification"}
        )
        self.assertIn(
            "waits on DR 0005 ratification; [#7](https://github.com/2AMLogic/sg13cmos5l-protocol-emulator/issues/7)",
            report,
        )

    def test_owner_metadata_leaves_verdict_and_failing_rows_intact(self):
        report, env = self.build(digest_state="unmet", owner={"issues": [42]})
        self.assertIn("fail: why", report)
        self.assertIn("Rows not passing: 1.", report)
        self.assertIn("rows not passing: 1", env)
        self.assertEqual(json.loads(env)["status"], "fail")

    def test_owner_column_is_the_only_table_difference(self):
        plain = self.build()
        owned = self.build(owner={"issues": [42]})
        strip = lambda r: [  # noqa: E731
            line.rsplit("|", 2)[0] + "|" for line in r.splitlines() if line.startswith("|")
        ]
        self.assertEqual(strip(plain[0]), strip(owned[0]))
        self.assertNotEqual(plain[0], owned[0])

    def test_passing_row_needs_no_owner(self):
        report, env = self.build()
        self.assertIn("| none |", report)
        self.assertEqual(json.loads(env)["status"], "pass")


    def test_drift_detected_on_committed_tree(self):
        self.assertEqual(cr.main(["--check"]), 0)


class ReadScope(unittest.TestCase):
    """The build reads only the experiments it cites, each once (issue #625)."""

    A, B, C = ("20260101-000000-aaaaaaa", "20260102-000000-bbbbbbb", "20260103-000000-ccccccc")

    def record_reads(self, root: Path) -> list[tuple[str, str]]:
        """(experiment, record_id) for each record file build() reads, in order."""
        seen = []
        read_text = Path.read_text

        def spy(path, *args, **kw):
            seen.append(path)
            return read_text(path, *args, **kw)

        with mock.patch.object(Path, "read_text", spy):
            cr.build(root)
        return [(p.parent.parent.name, p.stem) for p in seen if p.parent.name == "records"]

    def test_uncited_experiment_is_not_read(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            make_repo(root)
            write_records(root, "other", [("20260101-000000-zzzzzzz", None)])
            write_records(root, "sibling", [("20260101-000000-yyyyyyy", None)])
            self.assertEqual(self.record_reads(root), [("exp", self.A)])

    def test_cited_experiment_read_once_including_superseded_records(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            make_repo(root, records=[(self.A, None), (self.B, self.A), (self.C, [self.A, self.B])])
            self.assertEqual(self.record_reads(root), [("exp", self.A), ("exp", self.B), ("exp", self.C)])


class PinCheck(unittest.TestCase):
    """--check also validates the top manifest's item 8 citation (issue #458)."""

    def test_check_passes_when_tree_current(self):
        with tempfile.TemporaryDirectory() as t:
            make_current(Path(t))
            code, err = check(Path(t))
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_check_passes_with_failing_verdict(self):
        with tempfile.TemporaryDirectory() as t:
            make_current(Path(t), digest_state="unmet", owner={"issues": [42]})
            code, err = check(Path(t))
        self.assertEqual((code, err), (0, ""))

    def regenerate(self, root: Path) -> None:
        with mock.patch.object(cr, "REPO", root):
            self.assertEqual(cr.main([]), 0)

    def test_source_change_reports_drift_and_stale_pin_together(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            old_hash = make_current(root)
            before = {rel: (root / rel).read_bytes() for rel in (cr.REPORT, cr.ENVELOPE, MANIFEST)}
            src = json.loads((root / cr.SOURCES).read_text())
            src["rows"]["1"]["measured"] = "changed"
            (root / cr.SOURCES).write_text(json.dumps(src))
            code, err = check(root)
            self.assertEqual(code, 1)
            self.assertIn(f"{cr.REPORT} is out of date", err)
            self.assertIn(f"{cr.ENVELOPE} is out of date", err)
            fresh = json.loads(cr.build(root)[1])["provenance"]["input"]["content_hash"]
            self.assertNotEqual(fresh, old_hash)
            self.assertIn(f'{MANIFEST}: evidence["8"].content_hash pins {old_hash}', err)
            self.assertIn(f"the freshly built envelope records {fresh}", err)
            self.assertIn("remediate in order", err)
            self.assertIn("scripts/signoff-report.sh", err)
            self.assertIn("verification/check_records.py", err)
            for rel, data in before.items():  # --check leaves every file untouched
                self.assertEqual((root / rel).read_bytes(), data, rel)

    def test_stale_pin_alone_after_regeneration(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            old_hash = make_current(root)
            src = json.loads((root / cr.SOURCES).read_text())
            src["rows"]["1"]["measured"] = "changed"
            (root / cr.SOURCES).write_text(json.dumps(src))
            self.regenerate(root)  # generation writes only the report and envelope
            manifest = json.loads((root / MANIFEST).read_text())
            self.assertEqual(manifest["evidence"]["8"]["content_hash"], old_hash)
            env = json.loads((root / cr.ENVELOPE).read_text())
            self.assertNotEqual(env["provenance"]["input"]["content_hash"], old_hash)
            code, err = check(root)
            self.assertEqual(code, 1)
            self.assertIn(f'{MANIFEST}: evidence["8"].content_hash pins {old_hash}', err)
            self.assertIn(env["provenance"]["input"]["content_hash"], err)
            self.assertNotIn("is out of date", err)
            manifest["evidence"]["8"]["content_hash"] = env["provenance"]["input"]["content_hash"]
            (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
            code, err = check(root)
            self.assertEqual((code, err), (0, ""))

    def test_missing_pin_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            want = make_current(root, pin=None)
            code, err = check(root)
            self.assertEqual(code, 1)
            self.assertIn(f'{MANIFEST}: evidence["8"].content_hash is missing', err)
            self.assertIn(want, err)
            self.assertIn("remediate in order", err)

    def test_unreadable_manifest_fails(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            make_current(root)
            (root / MANIFEST).write_text("{not json")
            code, err = check(root)
        self.assertEqual(code, 1)
        self.assertIn(f"{MANIFEST} is not readable JSON", err)


if __name__ == "__main__":
    unittest.main()
